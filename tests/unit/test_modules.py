# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for idempotency-critical module behavior."""

from __future__ import annotations

import importlib

import pytest
from minio.error import MinioAdminException

BASE = "ansible_collections.dagoldfish.minio.plugins.modules"


class ExitJson(Exception):
    pass


class FailJson(Exception):
    pass


class Module:
    def __init__(self, params, check_mode=False):
        self.params, self.check_mode = params, check_mode

    def exit_json(self, **kwargs):
        raise ExitJson(kwargs)

    def fail_json(self, **kwargs):
        raise FailJson(kwargs)


def result(func, module, client):
    with pytest.raises(ExitJson) as caught:
        func(module, client)
    return caught.value.args[0]


class Users:
    def __init__(self, exists=True):
        self.exists, self.calls = exists, []

    def user_list(self):
        return {"alice": {"status": "enabled"}} if self.exists else {}

    def user_info(self, key):
        return {"status": "enabled"}

    def user_add(self, *args):
        self.calls.append(("add", args))

    def user_remove(self, *args):
        self.calls.append(("remove", args))

    def user_enable(self, *args):
        self.calls.append(("enable", args))

    def user_disable(self, *args):
        self.calls.append(("disable", args))


def test_user_is_idempotent_and_rotation_is_explicit():
    mod = importlib.import_module(f"{BASE}.minio_user")
    params = {
        "access_key": "alice",
        "secret_key": "{{ test_secret }}",
        "state": "present",
        "status": "enabled",
        "update_secret": False,
    }
    client = Users()
    assert result(mod.run, Module(params), client)["changed"] is False
    params["update_secret"] = True
    assert result(mod.run, Module(params, True), client)["changed"] is True
    assert client.calls == []


def test_user_create_and_absent_check_mode_do_not_mutate():
    mod = importlib.import_module(f"{BASE}.minio_user")
    create = {
        "access_key": "alice",
        "secret_key": "{{ test_secret }}",
        "state": "present",
        "status": None,
        "update_secret": False,
    }
    client = Users(False)
    assert result(mod.run, Module(create, True), client)["changed"] is True
    assert client.calls == []

    create["state"] = "absent"
    existing = Users()
    assert result(mod.run, Module(create, True), existing)["changed"] is True
    assert existing.calls == []


def test_user_delete():
    mod = importlib.import_module(f"{BASE}.minio_user")
    params = {"access_key": "alice", "secret_key": None, "state": "absent", "status": None, "update_secret": False}
    client = Users()
    assert result(mod.run, Module(params), client)["changed"] is True
    assert client.calls == [("remove", ("alice",))]


class Groups:
    def __init__(self):
        self.calls = []

    def group_list(self):
        return ["team"]

    def group_info(self, name):
        return {"status": "enabled", "members": ["alice", "old"]}

    def group_add(self, name, members):
        self.calls.append(("add", members))

    def group_remove(self, name, members=None):
        self.calls.append(("remove", members))


def test_group_membership_adds_and_purges():
    mod = importlib.import_module(f"{BASE}.minio_group")
    params = {
        "name": "team",
        "state": "present",
        "members": ["alice", "bob"],
        "purge_members": True,
        "status": "enabled",
    }
    client = Groups()
    out = result(mod.run, Module(params), client)
    assert out["changed"] and out["group"]["members"] == ["alice", "bob"]
    assert client.calls == [("add", ["bob"]), ("remove", ["old"])]


def test_group_check_mode_predicts_without_mutating():
    mod = importlib.import_module(f"{BASE}.minio_group")
    params = {
        "name": "team",
        "state": "present",
        "members": ["alice", "bob"],
        "purge_members": True,
        "status": "enabled",
    }
    client = Groups()
    assert result(mod.run, Module(params, True), client)["changed"] is True
    assert client.calls == []


def test_group_delete():
    mod = importlib.import_module(f"{BASE}.minio_group")
    params = {"name": "team", "state": "absent", "members": None, "purge_members": False, "status": None}
    client = Groups()
    assert result(mod.run, Module(params), client)["changed"] is True
    assert client.calls == [("remove", None)]


class Policies:
    def __init__(self):
        self.calls = []

    def policy_list(self):
        return {"read": {}}

    def policy_info(self, name):
        return '{"Statement": [], "Version": "2012-10-17"}'

    def policy_add(self, *args, **kwargs):
        raise AssertionError("unexpected mutation")

    def policy_remove(self, name):
        self.calls.append(("remove", name))


def test_policy_canonical_comparison_is_idempotent():
    mod = importlib.import_module(f"{BASE}.minio_policy")
    params = {
        "name": "read",
        "policy": {"Version": "2012-10-17", "Statement": []},
        "policy_file": None,
        "state": "present",
    }
    assert result(mod.run, Module(params), Policies())["changed"] is False


