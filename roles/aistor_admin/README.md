# AIStor administration role

`dagoldfish.minio.aistor_admin` reconciles MinIO AIStor administration
resources through the modules in this collection. It does not install AIStor,
MinIO, Python, or the MinIO SDK.

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

Python 3.9+, ansible-core 2.14.18+, and minio-py 7.2.20+ must be available where
the modules execute. With `connection: local`, that is the controller.

## Variables

All variables are namespaced with `aistor_admin_` and are optional. The role is
safe by default because `aistor_admin_manage` is `false`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `aistor_admin_manage` | `false` | Enable API reads and reconciliation |
| `aistor_admin_auth` | `{}` | Shared administrator connection dictionary |
| `aistor_admin_buckets` | `[]` | Buckets to create or remove |
| `aistor_admin_policies` | `[]` | IAM policies to reconcile |
| `aistor_admin_users` | `[]` | Local users to reconcile |
| `aistor_admin_groups` | `[]` | Local groups and memberships to reconcile |
| `aistor_admin_service_accounts` | `[]` | Service accounts to reconcile |
| `aistor_admin_ldap_providers` | `[]` | Default or named LDAP providers to reconcile |
| `aistor_admin_restart_on_ldap_change` | `false` | Restart AIStor after LDAP changes |
| `aistor_admin_policy_bindings` | `[]` | Built-in or LDAP bindings to reconcile |
| `aistor_admin_site_replication` | `{}` | Optional replication operation |

### Authentication

`aistor_admin_auth` accepts `endpoint`, `access_key`, and `secret_key` as
required fields. Optional fields are `secure` (`true`), `validate_certs`
(`true`), and `region` (`""`). The endpoint may include `http://` or `https://`;
the transport itself is controlled by `secure`.

Never place credentials in inventory committed to source control. Use Ansible
Vault, environment lookups, or a dedicated secret provider.

### Buckets

Each `aistor_admin_buckets` item accepts `name`, `region`, `object_lock`, and
`state` (`present` by default). Region and object-lock settings apply only when
creating a bucket and are not changed on an existing bucket. `state: absent`
removes only an empty bucket; the SDK returns an error rather than deleting
objects from a non-empty bucket.

### Policies

Each `aistor_admin_policies` item accepts `name`, one of `policy` or
`policy_file`, and `state` (`present` by default). Policy dictionaries are
compared as canonical JSON, so key order does not cause changes.

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
(`false`), and `state` (`present`). Secret handling matches local users.

### LDAP providers

Each `aistor_admin_ldap_providers` item accepts `name` (`_` for the default),
`server_addr`, `lookup_bind_dn`, `lookup_bind_password`, user and group search
bases and filters, `user_dn_attributes`, `srv_record_name`, `comment`,
`enabled`, `tls_skip_verify`, `server_insecure`, `server_starttls`, and `state`.
Creation requires the server address, lookup-bind credentials, user search base,
and user search filter. Omitted optional fields remain unchanged.

AIStor redacts the lookup-bind password when reading configuration. Set
`update_bind_password: true` to rotate an existing password intentionally.
LDAP changes require a service restart. By default the role reports the pending
restart and defers LDAP policy bindings; set
`aistor_admin_restart_on_ldap_change: true` to restart once through the SDK and
continue reconciliation. Server environment variables override configuration
stored through the Admin API.

### Policy bindings

Each `aistor_admin_policy_bindings` item accepts `policies` and exactly one of
`user` or `group`. `identity_provider` is `builtin` by default and may be
`ldap`; `state` is `present` by default. LDAP bindings cannot be predicted in
check mode because minio-py provides no LDAP association read-back API. During
normal runs, LDAP attach and detach operations are idempotent when the server
reports that the requested binding state is already satisfied.

### Site replication

`aistor_admin_site_replication` accepts `sites`, `state`, `force`, and
`remove_all`. A site accepts `name`, `endpoint`, `access_key`, `secret_key`,
`sync`, and a non-negative `bandwidth_limit`.

Adding a site requires its endpoint and credentials. Removing named sites
requires `state: absent`, `force: true`, and at least one site name. Removing
the complete topology requires `state: absent`, `force: true`,
`remove_all: true`, and `sites: []`.

## Ordering and idempotency

The role reconciles buckets, policies, users, groups, service accounts, LDAP
providers, policy bindings, and finally site replication. This permits later
resources to reference earlier ones. LDAP changes are applied or reported
through a handler before LDAP bindings. Empty resource lists are no-ops, and
undeclared resources are not purged.

Run with `--check` to preview all supported changes. The role intentionally
fails on LDAP binding operations in check mode instead of claiming an
idempotency guarantee the SDK cannot provide.

See `playbooks/manage_aistor.yml` for a complete environment-backed example.
