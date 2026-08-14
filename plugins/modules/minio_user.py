#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage MinIO local users."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_user
short_description: Manage a local MinIO AIStor user
description:
  - Creates, removes, enables, disables, and explicitly rotates local users.
  - Existing secrets are never compared or changed unless O(update_secret=true).
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
  access_key:
    description: Access key identifying the managed user.
    type: str
    required: true
  secret_key:
    description: Secret required for creation and explicit rotation.
    type: str
  status:
    description: Desired status. Existing status is preserved when omitted.
    choices: [enabled, disabled]
    type: str
  update_secret:
    description: Rotate the unreadable secret even when the user already exists.
    type: bool
    default: false
  state:
    description: Desired user existence.
    choices: [present, absent]
    default: present
    type: str
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: "Predicts user creation, status changes, rotation, and removal."}
"""

EXAMPLES = r"""
- name: Ensure an enabled AIStor user exists
  dagoldfish.minio.minio_user:
    auth: "{{ aistor_auth }}"
    access_key: backup
    secret_key: "{{ backup_secret }}"
    status: enabled
"""

RETURN = r"""
user:
  description: Current non-secret user information.
  returned: always
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    admin_client,
    auth_argument_spec,
    fail_from_exception,
    parse_json,
)


def run(module, client):
    access_key = module.params["access_key"]
    state = module.params["state"]
    users = parse_json(client.user_list(), {}) or {}
    exists = access_key in users
    current = parse_json(client.user_info(access_key), {}) if exists else {}

    if state == "absent":
        if not exists:
            module.exit_json(changed=False, user={})
        if not module.check_mode:
            client.user_remove(access_key)
        module.exit_json(changed=True, user={})

    secret_key = module.params["secret_key"]
    if not exists and not secret_key:
        module.fail_json(msg="secret_key is required when creating a user")

    changed = False
    original_status = current.get(
        "status", users.get(access_key, {}).get("status") if isinstance(users.get(access_key), dict) else None
    )
    if not exists or module.params["update_secret"]:
        if module.params["update_secret"] and not secret_key:
            module.fail_json(msg="secret_key is required when update_secret is true")
        changed = True
        if not module.check_mode:
            client.user_add(access_key, secret_key)
            current = parse_json(client.user_info(access_key), {})

    desired_status = module.params["status"] or (original_status if exists else "enabled")
    current_status = current.get("status", original_status or "enabled")
    if desired_status != current_status:
        changed = True
        if not module.check_mode:
            if desired_status == "enabled":
                client.user_enable(access_key)
            else:
                client.user_disable(access_key)
            current = parse_json(client.user_info(access_key), {})

    predicted = dict(current)
    predicted.update({"accessKey": access_key, "status": desired_status})
    module.exit_json(changed=changed, user=predicted)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "access_key": {"type": "str", "required": True, "no_log": False},
            "secret_key": {"type": "str", "required": False, "no_log": True},
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
