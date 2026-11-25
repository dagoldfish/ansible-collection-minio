#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage MinIO AIStor buckets."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_bucket
short_description: Manage a MinIO AIStor bucket
description:
  - Creates buckets and removes empty buckets through the official Python SDK.
  - Region and object-lock settings apply only when a bucket is created.
options:
  auth:
    description: MinIO connection settings.
    type: dict
    required: true
    suboptions:
      endpoint: {description: API endpoint., type: str, required: true}
      access_key: {description: Access key., type: str, required: true}
      secret_key: {description: Secret key., type: str, required: true}
      secure: {description: Use HTTPS., type: bool, default: true}
      validate_certs: {description: Validate TLS certificates., type: bool, default: true}
      region: {description: Signing region override., type: str, default: ""}
  name: {description: Bucket name., type: str, required: true}
  region: {description: Region used when creating the bucket., type: str}
  object_lock: {description: Enable object locking when creating the bucket., type: bool, default: false}
  versioning: {description: Set bucket versioning. Omit to preserve its current state., type: str, choices: [enabled, suspended]}
  quota_bytes:
    description:
      - Hard storage quota in bytes for a new or existing bucket when O(state=present).
      - The default of C(0) means unlimited and clears any existing quota.
    type: int
    default: 0
  state: {description: Desired bucket existence., type: str, choices: [present, absent], default: present}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: "Predicts bucket creation, removal, quota, and versioning changes."}
"""

EXAMPLES = r"""
- name: Create a bucket
  dagoldfish.minio.minio_bucket:
    auth: "{{ aistor_auth }}"
    name: backups

- name: Create an object-locked bucket in a region
  dagoldfish.minio.minio_bucket:
    auth: "{{ aistor_auth }}"
    name: compliance-archive
    region: eu-west-1
    object_lock: true

- name: Set a 10 GiB storage quota
  dagoldfish.minio.minio_bucket:
    auth: "{{ aistor_auth }}"
    name: backups
    quota_bytes: 10737418240

- name: Remove an empty bucket
  dagoldfish.minio.minio_bucket:
    auth: "{{ aistor_auth }}"
    name: retired
    state: absent
"""

RETURN = r"""
bucket:
  description: Bucket identity and requested settings, including C(quota_bytes) when managed.
  returned: always
  type: dict
"""

from dataclasses import replace

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    admin_client,
    auth_argument_spec,
    fail_from_exception,
    parse_json,
    s3_client,
)


def run(module, client):
    name = module.params["name"]
    exists = client.bucket_exists(name)
    bucket = {
        "name": name,
        "region": module.params["region"],
        "object_lock": module.params["object_lock"],
    }

    if module.params["state"] == "absent":
        if not exists:
            module.exit_json(changed=False, bucket={"name": name})
        if not module.check_mode:
            client.remove_bucket(name)
        module.exit_json(changed=True, bucket={"name": name})

    quota = module.params.get("quota_bytes", 0)
    if not 0 <= quota < 2**64:
        module.fail_json(msg="quota_bytes must be between 0 and 18446744073709551615 bytes.")

    bucket["quota_bytes"] = quota
    versioning = module.params.get("versioning")
    if versioning:
        bucket["versioning"] = versioning
    if not exists and bucket["object_lock"] and versioning == "suspended":
        module.fail_json(msg="A new object-locked bucket requires enabled versioning.")
    changed = False
    try:
        if not exists:
            if not module.check_mode:
                client.make_bucket(name, location=bucket["region"], object_lock=bucket["object_lock"])
            changed = True
        if exists or quota:
            admin = admin_client(module)
            current = (parse_json(admin.bucket_quota_get(name)) or {}) if exists else {}
            # MinIO uses the legacy quota field when size is zero.
            if (current.get("size") or current.get("quota", 0)) != quota:
                if not module.check_mode:
                    admin.bucket_quota_set(name, quota)
                changed = True
        if versioning:
            from minio.versioningconfig import VersioningConfig

            current_version = client.get_bucket_versioning(name) if exists else VersioningConfig(
                status="Enabled" if bucket["object_lock"] else None
            )
            if current_version.status != versioning.title():
                if not module.check_mode:
                    client.set_bucket_versioning(name, replace(current_version, status=versioning.title()))
                changed = True
    except Exception as error:
        fail_from_exception(module, error, changed=changed and not module.check_mode)
    module.exit_json(changed=changed, bucket=bucket)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "name": {"type": "str", "required": True},
            "region": {"type": "str"},
            "object_lock": {"type": "bool", "default": False},
            "versioning": {"type": "str", "choices": ["enabled", "suspended"]},
            "quota_bytes": {"type": "int", "default": 0},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        supports_check_mode=True,
    )
    try:
        run(module, s3_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
