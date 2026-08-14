# Changelog

All notable changes to `dagoldfish.minio` are documented here. Versions follow
Semantic Versioning while the public interface matures.

## 0.1.0 - Unreleased

### Added

- Modules for users, groups, policies, policy bindings, service accounts, and
  site replication.
- The `dagoldfish.minio.aistor_admin` reconciliation role.
- Unit, sanity, lint, artifact, and opt-in live integration validation.

### Safety

- Management is disabled by default at role level.
- Secret rotation and destructive replication removal require explicit flags.
- Authentication values are redacted from SDK exception messages.

The release remains blocked until the live IAM integration target passes
against a disposable AIStor deployment.
