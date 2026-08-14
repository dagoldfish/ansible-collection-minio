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

## Role example

The role is disabled by default. Credentials should come from an environment or
secret lookup and must never be committed to inventory.

```yaml
- name: Manage AIStor
  hosts: localhost
  connection: local
  gather_facts: false
  roles:
    - role: captain.minio.aistor_admin
      vars:
        aistor_admin_manage: true
        aistor_admin_auth:
          endpoint: aistor.example.com:9000
          access_key: "{{ lookup('ansible.builtin.env', 'AISTOR_ADMIN_ACCESS_KEY') }}"
          secret_key: "{{ lookup('ansible.builtin.env', 'AISTOR_ADMIN_SECRET_KEY') }}"
          secure: true
          validate_certs: true
        aistor_admin_policies:
          - name: archive-read
            policy:
              Version: "2012-10-17"
              Statement: []
```

## Build for Galaxy

```sh
ansible-galaxy collection build
```

This produces `captain-minio-0.1.0.tar.gz`. Review the artifact contents before
uploading it to Galaxy. Publishing is intentionally not automated yet.
