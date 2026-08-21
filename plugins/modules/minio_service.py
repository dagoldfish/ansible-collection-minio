#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage the MinIO AIStor service through the Admin API."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_service
short_description: Manage the MinIO AIStor service
description: Performs service-wide administrative actions through the official Python SDK.
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
  action: {description: Service operation to perform., type: str, choices: [restart], default: restart}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: Reports the restart without executing it.}
"""

EXAMPLES = r"""
- name: Restart AIStor
  dagoldfish.minio.minio_service:
    auth: "{{ aistor_auth }}"
    action: restart
"""

RETURN = r"""
response: {description: SDK service response., returned: when executed, type: str}
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    admin_client,
    auth_argument_spec,
    fail_from_exception,
)


def run(module, client):
    response = ""
    if not module.check_mode:
        response = client.service_restart()
    module.exit_json(changed=True, action="restart", response=response)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "action": {"type": "str", "choices": ["restart"], "default": "restart"},
        },
        supports_check_mode=True,
    )
    try:
        run(module, admin_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
