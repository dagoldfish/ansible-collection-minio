# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for shared MinIO administration helpers."""

from __future__ import annotations

import importlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
    pool = object()

    def provider(access_key, secret_key):
        calls["credentials"] = (access_key, secret_key)
        return "credentials"

    def client(**kwargs):
        calls["client"] = kwargs
        return "client"

    def pool_manager(**kwargs):
        calls["pool"] = kwargs
        return pool

    monkeypatch.setattr(helpers, "MINIO_IMP_ERR", None)
    monkeypatch.setattr(helpers, "StaticProvider", provider)
    monkeypatch.setattr(helpers, "PoolManager", pool_manager)
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
        "http_client": pool,
    }
    assert calls["pool"]["cert_reqs"] == "CERT_NONE"
    retry = calls["pool"]["retries"]
    assert retry.total == 5
    assert retry.backoff_factor == 0.2
    assert retry.raise_on_status is False
    assert retry.status_forcelist == [500, 502, 503, 504]


def test_admin_client_can_preserve_admin_error_responses(monkeypatch):
    helpers = importlib.import_module(MODULE)
    calls = {}
    pool = object()

    def pool_manager(**kwargs):
        calls["pool"] = kwargs
        return pool

    def client(**kwargs):
        calls["client"] = kwargs
        return "client"

    monkeypatch.setattr(helpers, "MINIO_IMP_ERR", None)
    monkeypatch.setattr(helpers, "StaticProvider", lambda access_key, secret_key: "credentials")
    monkeypatch.setattr(helpers, "PoolManager", pool_manager)
    monkeypatch.setattr(helpers, "MinioAdmin", client)
    module = Module(
        {
            "auth": {
                "endpoint": "https://aistor.example.com:9000",
                "access_key": "admin",
                "secret_key": "secret",
                "region": "",
                "secure": True,
                "validate_certs": True,
            }
        }
    )

    assert helpers.admin_client(module, preserve_error_response=True) == "client"
    assert calls["client"]["http_client"] is pool
    assert calls["pool"]["cert_reqs"] == "CERT_REQUIRED"
    retry = calls["pool"]["retries"]
    assert retry.total == 0
    assert retry.raise_on_status is False
    assert retry.status_forcelist == [500, 502, 503, 504]


def test_single_attempt_admin_http_client_preserves_first_503_body():
    helpers = importlib.import_module(MODULE)

    class Handler(BaseHTTPRequestHandler):
        attempts = 0

        def do_PUT(self):
            Handler.attempts += 1
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = b'{"Code":"PeerError","Message":"peer rejected configuration"}'
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        client = helpers.MinioAdmin(
            endpoint=f"127.0.0.1:{server.server_port}",
            credentials=helpers.StaticProvider("admin", "secret"),
            secure=False,
            http_client=helpers._single_attempt_admin_http_client(cert_check=False),
        )
        peer = helpers.PeerSite("site-two", "https://site-two.example.com", "admin", "secret")
        with pytest.raises(MinioAdminException) as caught:
            client.add_site_replication([peer])
        assert caught.value._code == "503"
        assert caught.value._body == '{"Code":"PeerError","Message":"peer rejected configuration"}'
        assert Handler.attempts == 1
    finally:
        server.shutdown()
        thread.join()


def test_admin_http_client_preserves_final_503_body_after_retries():
    helpers = importlib.import_module(MODULE)

    class Handler(BaseHTTPRequestHandler):
        attempts = 0

        def do_GET(self):
            Handler.attempts += 1
            body = f'{{"Code":"PeerError","Message":"attempt {Handler.attempts}"}}'.encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        client = helpers.MinioAdmin(
            endpoint=f"127.0.0.1:{server.server_port}",
            credentials=helpers.StaticProvider("admin", "secret"),
            secure=False,
            http_client=helpers._admin_http_client(cert_check=False, retries=2),
        )
        with pytest.raises(MinioAdminException) as caught:
            client.info()
        assert caught.value._code == "503"
        assert caught.value._body == '{"Code":"PeerError","Message":"attempt 3"}'
        assert Handler.attempts == 3
    finally:
        server.shutdown()
        thread.join()


def test_s3_client_normalizes_endpoint_and_passes_tls_options(monkeypatch):
    helpers = importlib.import_module(MODULE)
    calls = {}

    def client(**kwargs):
        calls["client"] = kwargs
        return "client"

    monkeypatch.setattr(helpers, "MINIO_IMP_ERR", None)
    monkeypatch.setattr(helpers, "Minio", client)
    module = Module(
        {
            "auth": {
                "endpoint": "https://aistor.example.com:9000/",
                "access_key": "admin",
                "secret_key": "secret",
                "region": "",
                "secure": True,
                "validate_certs": False,
            }
        }
    )

    assert helpers.s3_client(module) == "client"
    assert calls["client"] == {
        "endpoint": "aistor.example.com:9000",
        "access_key": "admin",
        "secret_key": "secret",
        "region": None,
        "secure": True,
        "cert_check": False,
    }


