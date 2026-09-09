#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage MinIO logger and audit webhook targets."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_webhook
short_description: Manage MinIO AIStor logging and audit webhooks
description:
  - Creates, updates, disables, and removes individual webhook targets through the signed Admin API.
  - Omitted settings and undeclared targets are preserved. New targets are enabled by default.
  - Server environment variables override stored configuration. Certificate and queue paths are on the server.
  - Reports whether a restart is needed; never restarts the service itself.
  - Optional settings depend on the server version. Unsupported settings are rejected using server configuration help before writing.
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
  kind: {description: Log stream to publish., type: str, required: true, choices: [logger, audit]}
  name: {description: Target name. Use C(_) for the default target., type: str, default: _}
  state: {description: Desired target existence., type: str, choices: [present, absent], default: present}
  enabled: {description: Enable delivery. Defaults to true on creation; otherwise preserved., type: bool}
  endpoint: {description: HTTP or HTTPS webhook URL. Required on creation., type: str}
  auth_token: {description: Complete Authorization header value. Treated as unreadable after creation., type: str}
  update_auth_token:
    description:
      - Explicitly replace an existing token. Requires O(auth_token); an empty string clears it.
      - Every explicit rotation reports a change because tokens may be redacted on read.
    type: bool
    default: false
  client_cert: {description: Server-local mTLS certificate path., type: str}
  client_key: {description: Server-local mTLS private key path., type: str}
  proxy: {description: Proxy URL used by MinIO to reach the webhook., type: str}
  queue_dir: {description: Existing writable server-local directory for persistent undelivered events., type: str}
  queue_size: {description: Maximum queued events. Must be positive., type: int}
  batch_size: {description: Events per batch. Must be positive., type: int}
  batch_max_size: {description: Maximum batch payload bytes. Must be at least 32000., type: int}
  max_retry: {description: Delivery retries. Zero retries indefinitely., type: int}
  retry_interval: {description: Retry duration such as C(3s). Must be positive and at most one minute., type: str}
  http_timeout: {description: Request duration such as C(5s). Must be at least one second., type: str}
  http_encoding: {description: Event encoding., type: str, choices: [json, cbor]}
  tls_skip_verification: {description: Disable webhook TLS certificate verification., type: bool}
  comment: {description: Target description., type: str}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: Predicts changes and conservatively reports possible restart requirements.}
"""

EXAMPLES = r"""
- name: Configure audit delivery
  dagoldfish.minio.minio_webhook:
    auth: "{{ aistor_auth }}"
    kind: audit
    name: security
    endpoint: https://audit.example.com/minio
    auth_token: "Bearer {{ vault_audit_token }}"
    queue_dir: /var/lib/minio/audit-queue
  register: audit_config

- name: Rotate a logging token
  dagoldfish.minio.minio_webhook:
    auth: "{{ aistor_auth }}"
    kind: logger
    name: operations
    auth_token: "Bearer {{ vault_logging_token }}"
    update_auth_token: true

- name: Remove one audit target
  dagoldfish.minio.minio_webhook:
    auth: "{{ aistor_auth }}"
    kind: audit
    name: security
    state: absent
"""

RETURN = r"""
webhook:
  description: Target identity and non-secret stored configuration known to the module; not a delivery health check.
  returned: always
  type: dict
restart_required:
  description:
    - Whether this operation needs a restart, or may need one in check mode.
    - False for unchanged targets or when the server confirms dynamic activation.
    - Does not detect pending restarts from earlier invocations.
  returned: always
  type: bool
