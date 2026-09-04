#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage MinIO site-replication peers."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_site_replication
short_description: Manage MinIO AIStor site replication
description:
  - Creates or expands site replication without purging undeclared peers.
  - Removal requires both C(state=absent) and C(force=true).
  - Site names must be unique and bandwidth limits cannot be negative.
options:
  auth:
    description: Administrator connection settings for an active site.
    type: dict
    required: true
    suboptions:
      endpoint: {description: API endpoint., type: str, required: true}
      access_key: {description: Administrator access key., type: str, required: true}
      secret_key: {description: Administrator secret key., type: str, required: true}
      secure: {description: Use HTTPS., type: bool, default: true}
      validate_certs: {description: Validate TLS certificates., type: bool, default: true}
      region: {description: Signing region., type: str, default: ""}
  sites:
    description: Sites to create/add, or names to remove.
    type: list
    elements: dict
    default: []
    suboptions:
      name: {description: Site name., type: str, required: true}
      endpoint: {description: Site endpoint., type: str}
      access_key: {description: Site administrator access key., type: str}
      secret_key: {description: Site administrator secret key., type: str}
      sync: {description: Enable synchronous replication for this existing peer., type: bool}
      bandwidth_limit:
        description: Default per-bucket bandwidth limit in bytes per second.
        type: int
  remove_all: {type: bool, default: false, description: Remove the complete topology.}
  force: {type: bool, default: false, description: Required destructive-operation acknowledgement.}
  state: {description: Add or explicitly remove sites., type: str, choices: [present, absent], default: present}
  retry_delay:
    description: Seconds between retries after a transient Admin API or transport failure.
    type: int
    default: 5
  retry_timeout:
    description: Maximum retry window in seconds for topology reads and site additions.
    type: int
    default: 600
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: "Predicts peer additions, supported edits, and explicit removals."}
"""
EXAMPLES = r"""
- dagoldfish.minio.minio_site_replication:
    auth: "{{ aistor_auth }}"
    sites:
      - name: primary
        endpoint: https://aistor-primary.example.com:9000
        access_key: "{{ primary_access_key }}"
        secret_key: "{{ primary_secret_key }}"
      - name: recovery
        endpoint: https://aistor-recovery.example.com:9000
        access_key: "{{ recovery_access_key }}"
        secret_key: "{{ recovery_secret_key }}"
"""
RETURN = r"""
site_replication: {description: Current or predicted topology., returned: always, type: dict}
"""
import time

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    MinioAdminException,
    PeerInfo,
    PeerSite,
    admin_client,
    auth_argument_spec,
    fail_from_exception,
    is_transport_error,
    parse_json,
)


def _status_code(error):
    """Extract the HTTP status code exposed by minio-py's Admin exception."""
    try:
        return int(getattr(error, "_code", None))
    except (TypeError, ValueError):
        return None


def _is_retryable(error):
    """Limit retries to transport failures, rate limiting, and server errors."""
    if isinstance(error, MinioAdminException):
        status = _status_code(error)
        return status == 429 or (status is not None and 500 <= status <= 599)
    return is_transport_error(error)


def _retry_call(call, deadline, delay, sleep=time.sleep, monotonic=time.monotonic):
    """Retry one idempotent Admin API call within a shared deadline."""
    while True:
        try:
            return call()
        except Exception as error:
            now = monotonic()
            if not _is_retryable(error) or now >= deadline:
                raise
            sleep(min(delay, max(0, deadline - now)))


def _add_and_read_topology(
    client,
    peers,
    desired_names,
    deadline,
    delay,
    sleep=time.sleep,
    monotonic=time.monotonic,
):
    """Add peers, checking topology before retrying an ambiguous failed request."""
    while True:
        try:
            client.add_site_replication(peers)
        except Exception as error:
            now = monotonic()
            if not _is_retryable(error) or now >= deadline:
                raise
            info = _retry_call(
                client.get_site_replication_info,
                deadline,
                delay,
                sleep=sleep,
                monotonic=monotonic,
            )
            current_names = {site.get("name") for site in (parse_json(info, {}) or {}).get("sites", [])}
            if desired_names <= current_names:
                return info
            now = monotonic()
            if now >= deadline:
                raise error
            sleep(min(delay, max(0, deadline - now)))
            continue
        return _retry_call(
            client.get_site_replication_info,
            deadline,
            delay,
            sleep=sleep,
            monotonic=monotonic,
        )