def test_signed_ldap_idp_adapter_uses_current_dedicated_routes(monkeypatch):
    helpers = importlib.import_module(MODULE)

    class Credentials:
        secret_key = "admin-secret"

    class Provider:
        def retrieve(self):
            return Credentials()

    class Response:
        def __init__(self, data=b""):
            self.data = data
            self.closed = False

        def close(self):
            self.closed = True

        def release_conn(self):
            self.closed = True

    class Client:
        _provider = Provider()

        def __init__(self):
            self.calls = []

        def _url_open(self, **kwargs):
            self.calls.append(kwargs)
            data = b'{"type":"ldap","name":"_","info":[]}' if kwargs["method"] == "GET" else b""
            return Response(data)

    monkeypatch.setattr(helpers, "encrypt", lambda payload, secret: b"encrypted:" + payload)
    monkeypatch.setattr(helpers, "decrypt", lambda response, secret: response.data)
    client = Client()

    assert helpers.ldap_idp_get(client, "_")["type"] == "ldap"
    helpers.ldap_idp_set(client, "_", {"server_addr": "ldap.example.com:636"}, update=False)
    helpers.ldap_idp_set(client, "_", {"comment": "Directory service"}, update=True)
    helpers.ldap_idp_delete(client, "_")

    assert [(call["method"], call["command"].value) for call in client.calls] == [
        ("GET", "idp-config/ldap/_"),
        ("PUT", "idp-config/ldap/_"),
        ("POST", "idp-config/ldap/_"),
        ("DELETE", "idp-config/ldap/_"),
    ]
    assert all(call["preload_content"] is True for call in client.calls)
    assert client.calls[2]["body"] == b'encrypted:comment="Directory service"'


def test_signed_ldap_idp_adapter_preserves_transport_error(monkeypatch):
    helpers = importlib.import_module(MODULE)

    class Client:
        def _url_open(self, **kwargs):
            raise MinioAdminException("400", "original Admin API error")

    error = MinioAdminException("400", "original Admin API error")

    def fail(**kwargs):
        raise error

    client = Client()
    client._url_open = fail
    with pytest.raises(MinioAdminException) as caught:
        helpers.ldap_idp_get(client, "_")
    assert caught.value is error


def test_json_helpers_accept_sdk_strings_and_stabilize_policies():
    helpers = importlib.import_module(MODULE)
    assert helpers.parse_json('{"answer": 42}') == {"answer": 42}
    assert helpers.parse_json(None, {}) == {}
    assert helpers.canonical_json({"b": 2, "a": 1}) == helpers.canonical_json('{"a": 1, "b": 2}')


def test_policy_comparison_treats_set_like_arrays_as_unordered_without_mutation():
    helpers = importlib.import_module(MODULE)
    desired = {
        "Statement": [
            {"Effect": "Deny", "NotAction": ["s3:DeleteObject", "s3:GetObject"]},
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": ["arn:two", "arn:one"],
                "Condition": {"StringEquals": {"s3:ExistingObjectTag/team": ["blue", "green"]}},
            },
        ]
    }
    reordered = {
        "Statement": [
            {
                "Condition": {"StringEquals": {"s3:ExistingObjectTag/team": ["green", "blue"]}},
                "Resource": ["arn:one", "arn:two"],
                "Action": ["s3:PutObject", "s3:GetObject"],
                "Effect": "Allow",
            },
            {"NotAction": ["s3:GetObject", "s3:DeleteObject"], "Effect": "Deny"},
        ]
    }
    original = repr(desired)
    assert helpers.canonical_json(desired) == helpers.canonical_json(reordered)
    assert repr(desired) == original


def test_policy_comparison_preserves_actual_differences():
    helpers = importlib.import_module(MODULE)
    left = {"Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"]}]}
    right = {"Statement": [{"Effect": "Deny", "Action": ["s3:GetObject"]}]}
    assert helpers.canonical_json(left) != helpers.canonical_json(right)


def test_fail_from_exception_redacts_authentication_values():
    helpers = importlib.import_module(MODULE)
    module = Module({"auth": {"access_key": "admin-key", "secret_key": "top-secret"}})
    with pytest.raises(FailJson) as caught:
        helpers.fail_from_exception(module, RuntimeError("admin-key could not use top-secret"))
    message = caught.value.args[0]["msg"]
    assert "admin-key" not in message
    assert "top-secret" not in message
    assert message == "MinIO AIStor API request failed: *** could not use ***"


def test_fail_from_exception_redacts_ldap_bind_password():
    helpers = importlib.import_module(MODULE)
    module = Module({"auth": {}, "lookup_bind_password": "directory-secret"})
    with pytest.raises(FailJson) as caught:
        helpers.fail_from_exception(module, RuntimeError("LDAP rejected directory-secret"))
    assert caught.value.args[0]["msg"] == "MinIO AIStor API request failed: LDAP rejected ***"


def test_not_found_only_matches_admin_404():
    helpers = importlib.import_module(MODULE)
    assert helpers.is_not_found(MinioAdminException("404", "missing")) is True
    assert helpers.is_not_found(MinioAdminException("403", "denied")) is False
    assert helpers.is_not_found(RuntimeError("404")) is False
