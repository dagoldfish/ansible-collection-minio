# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Webhook reconciliation and real SDK transport contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from ansible_collections.dagoldfish.minio.plugins.module_utils import minio_admin, webhook_config
from ansible_collections.dagoldfish.minio.plugins.modules import minio_webhook
from minio import MinioAdmin
from minio.credentials import StaticProvider
from minio.crypto import decrypt, encrypt
from minio.error import MinioAdminException
from test_modules import FailJson, Module, result
from urllib3 import PoolManager
from urllib3.response import HTTPResponse


class Config:
    def __init__(self, current=None, restart=False):
        self.current = current
        self.restart = restart
        self.calls = []

    def read(self, client, key):
        self.calls.append(("get", key))
        return self.current

    def write(self, client, key, changes=None):
        self.calls.append(("delete" if changes is None else "set", key, changes))
        self.current = None if changes is None else {**(self.current or {}), **changes}
        return self.restart


@pytest.fixture
def config(monkeypatch):
    config = Config()
    monkeypatch.setattr(minio_webhook, "read_config", config.read)
    monkeypatch.setattr(minio_webhook, "write_config", config.write)
    monkeypatch.setattr(minio_webhook, "validate_config_fields", lambda client, key, changes: None)
    return config


def params(**kwargs):
    return {"kind": "audit", "name": "security", "state": "present", "update_auth_token": False, **kwargs}


def run(config, check=False, **kwargs):
    return result(minio_webhook.run, Module(params(**kwargs), check), config)


@pytest.mark.parametrize("kind", ["logger", "audit"])
@pytest.mark.parametrize("name", ["_", "security"])
def test_create_and_repeat(config, kind, name):
    first = run(config, kind=kind, name=name, endpoint="https://receiver.test", auth_token='Bearer a "b"')
    assert first["changed"] and not first["restart_required"]
    assert first["webhook"]["enabled"] is True
    assert "auth_token" not in first["webhook"]
    assert config.calls[-1][1] == kind + "_webhook:" + name
    repeated = run(config, kind=kind, name=name, endpoint="https://receiver.test", auth_token="ignored")
    assert not repeated["changed"] and not repeated["restart_required"]
    assert config.calls[-1][0] == "get"


def test_omitted_fields_and_disabled_status_preserved(config):
    config.current = {"enable": "off", "endpoint": "https://old.test", "queue_dir": "/existing", "auth_token": "redacted"}
    out = run(config, endpoint="https://new.test")
    assert out["changed"]
    assert config.calls[-1][2] == {"enable": "off", "endpoint": "https://new.test"}
    assert config.current["queue_dir"] == "/existing"
    assert config.current["auth_token"] == "redacted"
    assert out["webhook"]["enabled"] is False


def test_omitted_enable_and_false_tls_normalized(config):
    config.current = {"endpoint": "https://receiver.test"}
    assert not run(config, enabled=True, tls_skip_verification=False)["changed"]


@pytest.mark.parametrize("token", ["", "Bearer new-secret"])
def test_explicit_token_rotation_and_clear(config, token):
    config.current = {"endpoint": "https://receiver.test"}
    out = run(config, update_auth_token=True, auth_token=token)
    assert out["changed"]
    assert config.calls[-1][2]["auth_token"] == token
    assert "auth_token" not in out["webhook"]


@pytest.mark.parametrize("state", ["present", "absent"])
def test_noop_never_requests_restart(config, state):
    config.current = {"endpoint": "https://receiver.test"} if state == "present" else None
    config.restart = True
    assert not run(config, state=state)["restart_required"]
    assert len(config.calls) == 1


@pytest.mark.parametrize("state", ["present", "absent"])
@pytest.mark.parametrize("check", [False, True])
def test_changed_restart_and_check_mode(config, state, check):
    config.current = {"endpoint": "https://old.test"}
    config.restart = True
    out = run(config, check=check, state=state, endpoint="https://new.test")
    assert out["changed"] and out["restart_required"]
    assert len(config.calls) == (1 if check else 2)


def test_check_mode_creation_is_conservative(config):
    out = run(config, check=True, endpoint="https://receiver.test")
    assert out["changed"] and out["restart_required"]
    assert len(config.calls) == 1


