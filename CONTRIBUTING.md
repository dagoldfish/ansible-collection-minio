# Contributing

Thank you for helping make `dagoldfish.minio` safer and easier to use.

## Local validation

Python 3.11 or newer, `venv`, and network access to PyPI are required for the
current validation toolchain. The collection itself still supports Python 3.9.
Run:

```sh
./scripts/validate.sh
```

The script works from any checkout path by copying the repository into a
temporary `ansible_collections/dagoldfish/minio` tree. It removes that tree on
exit and does not change tracked files.

Keep module behavior idempotent, preserve check mode, use FQCNs in YAML, and
add tests for both the changed and unchanged paths. Never include real secrets
or private service details in tests or examples.

## Live integration tests

Live targets are marked `destructive` and never belong in the default local or
pull-request workflow. Use only disposable AIStor environments.

Set the IAM test variables and run the target from a correctly laid-out
collection checkout:

```sh
export AISTOR_IT_ENDPOINT='<host>:9000'
export AISTOR_IT_ACCESS_KEY='<access-key>'
export AISTOR_IT_SECRET_KEY='<secret-key>'
ansible-test integration aistor_admin --allow-destructive -v
```

Site replication has a separate, more destructive target. Read its task file,
provide `AISTOR_IT_REPLICATION_SITES_JSON`, and set the explicit removal
acknowledgement only after confirming every site is disposable.

## Pull requests

- Explain the operator-facing problem and resulting behavior.
- Update module and role documentation when an interface changes.
- Add a changelog entry and tests.
- Confirm `./scripts/validate.sh` passes.
- Keep release publishing manual; pull requests must not upload to Galaxy.
