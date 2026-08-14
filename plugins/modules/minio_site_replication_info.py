#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read MinIO site-replication information."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_site_replication_info
short_description: Read MinIO AIStor site-replication information
description: Returns topology and optional detailed status without changing AIStor.
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
  include_status: {type: bool, default: false, description: Also request detailed replication status.}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: Performs only read operations in all modes.}
"""
EXAMPLES = r"""
- dagoldfish.minio.minio_site_replication_info:
    auth: "{{ aistor_auth }}"
  register: replication
"""
RETURN = r"""
site_replication: {description: Site-replication topology., returned: always, type: dict}
status: {description: Detailed status when requested., returned: when requested, type: dict}
"""
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    SiteReplicationStatusOptions,
    admin_client,
    auth_argument_spec,
    fail_from_exception,
    parse_json,
)


def run(module, client):
    result = {"changed": False, "site_replication": parse_json(client.get_site_replication_info(), {}) or {}}
    if module.params["include_status"]:
        options = SiteReplicationStatusOptions(buckets=True, policies=True, users=True, groups=True, metrics=True)
        result["status"] = parse_json(client.get_site_replication_status(options), {}) or {}
    module.exit_json(**result)


def main():
    module = AnsibleModule(
        argument_spec={"auth": auth_argument_spec(), "include_status": {"type": "bool", "default": False}},
        supports_check_mode=True,
    )
    try:
        run(module, admin_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
