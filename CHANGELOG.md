# Changelog

All notable changes to `dagoldfish.minio` are documented in this file.

## Unreleased

### Added

- Create buckets and safely remove empty buckets through the official Python SDK.
- Reconcile buckets before policies with the `aistor_admin` role.

## 0.1.1 - 2026-08-21

### Fixed

- Treat already-satisfied LDAP policy attach and detach operations as idempotent no-ops.

## 0.1.0 - 2026-08-17

### Added

- Initial creation
