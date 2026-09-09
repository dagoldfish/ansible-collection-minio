# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run the real role with an isolated collection of instrumented mock modules."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
MOCK_MODULE = '''#!/usr/bin/python
import json
import os
from ansible.module_utils.basic import AnsibleModule

fields = (
    "auth name kind endpoint auth_token update_auth_token state enabled action wait_for_ready readiness_delay "
    "readiness_timeout policies user group identity_provider update_bind_password server_addr lookup_bind_dn "
    "lookup_bind_password user_dn_search_base_dn user_dn_search_filter user_dn_attributes group_search_base_dn "
    "group_search_filter srv_record_name comment tls_skip_verify server_insecure server_starttls client_cert "
    "client_key proxy queue_dir queue_size batch_size batch_max_size max_retry retry_interval http_timeout "
    "http_encoding tls_skip_verification "
).split()
m = AnsibleModule(argument_spec={key: {"type": "raw"} for key in fields}, supports_check_mode=True)
operation = "MOCK_OPERATION"
with open(os.environ["MOCK_LOG"], "a") as log:
    log.write(json.dumps({"operation": operation, "params": m.params, "check": m.check_mode}) + "\\n")
if operation == "minio_service":
    if os.environ.get("MOCK_FAIL_RESTART") == "1":
        m.fail_json(msg="simulated readiness failure")
    m.exit_json(changed=True, ready=not m.check_mode)
if operation == "minio_ldap_provider":
    changed = os.environ.get("MOCK_LDAP_CHANGED") == "1"
    m.exit_json(changed=changed, restart_required=changed, provider={"name": m.params["name"]})
if operation == "minio_webhook":
    changed = os.environ.get("MOCK_WEBHOOK_CHANGED", "1") == "1"
    pending = changed and (m.check_mode or os.environ.get("MOCK_DYNAMIC") != "1")
    m.exit_json(changed=changed, restart_required=pending, webhook={"kind": m.params["kind"], "name": m.params["name"]})
m.exit_json(changed=False)
'''


def execute_role(tmp_path, *, automatic=False, legacy=False, ldap=False, dynamic=False,
                 fail=False, check=False, changed=True, manage=True, repeat=False, external_handler=False):
    root = tmp_path / "collections"
    collection = root / "ansible_collections/dagoldfish/minio"
    shutil.copytree(REPO / "roles", collection / "roles")
    modules = collection / "plugins/modules"
    modules.mkdir(parents=True)
    for original in (REPO / "plugins/modules").glob("*.py"):
        (modules / original.name).write_text(MOCK_MODULE.replace("MOCK_OPERATION", original.stem))
    log = tmp_path / "operations.jsonl"
    variables = {
        "ansible_python_interpreter": sys.executable,
        "aistor_admin_manage": manage,
        "aistor_admin_auth": {"endpoint": "unused.test", "access_key": "test", "secret_key": "test"},
        "aistor_admin_restart_on_config_change": automatic,
        "aistor_admin_restart_on_ldap_change": legacy,
        "aistor_admin_ldap_providers": [{"name": "directory"}] if ldap else [],
        "aistor_admin_logger_webhooks": [{"name": "operations", "endpoint": "https://logs.test"},
                                         {"name": "secondary", "endpoint": "https://logs.test"}],
        "aistor_admin_audit_webhooks": [{"name": "security", "endpoint": "https://audit.test"}],
        "aistor_admin_policy_bindings": [{"policies": ["read"], "user": "builtin"},
                                         {"policies": ["read"], "user": "directory-user", "identity_provider": "ldap"}],
    }
    environment = {"MOCK_LOG": str(log), "MOCK_LDAP_CHANGED": "1" if ldap else "0",
                   "MOCK_DYNAMIC": "1" if dynamic else "0", "MOCK_FAIL_RESTART": "1" if fail else "0",
                   "MOCK_WEBHOOK_CHANGED": "1" if changed else "0"}
    tasks = [{"name": "First invocation", "ansible.builtin.include_role": {"name": "dagoldfish.minio.aistor_admin"}}]
    if repeat:
        tasks.append({"name": "Unchanged second invocation", "ansible.builtin.include_role": {"name": "dagoldfish.minio.aistor_admin"},
                      "vars": {"aistor_admin_ldap_providers": [], "aistor_admin_logger_webhooks": [], "aistor_admin_audit_webhooks": []}})
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False, "vars": variables,
             "environment": environment, "tasks": tasks}]
    if external_handler:
        tasks.insert(0, {"name": "Schedule external handler", "ansible.builtin.debug": {"msg": "external change"},
                         "changed_when": True, "notify": "External handler"})
        tasks.append({"name": "After role", "ansible.builtin.debug": {"msg": "role completed"}})
        play[0]["handlers"] = [{"name": "External handler", "ansible.builtin.debug": {"msg": "external activation"}}]
    playbook = tmp_path / "play.yml"
    playbook.write_text(yaml.safe_dump(play))
    env = dict(os.environ, ANSIBLE_COLLECTIONS_PATH=str(root), ANSIBLE_COLLECTIONS_PATHS=str(root),
               ANSIBLE_LOCAL_TEMP=str(tmp_path / "local"), ANSIBLE_REMOTE_TEMP=str(tmp_path / "remote"),
               ANSIBLE_NOCOLOR="1")
    command = [str(Path(sys.executable).with_name("ansible-playbook")), "-i", "localhost,", str(playbook)]
    if check:
        command.append("--check")
    completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=90, check=False)
    entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return completed, entries


