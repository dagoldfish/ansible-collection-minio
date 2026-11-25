# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest
from ansible_collections.dagoldfish.minio.plugins.module_utils.bucket_lifecycle import (
    desired_rules,
    reconcile_lifecycle,
)
from minio.error import S3Error

BUCKET = "backups"
EXTERNAL_RULE = "<Rule><ID>external</ID><Filter/><Transition><VendorField>value</VendorField></Transition></Rule>"


def test_merge_preserves_external_fields_and_converges():
    client = Mock()
    client._execute.return_value.data = (
        '<LifecycleConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        + EXTERNAL_RULE + "</LifecycleConfiguration>"
    ).encode()
    rules = desired_rules([dict(id="old", noncurrent_expiration_days=30, newer_noncurrent_versions=3)])
    assert reconcile_lifecycle(client, BUCKET, rules, True, True)
    assert client._execute.call_count == 1
    assert reconcile_lifecycle(client, BUCKET, rules, True, False)
    body = client._execute.call_args.kwargs["body"]
    assert ET.fromstring(body).findtext(".//{*}VendorField") == "value"
    assert ET.fromstring(body).findtext(".//{*}NewerNoncurrentVersions") == "3"
    client._execute.return_value.data = body
    assert not reconcile_lifecycle(client, BUCKET, rules, True, False)
    assert client._execute.call_args.args[0] == "GET"

    disable = desired_rules([dict(id="old", enabled=False, expiration_days=3, prefix="logs/")])
    assert reconcile_lifecycle(client, BUCKET, disable, True, False)
    document = ET.fromstring(client._execute.call_args.kwargs["body"])
    assert document.findtext(".//{*}Status") == "Disabled"
    assert document.findtext(".//{*}Prefix") == "logs/"
    assert document.find(".//{*}NoncurrentVersionExpiration") is None


def test_remove_last_rule_and_absent_config():
    client = Mock()
    client._execute.return_value.data = ("<LifecycleConfiguration>" + EXTERNAL_RULE + "</LifecycleConfiguration>").encode()
    rules = desired_rules([dict(id="external", state="absent")])
    assert reconcile_lifecycle(client, BUCKET, rules, True, True)
    client.delete_bucket_lifecycle.assert_not_called()
    assert reconcile_lifecycle(client, BUCKET, rules, True, False)
    client.delete_bucket_lifecycle.assert_called_once_with(BUCKET)
    client._execute.side_effect = S3Error(None, "NoSuchLifecycleConfiguration", "", "", "", "")
    assert not reconcile_lifecycle(client, BUCKET, rules, True, False)
    client._execute.side_effect = S3Error(None, "AccessDenied", "", "", "", "")
    with pytest.raises(S3Error, match="AccessDenied"):
        reconcile_lifecycle(client, BUCKET, rules, True, False)


def test_missing_bucket_preview_and_empty_rules_do_not_read():
    client = Mock()
    rules = desired_rules([dict(id="move", transition_tier="ARCHIVE", transition_days=0)])
    assert reconcile_lifecycle(client, BUCKET, rules, False, True)
    assert not reconcile_lifecycle(client, BUCKET, {}, True, False)
    assert not client.mock_calls


@pytest.mark.parametrize("rules", [
    [dict(id="a")], [dict(id="", state="absent")],
    [dict(id="a", state="absent")] * 2,
    [dict(id="a", expiration_days=0)],
    [dict(id="a", expiration_days=3, expired_object_delete_marker=True)],
    [dict(id="a", newer_noncurrent_versions=1)], [dict(id="a", transition_days=2)],
])
def test_invalid_rules(rules):
    with pytest.raises(ValueError):
        desired_rules(rules)