"""

import re
from decimal import Decimal
from urllib.parse import urlsplit

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    admin_client,
    auth_argument_spec,
    fail_from_exception,
)
from ansible_collections.dagoldfish.minio.plugins.module_utils.webhook_config import (
    config_text,
    read_config,
    target_key,
    validate_config_fields,
    write_config,
)

STRING_FIELDS = (
    "endpoint", "client_cert", "client_key", "proxy", "queue_dir", "retry_interval",
    "http_timeout", "http_encoding", "comment",
)
INT_FIELDS = ("queue_size", "batch_size", "batch_max_size", "max_retry")
BOOL_FIELDS = ("enabled", "tls_skip_verification")
_DURATION_PART = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(ns|us|µs|μs|ms|s|m|h)")
_UNITS = {"ns": 1, "us": 1000, "µs": 1000, "μs": 1000, "ms": 1000000, "s": 1000000000,
          "m": 60000000000, "h": 3600000000000}


def _duration(value):
    parts = list(_DURATION_PART.finditer(value))
    if not parts or "".join(part.group() for part in parts) != value:
        raise ValueError("Durations must use MinIO units, for example 5s or 1m")
    return sum(Decimal(part.group(1)) * _UNITS[part.group(2)] for part in parts)


def _bool(value):
    if value.lower() in ("on", "true", "yes", "1"):
        return True
    if value.lower() in ("off", "false", "no", "0"):
        return False
    raise ValueError("Invalid boolean in webhook configuration response")


def _validate(params):
    if params["update_auth_token"] and params.get("auth_token") is None:
        raise ValueError("auth_token is required when update_auth_token is true (use an empty string to clear it)")
    endpoint = params.get("endpoint")
    if endpoint is not None:
        url = urlsplit(endpoint)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ValueError("endpoint must be a non-empty HTTP or HTTPS URL")
    for field in INT_FIELDS:
        value = params.get(field)
        minimum = 0 if field == "max_retry" else 32000 if field == "batch_max_size" else 1
        if value is not None and value < minimum:
            raise ValueError("%s must be at least %s" % (field, minimum))
    for field in ("http_timeout", "retry_interval"):
        value = params.get(field)
        if value is not None:
            ns = _duration(value)
            if (field == "http_timeout" and ns < _UNITS["s"]) or (
                field == "retry_interval" and not 0 < ns <= _UNITS["m"]
            ):
                raise ValueError("http_timeout must be at least 1s; retry_interval must be positive and at most 1m")
    # Validate syntax before making even a read request, including in check mode.
    supplied = {field: params[field] for field in STRING_FIELDS + INT_FIELDS + ("auth_token",)
                if params.get(field) is not None}
    config_text(supplied)


def _public(kind, name, current):
    result = {"kind": kind, "name": name}
    for field in STRING_FIELDS:
        if field in current:
            result[field] = current[field]
    for field in INT_FIELDS:
        if current.get(field) not in (None, ""):
            result[field] = int(current[field])
    for field in BOOL_FIELDS:
        key = "enable" if field == "enabled" else field
        if current.get(key) not in (None, ""):
            result[field] = _bool(current[key])
    return result


def run(module, client):
    params = module.params
    kind, name = params["kind"], params["name"]
    key = target_key(kind, name)
    _validate(params)
    current = read_config(client, key)
    exists = current is not None
    current = dict(current or {})
    # A reset default target is still returned by MinIO, with no endpoint.
    if name == "_" and not current.get("endpoint") and not _bool(current.get("enable", "off")):
        exists = False
    current.pop("auth_token", None)
    if exists:
        current.setdefault("enable", "on")
        current.setdefault("tls_skip_verification", "off")

    if params["state"] == "absent":
        restart = exists
        if exists and not module.check_mode:
            restart = write_config(client, key)
        module.exit_json(changed=exists, webhook={"kind": kind, "name": name}, restart_required=restart)

    if not exists and not params.get("endpoint"):
        module.fail_json(msg="endpoint is required when creating a webhook target")
    changes = {}
    for field in STRING_FIELDS + INT_FIELDS:
        desired = params.get(field)
        if desired is None:
            continue
        value = str(desired)
        previous = current.get(field, "")
        equal = value == previous
        if previous and field in ("retry_interval", "http_timeout"):
            equal = _duration(value) == _duration(previous)
        elif previous and field in INT_FIELDS:
            equal = int(value) == int(previous)
        if not equal:
            changes[field] = value
    for field in BOOL_FIELDS:
        desired = params.get(field)
        wire = "enable" if field == "enabled" else field
        if desired is not None and (wire not in current or _bool(current[wire]) != desired):
            changes[wire] = ("on" if desired else "off") if field == "enabled" else str(desired).lower()
    token = params.get("auth_token")
    if token is not None and (not exists or params["update_auth_token"]):
        changes["auth_token"] = token
    changed = bool(changes) or not exists
    restart = changed
    if changed:
        # MinIO config set implicitly enables targets unless enable is supplied.
        changes.setdefault("enable", current.get("enable", "on") if exists else "on")
        validate_config_fields(client, key, changes)
        if not module.check_mode:
            restart = write_config(client, key, changes)
    current.update({k: v for k, v in changes.items() if k != "auth_token"})
    module.exit_json(changed=changed, webhook=_public(kind, name, current), restart_required=restart)


def main():
    spec = {
        "auth": auth_argument_spec(),
        "kind": {"type": "str", "required": True, "choices": ["logger", "audit"]},
        "name": {"type": "str", "default": "_"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "auth_token": {"type": "str", "no_log": True},
        "update_auth_token": {"type": "bool", "default": False},
    }
    spec.update({field: {"type": "str"} for field in STRING_FIELDS})
    spec.update({field: {"type": "int"} for field in INT_FIELDS})
    spec.update({field: {"type": "bool"} for field in BOOL_FIELDS})
    spec["client_key"]["no_log"] = False  # Server-side path, not private key contents.
    spec["http_encoding"]["choices"] = ["json", "cbor"]
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True)
    try:
        run(module, admin_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
