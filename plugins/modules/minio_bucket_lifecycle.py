#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage lifecycle rules on an existing MinIO AIStor bucket."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_bucket_lifecycle
short_description: Reconcile lifecycle rules on an existing bucket
description:
  - Adds, replaces, or removes named lifecycle rules while preserving undeclared IDs.
extends_documentation_fragment: dagoldfish.minio.bucket_lifecycle
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
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: Predicts lifecycle rule changes.}
"""

EXAMPLES = r"""
- name: Expire old backup versions
  dagoldfish.minio.minio_bucket_lifecycle:
    auth: "{{ aistor_auth }}"
    name: backups
    lifecycle_rules:
      - id: expire-old-versions
        noncurrent_expiration_days: 30
"""

RETURN = r"""
bucket:
  description: Bucket identity.
  returned: always
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.bucket_lifecycle import (
    desired_rules,
    reconcile_lifecycle,
    rules_argument_spec,
)
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    auth_argument_spec,
    fail_from_exception,
    s3_client,
)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "name": {"type": "str", "required": True},
            "lifecycle_rules": rules_argument_spec(),
        },
        supports_check_mode=True,
    )
    name = module.params["name"]
    try:
        rules = desired_rules(module.params["lifecycle_rules"])
        changed = reconcile_lifecycle(s3_client(module), name, rules, True, module.check_mode)
    except Exception as error:
        fail_from_exception(module, error)
    module.exit_json(changed=changed, bucket={"name": name})


if __name__ == "__main__":
    main()
