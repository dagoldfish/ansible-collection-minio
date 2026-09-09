# Module utilities

`dagoldfish.minio` shares client construction, response handling, and targeted
configuration adapters between its modules. These Python helpers support module
development; use the [collection modules](../README.md#included-content) or
the [AIStor administration role](../roles/aistor_admin/README.md) in playbooks.

## Included utilities

| File | Purpose |
| --- | --- |
| [minio_admin.py](../plugins/module_utils/minio_admin.py) | Construct Admin and S3 clients, normalize responses, manage LDAP providers, and report redacted failures |
| [webhook_config.py](../plugins/module_utils/webhook_config.py) | Read, validate, write, and reset individual logging and audit webhook targets |

Python 3.9+, ansible-core 2.14.18+, and minio-py 7.2.20+ must be available where
the modules execute. Both client factories report a missing SDK through
`module.fail_json`.

## Minimal example

Import helpers through the collection namespace. This read-only module pattern
uses the shared authentication specification and failure reporting:

```python
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    admin_client,
    auth_argument_spec,
    fail_from_exception,
    parse_json,
)


def main():
    module = AnsibleModule(
        argument_spec={"auth": auth_argument_spec()},
        supports_check_mode=True,
    )
    try:
        client = admin_client(module)
        info = parse_json(client.get_site_replication_info(), {}) or {}
    except Exception as error:
        fail_from_exception(module, error)
    module.exit_json(changed=False, site_replication=info)


if __name__ == "__main__":
    main()
```

Client construction does not reconcile resources. Each calling module owns
input validation, reads, comparisons, check-mode behavior, writes, and result
filtering. See [minio_site_replication_info](../plugins/modules/minio_site_replication_info.py)
for the complete module and its argument documentation.

## Authentication and clients

`auth_argument_spec()` returns a fresh specification for a required nested
`auth` dictionary.

| Field | Default | Meaning |
| --- | --- | --- |
| `endpoint` | Required | Server hostname and optional port |
| `access_key` | Required | Authentication access key; marked `no_log` |
| `secret_key` | Required | Authentication secret key; marked `no_log` |
| `secure` | `true` | Use HTTPS |
| `validate_certs` | `true` | Verify the server certificate |
| `region` | `""` | Optional region |

`admin_client(module)` returns a `MinioAdmin` client with static credentials.
`s3_client(module)` returns a `Minio` client for bucket operations. Both remove
a leading `http://` or `https://` and trailing slashes from the endpoint;
`secure` controls the transport independently of that prefix. The S3 factory
converts an empty region to `None`.

The shared HTTP pool uses five-minute connect and read timeouts, a pool size of
10, and a retry budget of five with a 0.2 backoff factor. Its status retry list
is 500, 502, 503, and 504; the final HTTP response remains available to the SDK
for error reporting. Certificate verification uses `SSL_CERT_FILE` when set,
otherwise the CA bundle supplied by `certifi`.

`admin_client(module, preserve_error_response=True)` disables pool retries so
the calling module can own retry and recovery decisions. Site replication uses
this mode to read topology after an ambiguous add failure before resubmitting
the operation. Both modes preserve the final HTTP error response.

The wrappers supply options supported by the official
[MinioAdmin constructor](https://github.com/minio/minio-py/blob/master/_autodocs/api-reference/minioadmin.md).
Their defaults and normalization above are defined by this collection.

## Responses and policy comparison

| Helper | Behavior |
| --- | --- |
| `parse_json(value, default=None)` | Return the default for `None` or an empty string, pass dictionaries and lists through, and decode other values as JSON |
| `canonical_json(value)` | Return stable JSON for semantic IAM policy comparison without modifying the input |
| `is_transport_error(error)` | Recognize `HTTPError`, `OSError`, and `TimeoutError` for callers that implement retries |
| `is_not_found(error)` | Recognize a `MinioAdminException` whose status is the string `"404"` |

`canonical_json` accepts a policy dictionary or JSON string. It sorts object
keys and set-like arrays named `Statement`, `Action`, `NotAction`, `Resource`,
and `NotResource`, plus arrays under `Condition`. Other arrays retain their
order. Use the canonical form for comparison and the original policy for writes.

The utility also exposes the SDK's `PeerInfo`, `PeerSite`, and
`SiteReplicationStatusOptions` for replication modules.

## LDAP providers

| Helper | Purpose |
| --- | --- |
| `ldap_idp_get(client, name="_")` | Read a provider; `_` selects the default |
| `ldap_idp_set(client, name, config, update)` | Create with `update=False` or update with `update=True` |
| `ldap_idp_delete(client, name)` | Delete the selected provider |

These helpers prefer `get_idp_config`, `add_or_update_idp_config`, and
`delete_idp_config` when the client provides them. Otherwise they use the SDK's
private signed transport for `idp-config/ldap/{name}`, encrypting configuration
writes and decrypting reads. The adapter preloads response bodies and closes
and releases responses after use.

The calling module decides whether a provider exists, preserves unreadable
passwords, and reports restart requirements. The helpers do not restart AIStor
or wait for readiness. See [minio_ldap_provider](../plugins/modules/minio_ldap_provider.py)
for reconciliation and explicit password rotation.

## Logging and audit webhook configuration

| Helper | Purpose |
| --- | --- |
| `target_key(kind, name)` | Build an explicit `logger_webhook:name` or `audit_webhook:name` selector |
| `config_text(config)` | Serialize supported wire fields into MinIO key/value configuration |
| `parse_config(text, key)` | Parse exactly one target into a dictionary, or return `None` when it is absent |
| `read_config(client, key)` | Read and decrypt one target, returning `None` for recognized missing-target responses |
| `validate_config_fields(client, key, config)` | Check supplied fields against server configuration help before writing |
| `write_config(client, key, config=None)` | Write a configuration dictionary, or reset one target when `config` is `None`; return whether a restart is required |

Use `target_key` even for the default name `_` so a reset cannot select the
whole subsystem. Names allow letters, digits, underscores, and hyphens. The
parser accepts default-target aliases, ignores comment lines, and rejects
duplicate targets, duplicate fields, and malformed configuration. A nonempty
read response that omits the requested target is an error.

`WIRE_FIELDS` defines the supported configuration keys. Values use MinIO's
key/value syntax, with literal quotes and backslashes rather than shell
escaping. Newlines, carriage returns, NULs, and embedded webhook `key=` markers
are rejected. Unrelated assignments such as `team=ops` remain part of a value.
Server help validation also rejects unsupported fields and embedded markers
for keys advertised by that server; `enable` is accepted as an implicit key.

Writes and resets use encrypted bodies through the SDK's signed transport.
`write_config` returns `False` only when the response confirms
`x-minio-config-applied: true`; an absent or unrecognized value returns `True`.
It does not validate server support automatically or perform a restart. The
calling module must validate changed fields before writing and handle the
returned restart requirement. See [minio_webhook](../plugins/modules/minio_webhook.py)
for token preservation, check mode, and result filtering.

## Failures and sensitive values

Pass caught exceptions to `fail_from_exception(module, error)` for consistent
`module.fail_json` output. Recognized SDK errors include an `api_error`
dictionary with the exception `type` and available status, code, message,
resource, request ID, or content type. Unknown exceptions produce a bounded,
redacted message without `api_error`.

Admin error bodies are inspected only up to 16,384 characters, and only scalar
code and message fields are retained from JSON. Invalid, unrecognized, or
oversized bodies are omitted with length metadata. Diagnostic string fields
are limited to 4,096 characters before an omission suffix is appended.

The failure helper redacts known authentication keys, resource secrets, LDAP
bind passwords, webhook tokens, proxies, replication credentials, and values
registered in `module.no_log_values`. URL user information is masked too.

Use `register_url_credentials(module, *urls)` for credentials in supplied or
server-returned URLs before reporting results or errors. It registers encoded
and decoded values with Ansible's secret filtering. `url_sensitive_values(value)`
returns those values, while `redact_url_credentials(value)` returns a display
URL with user information replaced by `***`. Keep original URLs for requests
and comparison, and filter result dictionaries in the calling module.

## Develop and validate

The adapters depend on private SDK transport and crypto interfaces. When
changing them or upgrading the SDK, check request methods, encrypted bodies,
response cleanup, missing-target handling, activation headers, and diagnostics.
LDAP and webhook configuration use separate serializers with different rules.

Shared client and error coverage lives in
[test_module_utils.py](../tests/unit/test_module_utils.py); webhook transport
and configuration coverage lives in [test_webhook.py](../tests/unit/test_webhook.py).
Run the collection's complete local, non-live validation from the repository root:

```sh
./scripts/validate.sh
```

These tests use mocks and local HTTP fixtures. They do not establish
compatibility with a live AIStor deployment; see the
[role documentation](../roles/aistor_admin/README.md#disposable-webhook-integration-test)
for the opt-in disposable webhook integration target.