@pytest.mark.parametrize("automatic,legacy,ldap,dynamic,restarts,deferred", [
    (True, False, True, False, 1, False),
    (True, False, False, True, 0, False),
    (False, False, True, False, 0, True),
    (False, True, True, False, 1, False),
    (False, True, False, False, 0, False),
    (True, False, True, True, 1, False),
])
def test_role_restart_batching_and_legacy_scope(tmp_path, automatic, legacy, ldap, dynamic, restarts, deferred):
    completed, entries = execute_role(tmp_path, automatic=automatic, legacy=legacy, ldap=ldap, dynamic=dynamic)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    operations = [e["operation"] for e in entries]
    assert operations.count("minio_service") == restarts
    assert operations.count("minio_webhook") == 3
    bindings = [e["params"]["user"] for e in entries if e["operation"] == "minio_policy_binding"]
    assert bindings == (["builtin"] if deferred else ["builtin", "directory-user"])
    if restarts:
        restart_index = operations.index("minio_service")
        assert all(i < restart_index for i, op in enumerate(operations) if op in ("minio_webhook", "minio_ldap_provider"))
        assert operations.index("minio_policy_binding") > restart_index
        restart = entries[restart_index]["params"]
        assert restart["wait_for_ready"] and restart["readiness_timeout"] == 180
    if deferred:
        assert "LDAP policy bindings are deferred" in completed.stdout
        assert "audit:security" in completed.stdout and "ldap:directory" in completed.stdout


def test_role_failed_readiness_stops_bindings(tmp_path):
    completed, entries = execute_role(tmp_path, automatic=True, ldap=True, fail=True)
    assert completed.returncode != 0
    operations = [e["operation"] for e in entries]
    assert operations.count("minio_service") == 1
    assert "minio_policy_binding" not in operations


def test_role_check_mode_defers_ldap_even_with_restart_opt_in(tmp_path):
    completed, entries = execute_role(tmp_path, automatic=True, ldap=True, check=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert all(e["check"] for e in entries)
    assert [e["params"]["user"] for e in entries if e["operation"] == "minio_policy_binding"] == ["builtin"]
    assert "restart would be needed" in completed.stdout


@pytest.mark.parametrize("manage,changed", [(False, True), (True, False)])
def test_role_disabled_or_unchanged_does_not_restart(tmp_path, manage, changed):
    completed, entries = execute_role(tmp_path, automatic=True, manage=manage, changed=changed)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not any(e["operation"] == "minio_service" for e in entries)
    if not manage:
        assert not entries


def test_role_reinitializes_activation_state_on_repeated_inclusion(tmp_path):
    completed, entries = execute_role(tmp_path, automatic=True, ldap=True, repeat=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert sum(e["operation"] == "minio_service" for e in entries) == 1


def test_unchanged_role_does_not_flush_unrelated_handlers(tmp_path):
    completed, entries = execute_role(tmp_path, changed=False, external_handler=True)
    assert not any(e["operation"] == "minio_service" for e in entries)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.index("TASK [After role]") < completed.stdout.index("RUNNING HANDLER [External handler]")