def test_default_reset_absent_and_recreation(config):
    config.current = {"enable": "off", "endpoint": "", "queue_size": "100000"}
    assert not run(config, name="_", state="absent")["changed"]
    assert run(config, name="_", endpoint="https://receiver.test")["changed"]
    assert config.calls[-1][2]["enable"] == "on"


def test_disable_then_remove_then_repeat(config):
    config.current = {"endpoint": "https://receiver.test"}
    assert run(config, enabled=False)["changed"]
    assert not run(config, enabled=False)["changed"]
    assert run(config, state="absent")["changed"]
    assert config.calls[-1] == ("delete", "audit_webhook:security", None)
    assert not run(config, state="absent")["changed"]


def test_numeric_and_duration_normalization(config):
    config.current = {"endpoint": "https://receiver.test", "batch_size": "001", "http_timeout": "1m0s"}
    assert not run(config, batch_size=1, http_timeout="60s")["changed"]


def test_create_requires_endpoint(config):
    with pytest.raises(FailJson, match="endpoint is required"):
        run(config)


@pytest.mark.parametrize("options", [
    {"update_auth_token": True}, {"endpoint": ""}, {"endpoint": "file:///secret"},
    {"name": "unsafe\nlogger_webhook"}, {"name": ""}, {"name": "a:b"},
    {"queue_size": 0}, {"batch_size": -1}, {"batch_max_size": 31999}, {"max_retry": -1},
    {"retry_interval": "61s"}, {"http_timeout": "500ms"}, {"http_timeout": "5"},
    {"comment": "x\naudit_webhook:new enable=on"}, {"auth_token": "Bearer endpoint=evil"},
])
def test_invalid_inputs_fail_before_api_read(config, options):
    with pytest.raises(ValueError):
        run(config, **options)
    assert not config.calls


@pytest.mark.parametrize("value", ["", "Bearer abc==", 'Bearer a"b', "'quoted'", '"quoted"', " leading and trailing ", r"a\b", "it's fine"])
def test_serializer_matches_server_sanitization(value):
    text = webhook_config.config_text({"auth_token": value})
    encoded = text.split("=", 1)[1].strip()
    # MinIO SanitizeValue removes one double layer then one single layer.
    decoded = encoded.removeprefix('"').removesuffix('"').removeprefix("'").removesuffix("'")
    assert decoded == value


def test_parse_real_minio_output_not_shell_escaping():
    text = '''# MINIO_AUDIT_WEBHOOK_ENDPOINT=https://env.test
logger_webhook:other endpoint=https://unrelated.test
audit_webhook endpoint=https://default.test
audit_webhook:security endpoint=https://receiver.test auth_token="Bearer a"b\\c" comment="two words" queue_dir= enable=off
'''
    parsed = webhook_config.parse_config(text, "audit_webhook:security")
    assert parsed == {"endpoint": "https://receiver.test", "auth_token": 'Bearer a"b\\c',
                      "comment": "two words", "queue_dir": "", "enable": "off"}
    assert webhook_config.parse_config(text, "audit_webhook:_") == {"endpoint": "https://default.test"}


@pytest.mark.parametrize("text", ["audit_webhook:security garbage", "audit_webhook:security enable=on enable=off",
                                  "audit_webhook:security\naudit_webhook:security"])
def test_malformed_read_is_not_silently_absent(text):
    with pytest.raises(ValueError):
        webhook_config.parse_config(text, "audit_webhook:security")


class TrackingResponse(HTTPResponse):
    def __init__(self, *args, **kwargs):
        self.closed_count = self.released_count = 0
        super().__init__(*args, **kwargs)

    def close(self):
        self.closed_count += 1
        super().close()

    def release_conn(self):
        self.released_count += 1
        super().release_conn()


