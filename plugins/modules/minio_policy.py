#!/usr/bin/python
"""Manage MinIO IAM policies."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: minio_policy
short_description: Manage a MinIO AIStor IAM policy
description: Creates, canonically compares, updates, and removes IAM policies.
options:
  auth:
    description: MinIO administrator connection settings.
    type: dict
    required: true
    suboptions:
      endpoint: {description: API endpoint., type: str, required: true}
      access_key: {description: Administrator access key., type: str, required: true}
      secret_key: {description: Administrator secret key., type: str, required: true}
      secure: {description: Use HTTPS., type: bool, default: true}
      validate_certs: {description: Validate TLS certificates., type: bool, default: true}
      region: {description: Signing region., type: str, default: ""}
  name: {description: Policy name., type: str, required: true}
  policy: {description: IAM policy document., type: dict}
  policy_file: {description: Path to a JSON policy on the module execution host., type: path}
  state: {description: Desired policy existence., type: str, choices: [present, absent], default: present}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: "Predicts policy creation, document updates, and removal."}
"""

EXAMPLES = r"""
- name: Configure a read policy
  captain.minio.minio_policy:
    auth: "{{ aistor_auth }}"
    name: backups-read
    policy:
      Version: "2012-10-17"
      Statement: []
"""

RETURN = r"""
policy:
  description: Desired policy document, or an empty dictionary when absent.
  returned: always
  type: dict
"""

import json
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.captain.minio.plugins.module_utils.minio_admin import (
    admin_client,
    auth_argument_spec,
    canonical_json,
    fail_from_exception,
    parse_json,
)


def run(module, client):
    name = module.params["name"]
    policies = parse_json(client.policy_list(), {}) or {}
    exists = name in policies
    if module.params["state"] == "absent":
        if not exists:
            module.exit_json(changed=False, policy={})
        if not module.check_mode:
            client.policy_remove(name)
        module.exit_json(changed=True, policy={})

    desired = module.params["policy"]
    if module.params["policy_file"]:
        try:
            desired = json.loads(Path(module.params["policy_file"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            module.fail_json(msg=f"Unable to read policy_file: {error}")
    if desired is None:
        module.fail_json(msg="policy or policy_file is required when state is present")

    current = parse_json(client.policy_info(name), {}) if exists else {}
    changed = not exists or canonical_json(current) != canonical_json(desired)
    if changed and not module.check_mode:
        client.policy_add(name, policy=desired)
    module.exit_json(changed=changed, policy=desired)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "name": {"type": "str", "required": True},
            "policy": {"type": "dict"},
            "policy_file": {"type": "path"},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        mutually_exclusive=[("policy", "policy_file")],
        supports_check_mode=True,
    )
    try:
        run(module, admin_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
