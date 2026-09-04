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
  wait_for_ready:
    description: Poll the signed Admin info endpoint after restarting until AIStor is ready.
    type: bool
    default: false
  readiness_delay: {description: Seconds between readiness attempts., type: int, default: 5}
  readiness_timeout: {description: Maximum seconds to wait for readiness., type: int, default: 180}
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
    wait_for_ready: true
"""

RETURN = r"""
response: {description: SDK service response., returned: when executed, type: str}
ready: {description: Whether the post-restart Admin readiness check succeeded., returned: always, type: bool}
"""

import time

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    MinioAdminException,
    admin_client,
    auth_argument_spec,
    fail_from_exception,
    is_transport_error,
)


def _status_code(error):
    """Extract an HTTP status code from an Admin API exception."""
    value = getattr(error, "_code", None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_retryable_readiness_error(error):
    """Return whether a readiness failure can occur during a restart."""
    if isinstance(error, MinioAdminException):
        status = _status_code(error)
        return status == 403 or (status is not None and 500 <= status <= 599)
    return is_transport_error(error)


def _wait_until_ready(client, delay, timeout, sleep=time.sleep, monotonic=time.monotonic):
    """Poll the authenticated Admin info endpoint until it responds."""
    deadline = monotonic() + timeout
    while True:
        try:
            client.info()
            return
        except Exception as error:
            if not _is_retryable_readiness_error(error) or monotonic() >= deadline:
                raise
            sleep(min(delay, max(0, deadline - monotonic())))


def run(module, client):
    if module.params["readiness_delay"] < 0:
        module.fail_json(msg="readiness_delay must be greater than or equal to zero")
    if module.params["readiness_timeout"] < 1:
        module.fail_json(msg="readiness_timeout must be greater than zero")
    response = ""
    ready = False
    if not module.check_mode:
        response = client.service_restart()
        if module.params["wait_for_ready"]:
            _wait_until_ready(
                client,
                module.params["readiness_delay"],
                module.params["readiness_timeout"],
            )
            ready = True
    module.exit_json(changed=True, action="restart", response=response, ready=ready)


def main():
    module = AnsibleModule(
        argument_spec={
            "auth": auth_argument_spec(),
            "action": {"type": "str", "choices": ["restart"], "default": "restart"},
            "wait_for_ready": {"type": "bool", "default": False},
            "readiness_delay": {"type": "int", "default": 5},
            "readiness_timeout": {"type": "int", "default": 180},
        },
        supports_check_mode=True,
    )
    try:
        run(module, admin_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
