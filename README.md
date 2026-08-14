# `dagoldfish.minio`

Manage MinIO AIStor identities, policies, and site replication with Ansible and
the official Python SDK. The collection does not install or invoke `mc`.

The collection is aimed at operators who want declarative, reviewable AIStor
administration. It includes seven modules and the `aistor_admin` role, which
applies them in a safe dependency order.

## Install

After the first Galaxy release:

```sh
ansible-galaxy collection install dagoldfish.minio
```

Until then, build and install the artifact locally:

```sh
ansible-galaxy collection build
ansible-galaxy collection install dagoldfish-minio-0.1.0.tar.gz
```

Requirements:

- Python 3.9 or newer
- ansible-core 2.16 or newer
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
fail clearly in check mode.

See [the role documentation](roles/aistor_admin/README.md) for every variable,
resource shape, reconciliation order, and destructive-operation safeguard. The
complete [example playbook](playbooks/manage_aistor.yml) demonstrates all role
resources while remaining disabled unless `AISTOR_MANAGE=true`.

## Included content

| Content | Purpose |
| --- | --- |
| `minio_user` | Create, rotate, enable, disable, and remove local users |
| `minio_group` | Manage local groups, membership, and status |
| `minio_policy` | Reconcile IAM policy documents |
| `minio_policy_binding` | Attach or detach built-in and LDAP policies |
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

- Existing unreadable user and service-account secrets are preserved. Set
  `update_secret: true` to rotate one intentionally.
- Groups add declared members by default. Set `purge_members: true` to remove
  undeclared members.
- Site replication never purges undeclared peers during `state: present`.
- Replication removal requires `state: absent` and `force: true`; complete
  topology removal additionally requires `remove_all: true` with an empty
  `sites` list.
- The modules have mocked unit coverage, but release `0.1.0` remains blocked
  until the integration suite passes against a disposable AIStor deployment.

## Develop and validate

Run the complete local, non-live validation workflow from any checkout path:

```sh
./scripts/validate.sh
```

It creates a temporary collection layout, installs validation dependencies,
runs static/unit/sanity checks, builds and installs the artifact, renders all
module documentation, and exercises the example playbook safely. See
[CONTRIBUTING.md](CONTRIBUTING.md) for integration-test instructions.

## Release status

Version `0.1.0` is the intended first Galaxy release. Publishing is manual:
review the Git history and built artifact for secrets, confirm live integration
results, then upload `dagoldfish-minio-0.1.0.tar.gz` under the `dagoldfish`
namespace.

This collection is licensed under GPL-3.0-or-later. See [LICENSE](LICENSE).
