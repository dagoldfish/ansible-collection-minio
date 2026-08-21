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
  state: {description: Desired bucket existence., type: str, choices: [present, absent], default: present}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: "Predicts bucket creation and removal."}
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

- name: Remove an empty bucket
  dagoldfish.minio.minio_bucket:
    auth: "{{ aistor_auth }}"
    name: retired
    state: absent
"""

RETURN = r"""
bucket:
  description: Bucket identity and creation settings requested by the module.
  returned: always
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    auth_argument_spec,
    fail_from_exception,
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

    if exists:
        module.exit_json(changed=False, bucket=bucket)
    if not module.check_mode:
        client.make_bucket(name, location=module.params["region"], object_lock=module.params["object_lock"])
    module.exit_json(changed=True, bucket=bucket)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "name": {"type": "str", "required": True},
            "region": {"type": "str"},
            "object_lock": {"type": "bool", "default": False},
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
