# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for shared MinIO administration helpers."""

from __future__ import annotations

import importlib

import pytest
from minio.error import MinioAdminException

MODULE = "ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin"


class FailJson(Exception):
    pass


class Module:
    def __init__(self, params):
        self.params = params

    def fail_json(self, **kwargs):
        raise FailJson(kwargs)


def test_admin_client_normalizes_endpoint_and_passes_tls_options(monkeypatch):
    helpers = importlib.import_module(MODULE)
    calls = {}

    def provider(access_key, secret_key):
        calls["credentials"] = (access_key, secret_key)
        return "credentials"

    def client(**kwargs):
        calls["client"] = kwargs
        return "client"

    monkeypatch.setattr(helpers, "MINIO_IMP_ERR", None)
    monkeypatch.setattr(helpers, "StaticProvider", provider)
    monkeypatch.setattr(helpers, "MinioAdmin", client)
    module = Module(
        {
            "auth": {
                "endpoint": "https://aistor.example.com:9000/",
                "access_key": "admin",
                "secret_key": "secret",
                "region": "eu-west-1",
                "secure": True,
                "validate_certs": False,
            }
        }
    )

    assert helpers.admin_client(module) == "client"
    assert calls["credentials"] == ("admin", "secret")
    assert calls["client"] == {
        "endpoint": "aistor.example.com:9000",
        "credentials": "credentials",
        "region": "eu-west-1",
        "secure": True,
        "cert_check": False,
    }


def test_json_helpers_accept_sdk_strings_and_stabilize_policies():
    helpers = importlib.import_module(MODULE)
    assert helpers.parse_json('{"answer": 42}') == {"answer": 42}
    assert helpers.parse_json(None, {}) == {}
    assert helpers.canonical_json({"b": 2, "a": 1}) == helpers.canonical_json('{"a": 1, "b": 2}')


def test_fail_from_exception_redacts_authentication_values():
    helpers = importlib.import_module(MODULE)
    module = Module({"auth": {"access_key": "admin-key", "secret_key": "top-secret"}})
    with pytest.raises(FailJson) as caught:
        helpers.fail_from_exception(module, RuntimeError("admin-key could not use top-secret"))
    message = caught.value.args[0]["msg"]
    assert "admin-key" not in message
    assert "top-secret" not in message
    assert message == "MinIO AIStor API request failed: *** could not use ***"


def test_not_found_only_matches_admin_404():
    helpers = importlib.import_module(MODULE)
    assert helpers.is_not_found(MinioAdminException("404", "missing")) is True
    assert helpers.is_not_found(MinioAdminException("403", "denied")) is False
    assert helpers.is_not_found(RuntimeError("404")) is False