def run(module, client):
    retry_delay = module.params.get("retry_delay", 5)
    retry_timeout = module.params.get("retry_timeout", 600)
    if retry_delay < 0:
        module.fail_json(msg="retry_delay must be greater than or equal to zero")
    if retry_timeout < 1:
        module.fail_json(msg="retry_timeout must be greater than zero")
    deadline = time.monotonic() + retry_timeout
    info = parse_json(
        _retry_call(client.get_site_replication_info, deadline, retry_delay),
        {},
    ) or {}
    existing = {s.get("name"): s for s in info.get("sites", [])}
    sites = module.params["sites"]
    state = module.params["state"]
    remove_all = module.params["remove_all"]
    names = [site["name"] for site in sites]
    if len(names) != len(set(names)):
        module.fail_json(msg="site names must be unique")
    for site in sites:
        if site.get("bandwidth_limit") is not None and site["bandwidth_limit"] < 0:
            module.fail_json(msg=f"bandwidth_limit cannot be negative for site {site['name']}")
    if state == "present" and (remove_all or module.params["force"]):
        module.fail_json(msg="remove_all and force are only valid when state=absent")
    if state == "absent":
        if not module.params["force"]:
            module.fail_json(msg="force=true is required to remove site replication")
        if remove_all and sites:
            module.fail_json(msg="sites must be empty when remove_all=true")
        if not remove_all and not sites:
            module.fail_json(msg="sites must contain at least one name when remove_all=false")
        changed = bool(existing) if remove_all else bool(set(names) & set(existing))
        if changed and not module.check_mode:
            client.remove_site_replication(sites=",".join(names) if names else None, all_sites=remove_all)
        predicted_sites = [] if remove_all else [site for name, site in existing.items() if name not in names]
        predicted = dict(info)
        predicted["sites"] = predicted_sites
        if not predicted_sites:
            predicted["enabled"] = False
        module.exit_json(changed=changed, site_replication=predicted)
    missing = [s for s in sites if s["name"] not in existing]
    for site in missing:
        for field in ("endpoint", "access_key", "secret_key"):
            if not site.get(field):
                module.fail_json(msg=f"{field} is required when adding site {site['name']}")
    if missing and not module.check_mode:
        peers = [PeerSite(s["name"], s["endpoint"], s["access_key"], s["secret_key"]) for s in missing]
        info = parse_json(
            _add_and_read_topology(
                client,
                peers,
                {site["name"] for site in missing},
                deadline,
                retry_delay,
            ),
            {},
        ) or {}
        existing = {s.get("name"): s for s in info.get("sites", [])}
    edits = []
    for site in sites:
        current = existing.get(site["name"])
        if not current:
            continue
        desired_endpoint = site.get("endpoint") or current.get("endpoint")
        desired_sync = (
            ("enable" if site["sync"] else "disable") if site.get("sync") is not None else current.get("sync")
        )
        bandwidth = current.get("defaultbandwidth", {})
        desired_bandwidth = (
            site.get("bandwidth_limit")
            if site.get("bandwidth_limit") is not None
            else bandwidth.get("bandwidthLimitPerBucket", 0)
        )
        if (
            desired_endpoint != current.get("endpoint")
            or desired_sync != current.get("sync")
            or desired_bandwidth != bandwidth.get("bandwidthLimitPerBucket", 0)
        ):
            edits.append((site, current, desired_endpoint, desired_sync, desired_bandwidth))
    if edits and not module.check_mode:
        for site, current, endpoint, sync, bandwidth in edits:
            sync_enabled = None if sync not in ("enable", "disable") else sync == "enable"
            client.edit_site_replication(
                PeerInfo(
                    current["deploymentID"],
                    endpoint,
                    bandwidth,
                    bool(bandwidth),
                    name=site["name"],
                    sync_status=sync_enabled,
                )
            )
    predicted = dict(info)
    predicted["sites"] = list(existing.values()) + [
        {"name": s["name"], "endpoint": s["endpoint"]} for s in missing if s["name"] not in existing
    ]
    module.exit_json(changed=bool(missing or edits), site_replication=predicted)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "sites": {
                "type": "list",
                "elements": "dict",
                "default": [],
                "options": {
                    "name": {"type": "str", "required": True},
                    "endpoint": {"type": "str"},
                    "access_key": {"type": "str", "no_log": True},
                    "secret_key": {"type": "str", "no_log": True},
                    "sync": {"type": "bool"},
                    "bandwidth_limit": {"type": "int"},
                },
            },
            "remove_all": {"type": "bool", "default": False},
            "force": {"type": "bool", "default": False},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
            "retry_delay": {"type": "int", "default": 5},
            "retry_timeout": {"type": "int", "default": 600},
        },
        supports_check_mode=True,
    )
    try:
        run(module, admin_client(module, preserve_error_response=True))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
