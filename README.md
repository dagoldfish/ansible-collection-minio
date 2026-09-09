# `dagoldfish.minio`

Manage MinIO AIStor buckets, identities, LDAP providers, logging and audit
webhooks, policies, service operations, and site replication with Ansible and the official Python SDK. The
LDAP and webhook modules add narrowly scoped signed adapters for the dedicated
IDP Admin API and configuration activation headers not exposed by minio-py 7.2.20.

The collection is aimed at operators who want declarative, reviewable AIStor
administration. It includes eleven modules and the `aistor_admin` role, which
applies them in a safe dependency order.

## Install

Install the collection from Ansible Galaxy:

```sh
ansible-galaxy collection install dagoldfish.minio
```

To test the 0.3.0 development release, pin its exact version (Galaxy skips
prereleases during ordinary installation):

```sh
ansible-galaxy collection install 'dagoldfish.minio:==0.3.0-dev.2' --force
```

Or pin it in your collection requirements:

```yaml
collections:
  - name: dagoldfish.minio
    version: '0.3.0-dev.2'
```

This prerelease is intended for remote-site validation before the stable 0.3.0
release. Automatic configuration restarts remain opt-in; see the
[role documentation](roles/aistor_admin/README.md) for activation and recovery.

Alternatively, build and install the artifact locally:

```sh
ansible-galaxy collection build
ansible-galaxy collection install dagoldfish-minio-{version}.tar.gz
```

Requirements:

- Python 3.9 or newer
- ansible-core 2.14.18 or newer
- `minio` 7.2.20 or newer on the Python environment that executes the modules

Install the SDK on the controller for `connection: local`, or on each managed
host when the modules execute remotely:

```sh
python3 -m pip install 'minio>=7.2.20'
```

## First role run

The role deliberately does nothing until `aistor_admin_manage` is true. Keep
credentials in environment variables, Ansible Vault, or another secret lookup.

```yaml
---
- name: Reconcile AIStor administration
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    aistor_admin_manage: true
    aistor_admin_auth:
      endpoint: aistor.example.com:9000
      access_key: "{{ lookup('ansible.builtin.env', 'AISTOR_ADMIN_ACCESS_KEY') }}"
      secret_key: "{{ lookup('ansible.builtin.env', 'AISTOR_ADMIN_SECRET_KEY') }}"
      secure: true
      validate_certs: true
    aistor_admin_users:
      - access_key: backup
        secret_key: "{{ lookup('ansible.builtin.env', 'AISTOR_BACKUP_SECRET') }}"
        status: enabled
  roles:
    - role: dagoldfish.minio.aistor_admin
```

Preview supported operations with `--check` before applying them. LDAP policy
bindings are the exception: minio-py cannot read them back, so those operations
fail clearly in check mode. During normal runs, repeated LDAP attach and detach
operations are treated as successful no-ops when the server reports that the
requested binding state is already satisfied.

See [the role documentation](roles/aistor_admin/README.md) for every variable,
resource shape, reconciliation order, and destructive-operation safeguard. The
complete [example playbook](playbooks/manage_aistor.yml) demonstrates all role
resources while remaining disabled unless `AISTOR_MANAGE=true`.

## Included content

| Content | Purpose |
| --- | --- |
| `minio_bucket` | Create buckets and remove empty buckets |
| `minio_user` | Create, rotate, enable, disable, and remove local users |
| `minio_group` | Manage local groups, membership, and status |
| `minio_ldap_provider` | Reconcile default and named LDAP identity providers |
| `minio_policy` | Reconcile IAM policy documents |
| `minio_policy_binding` | Attach or detach built-in and LDAP policies |
| `minio_webhook` | Reconcile server logging and audit webhook targets |
| `minio_service` | Restart the AIStor service through the Admin API |
| `minio_service_account` | Manage service accounts and explicit secret rotation |
| `minio_site_replication` | Add, edit, or explicitly remove replication peers |
| `minio_site_replication_info` | Read topology and detailed status |
| `aistor_admin` | Reconcile the resources above in dependency order |

Use fully qualified names in playbooks and `ansible-doc`:

```sh
ansible-doc dagoldfish.minio.minio_user
```

The collection also provides the `group/dagoldfish.minio.minio` action group,
so shared module defaults can be defined once when appropriate.

## Behavior and limitations

- Bucket region and object-lock settings apply only at creation. Existing
  buckets are preserved, and deletion fails safely when a bucket is not empty.
- Existing unreadable user and service-account secrets are preserved. Set
  `update_secret: true` to rotate one intentionally.
- LDAP bind passwords are also unreadable. Set `update_bind_password: true` to
  rotate one intentionally. LDAP configuration changes require an AIStor
  restart; the role reports this by default and can restart automatically,
  waiting for the authenticated Admin API to become ready before continuing.
- Logging and audit webhooks preserve omitted settings and existing tokens. Set
  `update_auth_token: true` for explicit token rotation or clearing.
- Webhook changes use the server's dynamic-activation confirmation when available.
  Otherwise they request a restart. `aistor_admin_restart_on_config_change: true`
  enables one shared restart for LDAP and webhook changes, with a readiness wait.
  Restarts remain opt-in; the legacy LDAP flag still applies only when LDAP changes.
- AIStor environment variables override API-managed LDAP and webhook configuration.
- Groups add declared members by default. Set `purge_members: true` to remove
  undeclared members.
- Site replication never purges undeclared peers during `state: present`.
- MinIO site replication does not replicate service accounts owned by the root
  user. Service accounts created while these modules authenticate as root stay
  local to the site where they were created.
- Replication removal requires `state: absent` and `force: true`; complete
  topology removal additionally requires `remove_all: true` with an empty
  `sites` list.
- The collection has mocked unit coverage but has not yet been exercised against
  a live disposable AIStor deployment. Treat it as experimental and validate it
  outside production first.

## Develop and validate

See the [module utilities documentation](docs/module_utilities.md) for
shared client construction, response handling, LDAP and webhook adapters, and
guidance on using them in collection modules.

Run the complete local, non-live validation workflow from any checkout path:

```sh
./scripts/validate.sh
```

It creates a temporary collection layout, installs validation dependencies,
runs static/unit/sanity checks, builds and installs the artifact, renders all
module documentation, and exercises the example playbook safely.

## License

Copyright (c) 2026 Geoffrey Burger. This collection is licensed under
GPL-3.0-or-later. See [LICENSE](LICENSE) for the complete license text.

## Disclaimer

This project was developed with assistance from AI tools. All
AI-assisted contributions were reviewed by a human maintainer before inclusion.