def test_policy_delete():
    mod = importlib.import_module(f"{BASE}.minio_policy")
    params = {"name": "read", "policy": None, "policy_file": None, "state": "absent"}
    client = Policies()
    assert result(mod.run, Module(params), client)["changed"] is True
    assert client.calls == [("remove", "read")]


def test_policy_check_mode_predicts_update_without_mutating():
    mod = importlib.import_module(f"{BASE}.minio_policy")
    params = {
        "name": "read",
        "policy": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow"}]},
        "policy_file": None,
        "state": "present",
    }
    client = Policies()
    assert result(mod.run, Module(params, True), client)["changed"] is True


class Bindings:
    def get_policy_entities(self, *args):
        return {"userMappings": [{"user": "alice", "policies": ["read"]}]}

    def attach_policy(self, *args, **kwargs):
        raise AssertionError("unexpected mutation")


def test_builtin_binding_is_idempotent():
    mod = importlib.import_module(f"{BASE}.minio_policy_binding")
    params = {"policies": ["read"], "user": "alice", "group": None, "identity_provider": "builtin", "state": "present"}
    assert result(mod.run, Module(params), Bindings())["changed"] is False


def test_builtin_binding_check_mode_predicts_without_mutating():
    mod = importlib.import_module(f"{BASE}.minio_policy_binding")
    params = {
        "policies": ["write"],
        "user": "alice",
        "group": None,
        "identity_provider": "builtin",
        "state": "present",
    }
    assert result(mod.run, Module(params, True), Bindings())["changed"] is True


def test_ldap_check_mode_fails_clearly():
    mod = importlib.import_module(f"{BASE}.minio_policy_binding")
    params = {"policies": ["read"], "user": "uid=a", "group": None, "identity_provider": "ldap", "state": "present"}
    with pytest.raises(FailJson):
        mod.run(Module(params, True), object())


class LdapBindings:
    def attach_policy_ldap(self, policies, **target):
        return {"policiesAttached": policies}


def test_ldap_binding_uses_server_change_response():
    mod = importlib.import_module(f"{BASE}.minio_policy_binding")
    params = {"policies": ["read"], "user": "uid=a", "group": None, "identity_provider": "ldap", "state": "present"}
    assert result(mod.run, Module(params), LdapBindings())["changed"] is True


class ServiceAccounts:
    def __init__(self, current=None):
        self.current, self.calls = current, []

    def get_service_account(self, key):
        if self.current is None:
            raise MinioAdminException("404", "not found")
        return self.current

    def add_service_account(self, **kwargs):
        self.calls.append(("add", kwargs))
        return {"accessKey": kwargs["access_key"]}

    def update_service_account(self, **kwargs):
        self.calls.append(("update", kwargs))


def test_service_account_create_and_explicit_rotation():
    mod = importlib.import_module(f"{BASE}.minio_service_account")
    params = {
        "access_key": "svc",
        "secret_key": "{{ test_secret }}",
        "name": "Service",
        "description": None,
        "policy": None,
        "expiration": None,
        "status": None,
        "update_secret": False,
        "state": "present",
    }
    client = ServiceAccounts()
    assert result(mod.run, Module(params), client)["changed"] is True
    assert client.calls[0][0] == "add"
    params["update_secret"] = True
    client = ServiceAccounts({"accessKey": "svc", "name": "Service"})
    assert result(mod.run, Module(params, True), client)["changed"] is True
    assert client.calls == []


def test_service_account_propagates_auth_failure():
    mod = importlib.import_module(f"{BASE}.minio_service_account")
    params = {
        "access_key": "svc",
        "secret_key": None,
        "name": None,
        "description": None,
        "policy": None,
        "expiration": None,
        "status": None,
        "update_secret": False,
        "state": "absent",
    }
    client = ServiceAccounts()

    def deny(_key):
        raise MinioAdminException("403", "denied")

    client.get_service_account = deny
    with pytest.raises(MinioAdminException):
        mod.run(Module(params), client)


def test_service_account_status_update_and_delete():
    mod = importlib.import_module(f"{BASE}.minio_service_account")
    params = {
        "access_key": "svc",
        "secret_key": None,
        "name": None,
        "description": None,
        "policy": None,
        "expiration": None,
        "status": "disabled",
        "update_secret": False,
        "state": "present",
    }
    client = ServiceAccounts({"accessKey": "svc", "status": "enabled"})
    assert result(mod.run, Module(params), client)["changed"] is True
    assert client.calls == [("update", {"access_key": "svc", "status": "disabled"})]
    client.delete_service_account = lambda key: client.calls.append(("delete", key))
    params["state"] = "absent"
    assert result(mod.run, Module(params), client)["changed"] is True
    assert client.calls[-1] == ("delete", "svc")


class Replication:
    def __init__(self):
        self.calls = []

    def get_site_replication_info(self):
        return {"enabled": True, "sites": [{"name": "one"}]}

    def remove_site_replication(self, **kwargs):
        self.calls.append(kwargs)