@pytest.mark.parametrize("method", ["get", "set", "delete"])
@pytest.mark.parametrize("applied", [None, "false", "true", "TRUE"])
def test_signed_transport_and_response_cleanup(monkeypatch, method, applied):
    pool = PoolManager()
    client = MinioAdmin(endpoint="minio.test", credentials=StaticProvider("access", "test-secret"), http_client=pool)
    body = encrypt(b"audit_webhook:security endpoint=https://receiver.test", "test-secret") if method == "get" else b""
    headers = {"X-Minio-Config-Applied": applied} if applied is not None else {}
    response = TrackingResponse(body=body, status=200, headers=headers)
    requests = []

    def request(verb, url, **kwargs):
        requests.append((verb, url, kwargs))
        return response

    monkeypatch.setattr(pool, "urlopen", request)
    if method == "get":
        assert webhook_config.read_config(client, "audit_webhook:security")["endpoint"] == "https://receiver.test"
    else:
        changes = {"auth_token": 'Bearer a"b'} if method == "set" else None
        assert webhook_config.write_config(client, "audit_webhook:security", changes) is (applied != "true")
        plaintext = decrypt(webhook_config._BufferedAdminResponse(requests[0][2]["body"]), "test-secret").decode()
        assert plaintext == ("audit_webhook:security " + webhook_config.config_text(changes) if changes else "audit_webhook:security")
    verb, url, kwargs = requests[0]
    assert verb == {"get": "GET", "set": "PUT", "delete": "DELETE"}[method]
    assert "/minio/admin/v3/" + {"get": "get-config-kv", "set": "set-config-kv", "delete": "del-config-kv"}[method] in url
    if method == "get":
        assert "key=audit_webhook%3Asecurity" in url
    assert kwargs["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert response.closed_count >= 1 and response.released_count >= 1


@pytest.mark.parametrize("code,message,missing", [
    ("XMinioAdminNoSuchConfigTarget", "missing", True),
    ("XMinioAdminConfigBadJSON", "there is no target `security` for subsystem `audit_webhook`", True),
    ("AccessDenied", "not found", False),
    ("XMinioAdminConfigBadJSON", "unknown subsystem", False),
])
def test_only_missing_target_errors_are_absent(code, message, missing):
    def request(**kwargs):
        raise MinioAdminException("400", json.dumps({"Code": code, "Message": message}))
    client = SimpleNamespace(_url_open=request)
    if missing:
        assert webhook_config.read_config(client, "audit_webhook:security") is None
    else:
        with pytest.raises(MinioAdminException):
            webhook_config.read_config(client, "audit_webhook:security")


def test_cleanup_when_decryption_fails(monkeypatch):
    response = TrackingResponse(body=b"invalid", status=200)
    client = SimpleNamespace(_url_open=lambda **kwargs: response,
                             _provider=SimpleNamespace(retrieve=lambda: SimpleNamespace(secret_key="secret")))
    with pytest.raises(Exception):
        webhook_config.read_config(client, "audit_webhook:security")
    assert response.closed_count and response.released_count


def test_token_redacted_from_error():
    error = MinioAdminException("400", json.dumps({"Code": "BadConfig", "Message": 'token Bearer super-secret invalid'}))
    with pytest.raises(FailJson) as caught:
        minio_admin.fail_from_exception(Module({"auth_token": "Bearer super-secret"}), error)
    assert "super-secret" not in repr(caught.value.args)
    assert "***" in repr(caught.value.args)


@pytest.mark.parametrize("unsupported", [False, True])
def test_configuration_help_validates_fields_and_releases_response(unsupported):
    response = TrackingResponse(body=json.dumps({"keysHelp": [{"key": "endpoint"}, {"key": "auth_token"}]}).encode())
    calls = []

    def request(**kwargs):
        calls.append(kwargs)
        return response

    client = SimpleNamespace(_url_open=request)
    config = {"http_encoding": "cbor"} if unsupported else {"endpoint": "https://receiver.test", "enable": "off"}
    if unsupported:
        with pytest.raises(ValueError, match="unsupported.*http_encoding"):
            webhook_config.validate_config_fields(client, "audit_webhook:security", config)
    else:
        webhook_config.validate_config_fields(client, "audit_webhook:security", config)
    assert calls[0]["command"].value == "help-config-kv"
    assert calls[0]["query_params"] == {"subSys": "audit_webhook", "key": ""}
    assert response.closed_count and response.released_count


@pytest.mark.parametrize("check", [False, True])
def test_unsupported_settings_never_write(config, monkeypatch, check):
    def unsupported(client, key, changes):
        raise ValueError("Webhook settings unsupported by this server: http_encoding")
    monkeypatch.setattr(minio_webhook, "validate_config_fields", unsupported)
    with pytest.raises(ValueError, match="unsupported"):
        run(config, check=check, endpoint="https://receiver.test", http_encoding="cbor")
    assert config.calls == [("get", "audit_webhook:security")]
