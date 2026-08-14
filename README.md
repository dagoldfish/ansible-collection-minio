# `captain.minio`

An Ansible collection for managing MinIO AIStor administration resources with
the official Python SDK. The collection does not install or invoke `mc`.

## Requirements

- Python 3.9 or newer
- ansible-core 2.16 or newer
- minio 7.2.20 or newer on the host that executes the modules

```sh
python -m pip install 'minio>=7.2.20'
ansible-galaxy collection install git@github.com:dagoldfish/ansible-collection-minio.git
```

## Included content

The collection manages local users, groups, policies, policy bindings, service
accounts, and site replication. The `captain.minio.aistor_admin` role provides
ordered reconciliation for those resources.

All modules take a shared `auth` dictionary:

```yaml
auth:
  endpoint: aistor.example.com:9000
  access_key: "{{ lookup('ansible.builtin.env', 'AISTOR_ADMIN_ACCESS_KEY') }}"
  secret_key: "{{ lookup('ansible.builtin.env', 'AISTOR_ADMIN_SECRET_KEY') }}"
  secure: true
  validate_certs: true
```

See the module documentation with `ansible-doc captain.minio.minio_user`.

## Example playbook

The role is disabled by default. Credentials should come from an environment or
secret lookup and must never be committed to inventory.

The complete [`playbooks/manage_aistor.yml`](playbooks/manage_aistor.yml)
example demonstrates every supported role resource. It is safe by default:
the role does not contact AIStor unless `AISTOR_MANAGE=true` is explicitly set.

Preview it from the collection repository after exporting the required
environment-backed credentials:

```sh
export AISTOR_ENDPOINT='<host>:9000'
export AISTOR_ADMIN_ACCESS_KEY='<access-key>'
export AISTOR_ADMIN_SECRET_KEY='<secret-key>'
export AISTOR_EXAMPLE_USER_SECRET='<secret-key>'
export AISTOR_EXAMPLE_SERVICE_SECRET='<secret-key>'
export AISTOR_MANAGE=true
ansible-playbook playbooks/manage_aistor.yml --check
```

LDAP policy bindings cannot be previewed because the MinIO Python SDK does not
provide LDAP association read-back. Remove the LDAP binding from a preview or
run the reviewed configuration without `--check` when ready to apply it.

## Build for Galaxy

```sh
ansible-galaxy collection build
```

This produces `captain-minio-0.1.0.tar.gz`. Review the artifact contents before
uploading it to Galaxy. Publishing is intentionally not automated yet.
