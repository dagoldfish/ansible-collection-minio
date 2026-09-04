# Changelog

All notable changes to `dagoldfish.minio` are documented in this file.

## 0.2.3 - 2026-09-05

### Fixed

- Retry transient site-replication topology reads, additions, edits, and
  removals, verifying the topology before resubmitting an add whose response
  may have been lost.
- Send native JSON number and boolean values when editing replication bandwidth
  and synchronization settings, as required by current AIStor servers.
- Preserve site-replication HTTP 5xx response bodies instead of allowing the
  SDK transport to replace them with an opaque retry-exhaustion exception.
- Preserve the final Admin API HTTP 5xx response after normal SDK retries so
  all administration modules report the server's diagnostic body.
- Preserve the final S3 HTTP 5xx response after normal SDK retries so bucket
  failures retain the server's error code, message, and request identifier.
- Return structured status, code, message, and request details for SDK failures,
  with explicit redaction of nested site-replication credentials.

## 0.2.2 - 2026-09-03

### Fixed

- Treat AIStor's `XMinioAdminNoSuchConfigTarget` response as an absent LDAP
  provider so the provider can be created declaratively.
- Wait for the signed AIStor Admin info endpoint after LDAP-triggered restarts,
  retrying transient connection failures, HTTP 5xx responses, and nginx HTTP
  403 responses with configurable delay and timeout values.

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
