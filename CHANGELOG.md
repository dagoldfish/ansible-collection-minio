# Changelog

All notable changes to `dagoldfish.minio` are documented in this file.

## Unreleased

### Added

- Manage default and named LDAP identity providers through the official Python SDK.
- Optionally restart AIStor once through a role handler after LDAP changes.
- Restart the AIStor service with the `minio_service` module.

## 0.1.1 - 2026-08-21

### Fixed

- Treat already-satisfied LDAP policy attach and detach operations as idempotent no-ops.

## 0.1.0 - 2026-08-17

### Added

- Initial creation
