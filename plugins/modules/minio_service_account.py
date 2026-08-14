#!/usr/bin/python
"""Manage MinIO service accounts."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: minio_service_account
short_description: Manage a MinIO AIStor service account
description: Creates, updates, rotates, disables, and removes service accounts.
options:
  auth:
    description: Administrator connection settings.
    type: dict
    required: true
    suboptions:
      endpoint: {description: API endpoint., type: str, required: true}
      access_key: {description: Administrator access key., type: str, required: true}
      secret_key: {description: Administrator secret key., type: str, required: true}
      secure: {description: Use HTTPS., type: bool, default: true}
      validate_certs: {description: Validate TLS certificates., type: bool, default: true}
      region: {description: Signing region., type: str, default: ""}
  access_key: {type: str, required: true, description: Service-account access key.}
  secret_key: {type: str, description: Secret for creation or rotation.}
  name: {type: str, description: Display name.}
  description: {type: str, description: Description.}
  policy: {type: dict, description: Embedded policy document.}
  expiration: {type: str, description: ISO-8601 expiration.}
  status: {type: str, choices: [enabled, disabled], description: Account status.}
  update_secret: {type: bool, default: false, description: Explicitly rotate the unreadable secret.}
  state: {description: Desired account existence., type: str, choices: [present, absent], default: present}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: "Predicts service-account creation, updates, rotation, and removal."}
"""
EXAMPLES = r"""
- captain.minio.minio_service_account:
    auth: "{{ aistor_auth }}"
    access_key: backup-service
    secret_key: "{{ backup_secret }}"
    status: enabled
"""
RETURN = r"""
service_account: {description: Non-secret service-account information., returned: always, type: dict}
"""
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.captain.minio.plugins.module_utils.minio_admin import (
    admin_client,
    auth_argument_spec,
    canonical_json,
    fail_from_exception,
    is_not_found,
    parse_json,
)


def run(module, client):
    key = module.params["access_key"]
    try:
        current = parse_json(client.get_service_account(key), {}) or {}
    except Exception as error:
        if not is_not_found(error):
            raise
        current = {}
    exists = bool(current)
    if module.params["state"] == "absent":
        if exists and not module.check_mode:
            client.delete_service_account(key)
        module.exit_json(changed=exists, service_account={})
    if not exists:
        if not module.params["secret_key"]:
            module.fail_json(msg="secret_key is required when creating a service account")
        if not module.check_mode:
            result = client.add_service_account(
                access_key=key,
                secret_key=module.params["secret_key"],
                name=module.params["name"],
                description=module.params["description"],
                policy=module.params["policy"],
                expiration=module.params["expiration"],
                status=module.params["status"],
            )
            current = parse_json(result, {}) or {}
        module.exit_json(changed=True, service_account=current or {"accessKey": key})
    updates = {}
    for param, field in (
        ("name", "name"),
        ("description", "description"),
        ("expiration", "expiration"),
        ("status", "status"),
    ):
        if module.params[param] is not None and module.params[param] != current.get(field):
            updates[param] = module.params[param]
    if module.params["policy"] is not None and canonical_json(module.params["policy"]) != canonical_json(
        current.get("policy", {})
    ):
        updates["policy"] = module.params["policy"]
    if module.params["update_secret"]:
        if not module.params["secret_key"]:
            module.fail_json(msg="secret_key is required when update_secret is true")
        updates["secret_key"] = module.params["secret_key"]
    if updates and not module.check_mode:
        client.update_service_account(access_key=key, **updates)
    result = dict(current)
    result.update({k: v for k, v in updates.items() if k != "secret_key"})
    module.exit_json(changed=bool(updates), service_account=result)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "access_key": {"type": "str", "required": True, "no_log": False},
            "secret_key": {"type": "str", "no_log": True},
            "name": {"type": "str"},
            "description": {"type": "str"},
            "policy": {"type": "dict"},
            "expiration": {"type": "str"},
            "status": {"type": "str", "choices": ["enabled", "disabled"]},
            "update_secret": {"type": "bool", "default": False},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        supports_check_mode=True,
    )
    try:
        run(module, admin_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
