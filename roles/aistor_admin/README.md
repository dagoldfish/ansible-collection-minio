# AIStor administration role

`dagoldfish.minio.aistor_admin` reconciles MinIO AIStor administration
resources through the modules in this collection. It does not install AIStor,
MinIO, Python, or the MinIO SDK.

## Contents

- [Minimal example](#minimal-example)
- [Variables](#variables)
- [Authentication](#authentication)
- [Resources](#resources)
- [Coordinated activation and restarts](#coordinated-activation-and-restarts)
- [Ordering and idempotency](#ordering-and-idempotency)
- [Disposable webhook integration test](#disposable-webhook-integration-test)

## Minimal example

```yaml
- name: Manage AIStor from the controller
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    aistor_admin_manage: true
    aistor_admin_auth:
      endpoint: aistor.example.com:9000
      access_key: "{{ vault_aistor_admin_access_key }}"
      secret_key: "{{ vault_aistor_admin_secret_key }}"
    aistor_admin_policies:
      - name: backups-read
        policy:
          Version: "2012-10-17"
          Statement: []
  roles:
    - role: dagoldfish.minio.aistor_admin
```

### Requirements

Install the following where the modules execute. With `connection: local`,
that is the controller.

| Dependency | Minimum version |
| --- | --- |
| Python | 3.9 |
| ansible-core | 2.14.18 |
| minio-py | 7.2.20 |

## Variables

All variables are namespaced with `aistor_admin_` and are optional. The role is
safe by default because `aistor_admin_manage` is `false`.

### Management

| Variable | Default | Meaning |
| --- | --- | --- |
| `aistor_admin_manage` | `false` | Enable API reads and reconciliation |
| `aistor_admin_auth` | `{}` | Shared administrator connection dictionary |

### Resource lists and topology

| Variable | Default | Meaning |
| --- | --- | --- |
| [`aistor_admin_buckets`](#buckets) | `[]` | Buckets to create or remove |
| [`aistor_admin_policies`](#policies) | `[]` | IAM policies to reconcile |
| [`aistor_admin_users`](#users) | `[]` | Local users to reconcile |
| [`aistor_admin_groups`](#groups) | `[]` | Local groups and memberships to reconcile |
| [`aistor_admin_service_accounts`](#service-accounts) | `[]` | Service accounts to reconcile |
| [`aistor_admin_ldap_providers`](#ldap-providers) | `[]` | Default or named LDAP providers to reconcile |
| [`aistor_admin_logger_webhooks`](#logging-and-audit-webhooks) | `[]` | Server logging webhook targets |
| [`aistor_admin_audit_webhooks`](#logging-and-audit-webhooks) | `[]` | Audit webhook targets |
| [`aistor_admin_policy_bindings`](#policy-bindings) | `[]` | Built-in or LDAP bindings to reconcile |
| [`aistor_admin_site_replication`](#site-replication) | `{}` | Optional replication operation |

### Restarts and readiness

| Variable | Default | Meaning |
| --- | --- | --- |
| `aistor_admin_restart_on_config_change` | `false` | Restart once for pending LDAP/webhook activation |
| `aistor_admin_restart_on_ldap_change` | `false` | Restart AIStor after LDAP changes |
| `aistor_admin_restart_readiness_delay` | `5` | Seconds between post-restart readiness attempts |
| `aistor_admin_restart_readiness_timeout` | `180` | Maximum seconds to wait for AIStor readiness |

### Site replication retries

| Variable | Default | Meaning |
| --- | --- | --- |
| `aistor_admin_site_replication_retry_delay` | `5` | Seconds between replication retry attempts |
| `aistor_admin_site_replication_retry_timeout` | `600` | Maximum seconds for replication retries |

## Authentication

Set connection details in `aistor_admin_auth`:

| Field | Default | Meaning |
| --- | --- | --- |
| `endpoint` | Required | Server hostname and optional port |
| `access_key` | Required | Administrator access key |
| `secret_key` | Required | Administrator secret key |
| `secure` | `true` | Use HTTPS |
| `validate_certs` | `true` | Verify the server certificate |
| `region` | `""` | Optional region |

The endpoint may include `http://` or `https://`; the transport itself is
controlled by `secure`.

Never place credentials in inventory committed to source control. Use Ansible
Vault, environment lookups, or a dedicated secret provider.

## Resources

### Buckets

Each `aistor_admin_buckets` item accepts `name`, `region`, `object_lock`, and
`state` (`present` by default). Region and object-lock settings apply only when
creating a bucket and are not changed on an existing bucket. `state: absent`
removes only an empty bucket; the SDK returns an error rather than deleting
objects from a non-empty bucket.

### Policies

Each `aistor_admin_policies` item accepts `name`, one of `policy` or
`policy_file`, and `state` (`present` by default). Policy dictionaries are
compared semantically, so key order and ordering of set-like IAM arrays such as
statements, actions, resources, and condition values do not cause changes.

### Users

Each `aistor_admin_users` item accepts `access_key`, `secret_key`, `status`,
`update_secret` (`false`), and `state` (`present`). A secret is required for
creation and explicit rotation. Existing secrets are otherwise preserved.

### Groups

Each `aistor_admin_groups` item accepts `name`, `members`, `purge_members`
(`false`), `status`, and `state` (`present`). Omitting `members` leaves existing
membership untouched; enabling `purge_members` removes undeclared members.

### Service accounts

Each `aistor_admin_service_accounts` item accepts `access_key`, `secret_key`,
`name`, `description`, `policy`, `expiration`, `status`, `update_secret`
(`false`), and `state` (`present`). Explicit secrets must contain 8 through 40
characters. Secret handling otherwise matches local users.

MinIO site replication does not replicate service accounts owned by the root
user. When the role authenticates as root, the service accounts it creates
remain local to the originating site; the collection does not work around this
server rule.

### LDAP providers

Each item in `aistor_admin_ldap_providers` accepts:

| Setting | Fields |
| --- | --- |
| Provider | `name` (`_` for the default), `enabled`, `state`, `comment` |
| Server | `server_addr`, `srv_record_name` |
| Bind credentials | `lookup_bind_dn`, `lookup_bind_password`, `update_bind_password` |
| User search | `user_dn_search_base_dn`, `user_dn_search_filter`, `user_dn_attributes` |
| Group search | `group_search_base_dn`, `group_search_filter` |
| TLS | `tls_skip_verify`, `server_insecure`, `server_starttls` |

Creation requires the server address, lookup-bind credentials, user search base,
and user search filter. Omitted optional fields remain unchanged.

#### Password rotation

AIStor redacts the lookup-bind password when reading configuration. Set
`update_bind_password: true` to rotate an existing password intentionally.

#### Activation

LDAP changes require a service restart. By default the role reports the pending
restart and defers LDAP policy bindings; set
`aistor_admin_restart_on_ldap_change: true` to restart once through the SDK and
wait for the signed Admin info endpoint to recover before continuing
reconciliation. Connection errors, HTTP 5xx responses, and temporary HTTP 403
responses (including those returned by nginx) are retried. Tune the delay and
overall deadline with `aistor_admin_restart_readiness_delay` and
`aistor_admin_restart_readiness_timeout`. Server environment variables override
configuration stored through the Admin API.

### Logging and audit webhooks

Each item in `aistor_admin_logger_webhooks` or `aistor_admin_audit_webhooks`
accepts:

| Setting | Fields |
| --- | --- |
| Target | `name` (`_` for the default), `endpoint`, `enabled`, `state` (`present` by default), `comment` |
| Authentication | `auth_token`, `update_auth_token` |
| TLS | `client_cert`, `client_key`, `tls_skip_verification` |
| Connection | `proxy`, `http_timeout`, `http_encoding` |
| Queue | `queue_dir`, `queue_size` |
| Batching | `batch_size`, `batch_max_size` |
| Retries | `max_retry`, `retry_interval` |

The role supplies `kind` automatically. Use `dagoldfish.minio.minio_webhook`
directly with `kind: logger` or `kind: audit`.

#### Example

```yaml
aistor_admin_logger_webhooks:
  - name: operations
    endpoint: https://logs.example.com/minio
    auth_token: "Bearer {{ vault_logger_token }}"
aistor_admin_audit_webhooks:
  - name: security
    endpoint: https://audit.example.com/minio
    queue_dir: /var/lib/minio/audit-queue
    batch_size: 10
    retry_interval: 3s
    http_timeout: 5s
aistor_admin_restart_on_config_change: true
```

#### Creation, updates, and removal

Creation requires an HTTP(S) endpoint and enables the target unless explicitly
disabled. Updates preserve omitted fields, including disabled status. Empty
lists do nothing; undeclared targets are never purged. `state: absent` resets
only the selected target. An unconfigured default target (disabled with no
endpoint) counts as absent even though MinIO returns its defaults on read.

#### Tokens and URL credentials

Tokens are treated as unreadable. They are set on creation and otherwise
preserved unless `update_auth_token: true`. With that flag, `auth_token: ""`
clears authentication. Explicit rotations always report a change; remove the
flag after rotating. Tokens are excluded from module results and redacted from
API diagnostics. Supply the complete header value, including `Bearer` if needed.
Proxy input is also sensitive. Returned endpoint/proxy URLs mask embedded
credentials, including credentials read from the server when the corresponding
parameter was omitted. Encoded and decoded URL credentials are registered with
Ansible's secret filtering and the collection's shared diagnostic redactor, so
module output stays protected when task-level `no_log` is disabled for debugging.
Raw URLs are still used for reconciliation and requests.

#### Server paths and delivery

Queue and certificate paths refer to MinIO servers, not the Ansible controller.
Provision directories, certificates, and permissions separately on each server.
A persistent queue retains undelivered events while the receiver is unavailable;
this role does not create it or guarantee delivery.

#### Supported settings

Optional fields vary by server version; changed settings are checked against
server configuration help before writing, so unsupported keys cannot be silently ignored. Omitted
fields retain server defaults rather than imposing a version-specific baseline.
Environment variables take precedence over stored API configuration and cannot
be removed by this role. Module results describe stored configuration, not
receiver health.

#### Names and values

Names allow letters, digits, underscores, and hyphens. Values
containing newlines, NULs, or embedded webhook `key=` markers are rejected because
MinIO's configuration parser cannot safely represent them. Literal quotes and
backslashes are preserved without shell escaping. Assignments such as
`team=ops` inside comments remain literal values and do not trigger repeat writes.

### Policy bindings

Each `aistor_admin_policy_bindings` item accepts `policies` and exactly one of
`user` or `group`. `identity_provider` is `builtin` by default and may be
`ldap`; `state` is `present` by default. LDAP bindings cannot be predicted in
check mode because minio-py provides no LDAP association read-back API. During
normal runs, LDAP attach and detach operations are idempotent when the server
reports that the requested binding state is already satisfied.

### Site replication

`aistor_admin_site_replication` accepts `sites`, `state`, `force`, `remove_all`,
`retry_delay`, and `retry_timeout`. A site accepts `name`, `endpoint`,
`access_key`, `secret_key`, `sync`, and a non-negative `bandwidth_limit`.
Transient transport, HTTP 429, and HTTP 5xx failures during topology reads and
site additions are retried for up to 600 seconds by default. After an ambiguous
failed add response, the module reads the topology before submitting the add
again, so a successful request with a lost response remains idempotent. Set
`aistor_admin_site_replication_retry_delay` and
`aistor_admin_site_replication_retry_timeout` to change the role-wide defaults.

| Operation | Required inputs |
| --- | --- |
| Add a site | Site endpoint and credentials |
| Remove named sites | `state: absent`, `force: true`, and at least one site name |
| Remove the complete topology | `state: absent`, `force: true`, `remove_all: true`, and `sites: []` |

## Coordinated activation and restarts

After reconciling LDAP and both webhook lists, the role gathers targets whose
modules report `restart_required`. The webhook adapter inspects
`x-minio-config-applied: true` on successful writes and resets, following the
[MinIO Admin client's activation contract](https://github.com/minio/madmin-go/blob/main/config-kv-commands.go).
A confirmed dynamic change does not request a restart; an absent or unrecognized
header conservatively does. LDAP changes still require a restart.

### Automatic restarts

`aistor_admin_restart_on_config_change: true` authorizes one shared Admin API
restart followed by the existing readiness wait. The legacy
`aistor_admin_restart_on_ldap_change` authorizes that restart only when LDAP
changed; it does not authorize webhook-only restarts. A restart activates all
stored configuration, including other changes already staged on the server.
Restart/readiness failures stop reconciliation before policy bindings.

### Deferred activation and check mode

With automatic restarts disabled, the role reports affected target names and
defers LDAP bindings when LDAP changed. In check mode it predicts possible
webhook restart requirements without writing configuration or restarting, and
defers bindings dependent on changed LDAP even if automatic restarts are enabled.

### Recovery

Pending reports cover this invocation only. Stored configuration matching the
playbook does not prove that an earlier deferred or failed restart completed.
To recover, explicitly run `dagoldfish.minio.minio_service` with
`wait_for_ready: true`, then rerun the role. This is a service-wide restart,
not rolling orchestration, and the Admin readiness check is not a webhook
end-to-end delivery check.

## Ordering and idempotency

The role applies resources in dependency order so later resources can reference
earlier ones:

1. Buckets
2. Policies
3. Users
4. Groups
5. Service accounts
6. LDAP providers
7. Logging and audit webhooks
8. Shared configuration activation or pending-restart report
9. Policy bindings
10. Site replication

Empty resource lists are no-ops, and undeclared resources are not purged.

Run with `--check` to preview all supported changes. The role intentionally
fails on LDAP binding operations in check mode instead of claiming an
idempotency guarantee the SDK cannot provide.

See the [complete example playbook](../../playbooks/manage_aistor.yml) for an
environment-backed configuration.

## Disposable webhook integration test

The `aistor_webhooks` integration target sends real events and may restart
MinIO. Run it only against a disposable deployment. The receiver must be
reachable from MinIO and accept log requests without authentication.

### Environment

| Variable | Required value or default |
| --- | --- |
| `AISTOR_IT_WEBHOOKS` | `true` to enable the test |
| `AISTOR_IT_ENDPOINT` | Required AIStor endpoint |
| `AISTOR_IT_ACCESS_KEY` | Required administrator access key |
| `AISTOR_IT_SECRET_KEY` | Required administrator secret key |
| `AISTOR_IT_WEBHOOK_ENDPOINT` | Required webhook receiver endpoint |
| `AISTOR_IT_SECURE` | `true` |
| `AISTOR_IT_VALIDATE_CERTS` | `true` |

### Run

```sh
ansible-test integration aistor_webhooks --allow-destructive --allow-unsupported
```

The target exercises both kinds with isolated names, repeats configuration,
previews disabling, and removes its targets in an `always` block.
