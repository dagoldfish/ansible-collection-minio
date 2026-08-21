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
  - Uses the dedicated, signed MinIO identity-provider Admin API without invoking C(mc).
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

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    MinioAdminException,
    admin_client,
    auth_argument_spec,
    fail_from_exception,
    ldap_idp_delete,
    ldap_idp_get,
    ldap_idp_set,
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
REQUIRED_ON_CREATE = (
    "server_addr",
    "lookup_bind_dn",
    "lookup_bind_password",
    "user_dn_search_base_dn",
    "user_dn_search_filter",
)


def _is_missing(error):
    if not isinstance(error, MinioAdminException):
        return False
    message = (str(error) + " " + str(getattr(error, "_body", ""))).casefold()
    return "doesn't exist" in message or "does not exist" in message or "not found" in message


def _read_current(client, name):
    try:
        response = ldap_idp_get(client, name)
    except Exception as error:
        if _is_missing(error):
            return False, {}
        raise
    current = {
        item["key"]: item.get("value", "")
        for item in response.get("info", [])
        if item.get("key") and item.get("key") != "lookup_bind_password"
    }
    exists = bool(response)
    # The Admin API omits enable=on from its serialized configuration output.
    if exists and "enable" not in current:
        current["enable"] = "on"
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
    exists, current = _read_current(client, name)

    if params["state"] == "absent":
        if not exists:
            module.exit_json(changed=False, provider={"name": name}, restart_required=False)
        if not module.check_mode:
            ldap_idp_delete(client, name)
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
        ldap_idp_set(client, name, changes, update=exists)

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