def test_replication_removal_requires_force():
    mod = importlib.import_module(f"{BASE}.minio_site_replication")
    params = {"sites": [{"name": "one"}], "state": "absent", "force": False, "remove_all": False}
    with pytest.raises(FailJson):
        mod.run(Module(params), Replication())


def test_replication_removal_predicts_topology_in_check_mode():
    mod = importlib.import_module(f"{BASE}.minio_site_replication")
    params = {"sites": [{"name": "one"}], "state": "absent", "force": True, "remove_all": False}
    client = Replication()
    out = result(mod.run, Module(params, True), client)
    assert out == {"changed": True, "site_replication": {"enabled": False, "sites": []}}
    assert client.calls == []


@pytest.mark.parametrize(
    ("params", "message"),
    [
        (
            {"sites": [{"name": "one"}, {"name": "one"}], "state": "present", "force": False, "remove_all": False},
            "site names must be unique",
        ),
        (
            {
                "sites": [{"name": "one", "bandwidth_limit": -1}],
                "state": "present",
                "force": False,
                "remove_all": False,
            },
            "bandwidth_limit cannot be negative",
        ),
        (
            {"sites": [], "state": "present", "force": True, "remove_all": False},
            "only valid when state=absent",
        ),
        (
            {"sites": [{"name": "one"}], "state": "absent", "force": True, "remove_all": True},
            "sites must be empty",
        ),
        (
            {"sites": [], "state": "absent", "force": True, "remove_all": False},
            "at least one name",
        ),
    ],
)
def test_replication_rejects_ambiguous_inputs(params, message):
    mod = importlib.import_module(f"{BASE}.minio_site_replication")
    with pytest.raises(FailJson) as caught:
        mod.run(Module(params), Replication())
    assert message in caught.value.args[0]["msg"]


def test_replication_existing_topology_is_idempotent():
    mod = importlib.import_module(f"{BASE}.minio_site_replication")
    params = {"sites": [{"name": "one"}], "state": "present", "force": False, "remove_all": False}
    assert result(mod.run, Module(params), Replication())["changed"] is False


def test_replication_add_applies_requested_settings(monkeypatch):
    mod = importlib.import_module(f"{BASE}.minio_site_replication")
    monkeypatch.setattr(mod, "PeerSite", lambda *args: args)
    monkeypatch.setattr(mod, "PeerInfo", lambda *args, **kwargs: (args, kwargs))

    class Client:
        def __init__(self):
            self.reads, self.calls = 0, []

        def get_site_replication_info(self):
            self.reads += 1
            if self.reads == 1:
                return {"enabled": False, "sites": []}
            return {
                "enabled": True,
                "sites": [
                    {
                        "name": "two",
                        "endpoint": "https://two",
                        "deploymentID": "dep2",
                        "sync": "disable",
                        "defaultbandwidth": {"bandwidthLimitPerBucket": 0},
                    }
                ],
            }

        def add_site_replication(self, peers):
            self.calls.append(("add", peers))

        def edit_site_replication(self, peer):
            self.calls.append(("edit", peer))

    params = {
        "sites": [
            {
                "name": "two",
                "endpoint": "https://two",
                "access_key": "admin",
                "secret_key": "{{ test_secret }}",
                "sync": True,
                "bandwidth_limit": 1024,
            }
        ],
        "state": "present",
        "force": False,
        "remove_all": False,
    }
    client = Client()
    assert result(mod.run, Module(params), client)["changed"] is True
    assert [call[0] for call in client.calls] == ["add", "edit"]


def test_replication_add_check_mode_predicts_without_mutating():
    mod = importlib.import_module(f"{BASE}.minio_site_replication")

    class Client:
        def __init__(self):
            self.calls = []

        def get_site_replication_info(self):
            return {"enabled": False, "sites": []}

        def add_site_replication(self, peers):
            self.calls.append(peers)

    params = {
        "sites": [
            {
                "name": "two",
                "endpoint": "https://two",
                "access_key": "admin",
                "secret_key": "{{ test_secret }}",
            }
        ],
        "state": "present",
        "force": False,
        "remove_all": False,
    }
    client = Client()
    out = result(mod.run, Module(params, True), client)
    assert out["changed"] is True
    assert out["site_replication"]["sites"] == [{"name": "two", "endpoint": "https://two"}]
    assert client.calls == []


def test_replication_info_reads_optional_status(monkeypatch):
    mod = importlib.import_module(f"{BASE}.minio_site_replication_info")
    monkeypatch.setattr(mod, "SiteReplicationStatusOptions", lambda **kwargs: kwargs)

    class Client:
        def get_site_replication_info(self):
            return '{"enabled": true, "sites": []}'

        def get_site_replication_status(self, options):
            assert all(options.values())
            return '{"healthy": true}'

    out = result(mod.run, Module({"include_status": True}), Client())
    assert out == {
        "changed": False,
        "site_replication": {"enabled": True, "sites": []},
        "status": {"healthy": True},
    }
