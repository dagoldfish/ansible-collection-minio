#!/usr/bin/python
# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manage MinIO AIStor LDAP identity providers."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: minio_ldap_provider
short_description: Manage a MinIO AIStor LDAP identity provider
description:
  - Creates, updates, enables, disables, and removes LDAP provider configurations.
  - Uses the official Python SDK generic server-configuration API.
  - Server environment variables override settings managed by this module.
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
  name: {description: Provider name. Use C(_) for the default provider., type: str, default: _}
  server_addr: {description: LDAP server address., type: str}
  lookup_bind_dn: {description: Distinguished name used for LDAP lookups., type: str}
  lookup_bind_password: {description: Password used for LDAP lookups., type: str}
  update_bind_password: {description: Explicitly rotate the unreadable bind password., type: bool, default: false}
  user_dn_search_base_dn: {description: Semicolon-separated user search base DNs., type: str}
  user_dn_search_filter: {description: LDAP user search filter., type: str}
  user_dn_attributes: {description: Comma-separated user DN attributes., type: str}
  group_search_base_dn: {description: Semicolon-separated group search base DNs., type: str}
  group_search_filter: {description: LDAP group search filter., type: str}
  srv_record_name: {description: LDAP DNS SRV record prefix., type: str}
  comment: {description: Provider comment., type: str}
  enabled: {description: Whether the provider is enabled., type: bool}
  tls_skip_verify: {description: Skip LDAP server certificate verification., type: bool}
  server_insecure: {description: Allow unencrypted LDAP connections., type: bool}
  server_starttls: {description: Use StartTLS for the LDAP connection., type: bool}
  state: {description: Desired provider existence., type: str, choices: [present, absent], default: present}
author: [Geoffrey Burger (@dagoldfish)]
requirements: [minio >= 7.2.20]
attributes:
  check_mode: {support: full, description: "Predicts provider creation, updates, and removal."}
"""

EXAMPLES = r"""
- name: Configure the default LDAP provider
  dagoldfish.minio.minio_ldap_provider:
    auth: "{{ aistor_auth }}"
    server_addr: ldap.example.com:636
    lookup_bind_dn: cn=minio,ou=services,dc=example,dc=com
    lookup_bind_password: "{{ vault_ldap_password }}"
    user_dn_search_base_dn: ou=users,dc=example,dc=com
    user_dn_search_filter: "(uid=%s)"

- name: Rotate a named provider bind password
  dagoldfish.minio.minio_ldap_provider:
    auth: "{{ aistor_auth }}"
    name: partners
    lookup_bind_password: "{{ vault_partner_ldap_password }}"
    update_bind_password: true
"""

RETURN = r"""
provider:
  description: Sanitized effective provider configuration known to the module.
  returned: always
  type: dict
restart_required:
  description: Whether this operation changed configuration that requires a service restart.
  returned: always
  type: bool
"""

import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    MinioAdminException,
    admin_client,
    auth_argument_spec,
    fail_from_exception,
)

STRING_FIELDS = (
    "server_addr",
    "lookup_bind_dn",
    "user_dn_search_base_dn",
    "user_dn_search_filter",
    "user_dn_attributes",
    "group_search_base_dn",
    "group_search_filter",
    "srv_record_name",
    "comment",
)
BOOL_FIELDS = ("enabled", "tls_skip_verify", "server_insecure", "server_starttls")
CONFIG_KEYS = STRING_FIELDS + (
    "lookup_bind_password",
    "enable",
    "tls_skip_verify",
    "server_insecure",
    "server_starttls",
)
REQUIRED_ON_CREATE = (
    "server_addr",
    "lookup_bind_dn",
    "lookup_bind_password",
    "user_dn_search_base_dn",
    "user_dn_search_filter",
)


def _config_key(name):
    return "identity_ldap" if name == "_" else f"identity_ldap:{name}"


def _strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_config(value):
    """Parse SDK config output using known key boundaries so spaces survive."""
    if not value:
        return {}
    text = str(value).strip()
    pattern = re.compile(r"(?:^|\s)(%s)=" % "|".join(re.escape(key) for key in CONFIG_KEYS))
    matches = list(pattern.finditer(text))
    parsed = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        parsed[match.group(1)] = _strip_quotes(text[match.end() : end])
    return parsed


def _is_missing(error):
    if not isinstance(error, MinioAdminException):
        return False
    message = (str(error) + " " + str(getattr(error, "_body", ""))).casefold()
    return "doesn't exist" in message or "does not exist" in message or "not found" in message


def _read_current(client, key, is_default):
    try:
        current = _parse_config(client.config_get(key))
    except Exception as error:
        if _is_missing(error):
            return False, {}
        raise
    # The default target always exists in the server configuration with empty defaults.
    exists = bool(current.get("server_addr")) if is_default else True
    return exists, current


def _public_config(name, current):
    provider = {"name": name}
    for field in STRING_FIELDS:
        if field in current:
            provider[field] = current[field]
    for field in BOOL_FIELDS:
        key = "enable" if field == "enabled" else field
        if key in current and current[key] != "":
            provider[field] = current[key].casefold() in ("on", "true", "yes", "1")
    return provider


def run(module, client):
    params = module.params
    name = params["name"]
    key = _config_key(name)
    exists, current = _read_current(client, key, name == "_")

    if params["state"] == "absent":
        if not exists:
            module.exit_json(changed=False, provider={"name": name}, restart_required=False)
        if not module.check_mode:
            client.config_reset(key)
        module.exit_json(changed=True, provider={"name": name}, restart_required=True)

    if not exists:
        missing = [field for field in REQUIRED_ON_CREATE if params.get(field) in (None, "")]
        if missing:
            module.fail_json(msg="The following fields are required when creating an LDAP provider: " + ", ".join(missing))
    if params["update_bind_password"] and not params.get("lookup_bind_password"):
        module.fail_json(msg="lookup_bind_password is required when update_bind_password is true")

    changes = {}
    for field in STRING_FIELDS:
        desired = params.get(field)
        if desired is not None and current.get(field) != desired:
            changes[field] = desired
    for field in BOOL_FIELDS:
        desired = params.get(field)
        config_field = "enable" if field == "enabled" else field
        normalized = "on" if desired else "off"
        if desired is not None and current.get(config_field, "").casefold() != normalized:
            changes[config_field] = normalized

    password = params.get("lookup_bind_password")
    if password and (not exists or params["update_bind_password"]):
        changes["lookup_bind_password"] = password

    changed = bool(changes) or not exists
    if changed and not module.check_mode:
        client.config_set(key, changes)

    effective = dict(current)
    effective.update({field: value for field, value in changes.items() if field != "lookup_bind_password"})
    module.exit_json(changed=changed, provider=_public_config(name, effective), restart_required=changed)


def main():
    argument_spec = {
        "auth": auth_argument_spec(),
        "name": {"type": "str", "default": "_"},
        "lookup_bind_password": {"type": "str", "no_log": True},
        "update_bind_password": {"type": "bool", "default": False},
        "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
    }
    argument_spec.update({field: {"type": "str"} for field in STRING_FIELDS})
    argument_spec.update({field: {"type": "bool"} for field in BOOL_FIELDS})
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    try:
        run(module, admin_client(module))
    except Exception as error:
        fail_from_exception(module, error)


if __name__ == "__main__":
    main()
