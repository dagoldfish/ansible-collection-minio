# Changelog

All notable changes to `dagoldfish.minio` are documented in this file.

## 0.2.1 - 2026-08-21

### Fixed

- Create, read, update, and remove LDAP providers through the dedicated signed IDP Admin API.
- Normalize omitted default-off LDAP boolean values during provider read-back.
- Preserve LDAP bind-password secrecy in successful results and API failures.
- Treat already-applied LDAP policy association changes as idempotent no-ops.
- Normalize service-account status read-back and validate explicit secret lengths locally.
- Compare set-like IAM policy arrays without regard to server-side ordering.

### Documented

- Root-owned service accounts remain local because MinIO site replication does not replicate them.

## 0.2.0 - 2026-08-21

### Added

- Manage default and named LDAP identity providers through the official Python SDK.
- Optionally restart AIStor once through a role handler after LDAP changes.
- Restart the AIStor service with the `minio_service` module.
- Create buckets and safely remove empty buckets through the official Python SDK.
- Reconcile buckets before policies with the `aistor_admin` role.

## 0.1.1 - 2026-08-21

### Fixed

- Treat already-satisfied LDAP policy attach and detach operations as idempotent no-ops.

## 0.1.0 - 2026-08-17

### Added

- Initial creation
