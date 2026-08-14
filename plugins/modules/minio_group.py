#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage MinIO local groups and membership."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_group
short_description: Manage a local MinIO AIStor group
description: Creates groups, reconciles membership, changes status, and removes groups.
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
  name: {description: Group name., type: str, required: true}
  members:
    description: Members that must belong to the group. Membership is untouched when omitted.
    type: list
    elements: str
  purge_members:
    description: Remove current members not declared in O(members).
    type: bool
    default: false
  status: {description: Desired group status., type: str, choices: [enabled, disabled]}
  state: {description: Desired group existence., type: str, choices: [present, absent], default: present}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: "Predicts group, membership, status, and removal changes."}
"""

EXAMPLES = r"""
- name: Reconcile the backup group
  dagoldfish.minio.minio_group:
    auth: "{{ aistor_auth }}"
    name: backups
    members: [backup]
    purge_members: true
"""

RETURN = r"""
group:
  description: Predicted or current group information.
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
    name = module.params["name"]
    state = module.params["state"]
    groups = parse_json(client.group_list(), []) or []
    if isinstance(groups, dict):
        groups = list(groups)
    exists = name in groups
    current = parse_json(client.group_info(name), {}) if exists else {}

    if state == "absent":
        if not exists:
            module.exit_json(changed=False, group={})
        if not module.check_mode:
            client.group_remove(name)
        module.exit_json(changed=True, group={})

    changed = False
    desired_members = module.params["members"]
    current_members = set(current.get("members", []))
    if not exists:
        changed = True
        initial_members = desired_members or []
        if not module.check_mode:
            client.group_add(name, initial_members)
            current = parse_json(client.group_info(name), {})
            current_members = set(current.get("members", initial_members))
        else:
            current_members = set(initial_members)
    elif desired_members is not None:
        desired = set(desired_members)
        additions = sorted(desired - current_members)
        removals = sorted(current_members - desired) if module.params["purge_members"] else []
        if additions:
            changed = True
            if not module.check_mode:
                client.group_add(name, additions)
        if removals:
            changed = True
            if not module.check_mode:
                client.group_remove(name, members=removals)
        current_members = (current_members | set(additions)) - set(removals)

    desired_status = module.params["status"] or (current.get("status") if exists else "enabled")
    if desired_status and desired_status != current.get("status", "enabled"):
        changed = True
        if not module.check_mode:
            (client.group_enable if desired_status == "enabled" else client.group_disable)(name)

    result = dict(current)
    result.update({"name": name, "members": sorted(current_members), "status": desired_status})
    module.exit_json(changed=changed, group=result)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "name": {"type": "str", "required": True},
            "members": {"type": "list", "elements": "str"},
            "purge_members": {"type": "bool", "default": False},
            "status": {"type": "str", "choices": ["enabled", "disabled"]},
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
