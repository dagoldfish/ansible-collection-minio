#!/usr/bin/python
"""Manage built-in and LDAP policy associations."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: minio_policy_binding
short_description: Manage MinIO AIStor policy bindings
description: Attaches or detaches policies for built-in or LDAP users and groups.
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
  policies: {type: list, elements: str, required: true, description: Policies to attach or detach.}
  user: {type: str, description: Target user or LDAP distinguished name.}
  group: {type: str, description: Target group or LDAP distinguished name.}
  identity_provider: {type: str, choices: [builtin, ldap], default: builtin, description: Identity source.}
  state: {description: Whether bindings are attached or detached., type: str, choices: [present, absent], default: present}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode:
    support: partial
    description: Predicts built-in bindings but rejects LDAP bindings because the SDK lacks LDAP read-back.
    details: LDAP binding operations fail clearly in check mode.
"""
EXAMPLES = r"""
- captain.minio.minio_policy_binding:
    auth: "{{ aistor_auth }}"
    policies: [readonly]
    user: backup
"""
RETURN = r"""
policies: {description: Policies targeted by this operation., returned: always, type: list, elements: str}
"""
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.captain.minio.plugins.module_utils.minio_admin import (
    admin_client,
    auth_argument_spec,
    fail_from_exception,
    parse_json,
)


def run(module, client):
    policies = sorted(set(module.params["policies"]))
    target = {"user": module.params["user"]} if module.params["user"] else {"group": module.params["group"]}
    ldap = module.params["identity_provider"] == "ldap"
    if ldap and module.check_mode:
        module.fail_json(
            msg="LDAP policy bindings do not support check mode because minio-py has no LDAP policy-entity read API"
        )
    if ldap:
        method = client.attach_policy_ldap if module.params["state"] == "present" else client.detach_policy_ldap
        response = parse_json(method(policies, **target), {}) or {}
        key = "policiesAttached" if module.params["state"] == "present" else "policiesDetached"
        module.exit_json(changed=bool(response.get(key)), policies=policies)
    entities = (
        parse_json(
            client.get_policy_entities(
                [target.get("user")] if target.get("user") else [],
                [target.get("group")] if target.get("group") else [],
                [],
            ),
            {},
        )
        or {}
    )
    mapping_key = "userMappings" if target.get("user") else "groupMappings"
    name_key = "user" if target.get("user") else "group"
    current = set()
    for mapping in entities.get(mapping_key, []):
        if mapping.get(name_key) == (target.get("user") or target.get("group")):
            current = set(mapping.get("policies", []))
    wanted = set(policies)
    delta = wanted - current if module.params["state"] == "present" else wanted & current
    if delta and not module.check_mode:
        method = client.attach_policy if module.params["state"] == "present" else client.detach_policy
        method(sorted(delta), **target)
    module.exit_json(changed=bool(delta), policies=policies)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "policies": {"type": "list", "elements": "str", "required": True},
            "user": {"type": "str"},
            "group": {"type": "str"},
            "identity_provider": {"type": "str", "choices": ["builtin", "ldap"], "default": "builtin"},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        required_one_of=[("user", "group")],
        mutually_exclusive=[("user", "group")],
        supports_check_mode=True,
    )
    try:
        run(module, admin_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
