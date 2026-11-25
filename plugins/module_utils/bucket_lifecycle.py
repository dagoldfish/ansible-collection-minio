# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reconcile lifecycle rules without losing server-specific XML in unrelated rules."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from copy import deepcopy
from xml.etree import ElementTree as ET


def rules_argument_spec():
    return dict(type="list", elements="dict", options={
        "id": dict(type="str", required=True),
        "state": dict(type="str", choices=["present", "absent"], default="present"),
        "enabled": dict(type="bool", default=True),
        "prefix": dict(type="str", default=""),
        "expiration_days": dict(type="int"),
        "noncurrent_expiration_days": dict(type="int"),
        "newer_noncurrent_versions": dict(type="int"),
        "expired_object_delete_marker": dict(type="bool", default=False),
        "transition_days": dict(type="int"),
        "transition_tier": dict(type="str"),
    })


def desired_rules(rules):
    desired = {}
    for rule in rules or []:
        identifier = rule["id"]
        if not identifier.strip() or len(identifier.encode("utf-8")) > 255 or identifier in desired:
            raise ValueError("Each lifecycle rule needs a unique, nonempty ID of at most 255 UTF-8 bytes.")
        desired[identifier] = None
        if rule.get("state") == "absent":
            continue
        element = ET.Element("Rule")
        ET.SubElement(element, "ID").text = identifier
        rule_filter = ET.SubElement(element, "Filter")
        if rule.get("prefix"):
            ET.SubElement(rule_filter, "Prefix").text = rule["prefix"]
        ET.SubElement(element, "Status").text = "Enabled" if rule.get("enabled", True) else "Disabled"
        expiration = rule.get("expiration_days")
        noncurrent = rule.get("noncurrent_expiration_days")
        keep = rule.get("newer_noncurrent_versions")
        marker = rule.get("expired_object_delete_marker")
        transition = rule.get("transition_days")
        tier = rule.get("transition_tier")
        if any(n is not None and n < 1 for n in (expiration, noncurrent, keep)):
            raise ValueError("Expiration days and newer_noncurrent_versions must be positive.")
        if keep is not None and noncurrent is None:
            raise ValueError("newer_noncurrent_versions requires noncurrent_expiration_days.")
        if expiration is not None and marker:
            raise ValueError("expiration_days and expired_object_delete_marker are mutually exclusive.")
        if (transition is not None) != bool(tier) or (transition is not None and transition < 0):
            raise ValueError("A transition requires transition_tier and nonnegative transition_days.")
        if expiration is None and noncurrent is None and transition is None and not marker:
            raise ValueError("A present lifecycle rule requires at least one lifecycle action.")
        if expiration is not None or marker:
            action = ET.SubElement(element, "Expiration")
            if marker:
                ET.SubElement(action, "ExpiredObjectDeleteMarker").text = "true"
            else:
                ET.SubElement(action, "Days").text = str(expiration)
        if noncurrent is not None:
            action = ET.SubElement(element, "NoncurrentVersionExpiration")
            ET.SubElement(action, "NoncurrentDays").text = str(noncurrent)
            if keep is not None:
                ET.SubElement(action, "NewerNoncurrentVersions").text = str(keep)
        if transition is not None:
            action = ET.SubElement(element, "Transition")
            ET.SubElement(action, "Days").text = str(transition)
            ET.SubElement(action, "StorageClass").text = tier
        desired[identifier] = element
    return desired


def _signature(element):
    # Servers may reorder fields and encode an all-objects filter with an empty Prefix.
    children = sorted(_signature(child) for child in element)
    namespace = element.tag.rpartition("}")[0] + "}" if element.tag.startswith("{") else ""
    if element.tag == namespace + "Filter" and children == [(namespace + "Prefix", "", [], [])]:
        children = []
    # MinIO omits Days on readback for an immediate tier transition.
    if element.tag == namespace + "Transition" and element.find(namespace + "Date") is None:
        zero_days = (namespace + "Days", "0", [], [])
        if zero_days in children:
            children.remove(zero_days)
    value = "" if len(element) else element.text or ""
    return element.tag, value, sorted(element.attrib.items()), children


def reconcile_lifecycle(client, name, desired, exists, check_mode):
    from minio.error import S3Error
    from minio.helpers import check_bucket_name, md5sum_hash

    check_bucket_name(name, s3_check=client._base_url.is_aws_host)
    if not desired:
        return False
    root = ET.Element("{http://s3.amazonaws.com/doc/2006-03-01/}LifecycleConfiguration")
    if exists:
        # The SDK model drops unknown fields on a get/set round trip. Keep the
        # original XML tree because S3 only accepts whole-configuration writes.
        try:
            response = client._execute("GET", name, query_params={"lifecycle": ""})
        except S3Error as error:
            if error.code != "NoSuchLifecycleConfiguration":
                raise
        else:
            root = ET.fromstring(response.data)
    namespace = root.tag.rpartition("}")[0] + "}" if root.tag.startswith("{") else ""
    if root.tag != namespace + "LifecycleConfiguration":
        raise ValueError("Unexpected lifecycle configuration response.")
    current = {rule.findtext(namespace + "ID"): rule for rule in root.findall(namespace + "Rule")}
    changed = False
    for identifier, replacement in desired.items():
        old = current.get(identifier)
        if replacement is not None:
            replacement = deepcopy(replacement)
            for field in replacement.iter():
                field.tag = namespace + field.tag
            if old is not None and _signature(old) == _signature(replacement):
                continue
            root.append(replacement)
        elif old is None:
            continue
        if old is not None:
            root.remove(old)
        changed = True
    if changed and not check_mode:
        if len(root):
            # XML parsers normalize literal carriage returns to line feeds.
            body = ET.tostring(root, encoding="utf-8").replace(b"\r", b"&#13;")
            client._execute(
                "PUT", name, body=body, headers={"Content-MD5": md5sum_hash(body)},
                query_params={"lifecycle": ""},
            )
        else:
            client.delete_bucket_lifecycle(name)
    return changed
