#!/usr/bin/env bash
set -euo pipefail

validation_repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
validation_python="${VALIDATE_PYTHON:-python3}"
validation_ansible_core="${VALIDATE_ANSIBLE_CORE_VERSION:-2.20.2}"
validation_work_dir="$(mktemp -d /tmp/dagoldfish-minio-validate.XXXXXX)"
validation_collection_dir="${validation_work_dir}/ansible_collections/dagoldfish/minio"
validation_venv_dir="${validation_work_dir}/venv"
validation_artifact_dir="${validation_work_dir}/artifacts"
validation_install_dir="${validation_work_dir}/installed"

cleanup() {
  rm -rf -- "${validation_work_dir}"
}
trap cleanup EXIT

mkdir -p "${validation_collection_dir}" "${validation_artifact_dir}" "${validation_install_dir}"
cp -a "${validation_repo_dir}/." "${validation_collection_dir}/"

"${validation_python}" -m venv "${validation_venv_dir}"
"${validation_venv_dir}/bin/python" -m pip install \
  "ansible-core==${validation_ansible_core}" \
  -r "${validation_collection_dir}/requirements.txt" \
  -r "${validation_collection_dir}/test-requirements.txt" \
  -r "${validation_collection_dir}/tests/unit/requirements.txt"

export ANSIBLE_LOCAL_TEMP="${validation_work_dir}/ansible-local"
export ANSIBLE_COLLECTIONS_PATH="${validation_work_dir}"
export PYTHONPYCACHEPREFIX="${validation_work_dir}/pycache"
export PATH="${validation_venv_dir}/bin:${PATH}"

cd "${validation_collection_dir}"

ruff check .
python -m compileall -q plugins tests
PYTHONPATH="${validation_work_dir}" python -m pytest -q tests/unit
ansible-lint --offline --nocolor playbooks roles tests/integration
ansible-test sanity --venv

ansible-galaxy collection build --force --output-path "${validation_artifact_dir}"
shopt -s nullglob
validation_artifacts=("${validation_artifact_dir}"/dagoldfish-minio-*.tar.gz)
shopt -u nullglob
if (( ${#validation_artifacts[@]} != 1 )); then
  echo "Expected exactly one built collection artifact, found ${#validation_artifacts[@]}." >&2
  exit 1
fi
validation_artifact="${validation_artifacts[0]}"
tar -tzf "${validation_artifact}" >/dev/null
ansible-galaxy collection install "${validation_artifact}" --force -p "${validation_install_dir}"

export ANSIBLE_COLLECTIONS_PATH="${validation_install_dir}"
for validation_module in \
  minio_user \
  minio_group \
  minio_policy \
  minio_policy_binding \
  minio_service_account \
  minio_site_replication \
  minio_site_replication_info; do
  ansible-doc -t module "dagoldfish.minio.${validation_module}" >/dev/null
done

ansible-playbook playbooks/manage_aistor.yml --syntax-check
AISTOR_MANAGE=false ansible-playbook playbooks/manage_aistor.yml --check

echo "Validation passed for dagoldfish.minio ${validation_ansible_core}."
