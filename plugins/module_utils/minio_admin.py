# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared MinIO Admin client construction and response helpers."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import re
import traceback
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from typing import Any, Optional
from urllib.parse import unquote

from ansible.module_utils.basic import missing_required_lib

__all__ = ("PeerInfo", "PeerSite", "SiteReplicationStatusOptions")

_MAX_ERROR_BODY_LENGTH = 16384
_MAX_ERROR_FIELD_LENGTH = 4096
_URL_USERINFO = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/?#\s]+)@")

MINIO_IMP_ERR = None
try:
    import certifi
    from minio import Minio, MinioAdmin
    from minio.credentials import StaticProvider
    from minio.crypto import decrypt, encrypt
    from minio.error import InvalidResponseError, MinioAdminException, S3Error, ServerError
    from minio.minioadmin import PeerInfo, PeerSite, SiteReplicationStatusOptions
    from urllib3 import PoolManager, Retry
    from urllib3.exceptions import HTTPError
    from urllib3.util import Timeout
except ImportError:
    MINIO_IMP_ERR = traceback.format_exc()
    Minio = None  # type: ignore[assignment,misc]
    MinioAdmin = None  # type: ignore[assignment,misc]
    StaticProvider = None  # type: ignore[assignment,misc]
    decrypt = None  # type: ignore[assignment,misc]
    encrypt = None  # type: ignore[assignment,misc]
    MinioAdminException = Exception  # type: ignore[assignment,misc]
    InvalidResponseError = Exception  # type: ignore[assignment,misc]
    S3Error = Exception  # type: ignore[assignment,misc]
    ServerError = Exception  # type: ignore[assignment,misc]
    HTTPError = OSError  # type: ignore[assignment,misc]
    PeerSite = None  # type: ignore[assignment,misc]
    PeerInfo = None  # type: ignore[assignment,misc]
    SiteReplicationStatusOptions = None  # type: ignore[assignment,misc]
    PoolManager = None  # type: ignore[assignment,misc]
    Retry = None  # type: ignore[assignment,misc]
    Timeout = None  # type: ignore[assignment,misc]


def auth_argument_spec() -> dict[str, Any]:
    """Return the common nested authentication argument specification."""
    return {
        "type": "dict",
        "required": True,
        "options": {
            "endpoint": {"type": "str", "required": True},
            "access_key": {"type": "str", "required": True, "no_log": True},
            "secret_key": {"type": "str", "required": True, "no_log": True},
            "secure": {"type": "bool", "default": True},
            "validate_certs": {"type": "bool", "default": True},
            "region": {"type": "str", "default": ""},
        },
    }


def _sdk_http_client(cert_check: bool, *, retries: int = 5) -> Any:
    """Build a pool that returns the final HTTP response after SDK retries."""
    timeout = timedelta(minutes=5).seconds
    return PoolManager(
        timeout=Timeout(connect=timeout, read=timeout),
        maxsize=10,
        cert_reqs="CERT_REQUIRED" if cert_check else "CERT_NONE",
        ca_certs=os.environ.get("SSL_CERT_FILE") or certifi.where(),
        retries=Retry(
            total=retries,
            backoff_factor=0.2,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False,
        ),
    )


def _single_attempt_admin_http_client(cert_check: bool) -> Any:
    """Build an SDK-compatible pool that leaves retries to the Ansible module."""
    return _sdk_http_client(cert_check, retries=0)


def admin_client(module: Any, *, preserve_error_response: bool = False) -> Any:
    """Build the official SDK admin client from module parameters."""
    if MINIO_IMP_ERR:
        module.fail_json(
            msg=missing_required_lib("minio", url="https://github.com/minio/minio-py"),
            exception=MINIO_IMP_ERR,
        )
    auth = module.params["auth"]
    endpoint = auth["endpoint"].removeprefix("https://").removeprefix("http://").rstrip("/")
    options = {
        "endpoint": endpoint,
        "credentials": StaticProvider(auth["access_key"], auth["secret_key"]),
        "region": auth["region"],
        "secure": auth["secure"],
        "cert_check": auth["validate_certs"],
        "http_client": _sdk_http_client(auth["validate_certs"]),
    }
    if preserve_error_response:
        # MinioAdmin's default pool retries 5xx responses, including PUT, and
        # can replace the server's useful response with a MaxRetryError. The
        # site-replication module owns retries so it can inspect topology after
        # an ambiguous add and retain the original Admin API error body.
        options["http_client"] = _single_attempt_admin_http_client(auth["validate_certs"])
    return MinioAdmin(
        **options,
    )


def s3_client(module: Any) -> Any:
    """Build the official SDK S3 client from module parameters."""
    if MINIO_IMP_ERR:
        module.fail_json(
            msg=missing_required_lib("minio", url="https://github.com/minio/minio-py"),
            exception=MINIO_IMP_ERR,
        )
    auth = module.params["auth"]
    endpoint = auth["endpoint"].removeprefix("https://").removeprefix("http://").rstrip("/")
    return Minio(
        endpoint=endpoint,
        access_key=auth["access_key"],
        secret_key=auth["secret_key"],
        region=auth["region"] or None,
        secure=auth["secure"],
        cert_check=auth["validate_certs"],
        http_client=_sdk_http_client(auth["validate_certs"]),
    )


def parse_json(value: Any, default: Any = None) -> Any:
    """Decode SDK JSON strings while accepting already-decoded test values."""
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def is_transport_error(error: Exception) -> bool:
    """Return whether an exception represents a temporary transport failure."""
    return isinstance(error, (HTTPError, OSError, TimeoutError))


def canonical_json(value: Any) -> str:
    """Return a semantic, stable representation for IAM policy comparison."""
    if isinstance(value, str):
        value = json.loads(value)
    return json.dumps(_canonical_policy(deepcopy(value)), sort_keys=True, separators=(",", ":"))


_UNORDERED_IAM_ARRAYS = {"Statement", "Action", "NotAction", "Resource", "NotResource"}


def _canonical_policy(value: Any, path: tuple[str, ...] = ()) -> Any:
    """Normalize only set-like IAM arrays, leaving the submitted policy untouched."""
    if isinstance(value, dict):
        return {key: _canonical_policy(item, path + (key,)) for key, item in value.items()}
    if isinstance(value, list):
        normalized = [_canonical_policy(item, path) for item in value]
        if (path and path[-1] in _UNORDERED_IAM_ARRAYS) or "Condition" in path:
            return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return normalized
    return value


@dataclass(frozen=True)
class _AdminCommand:
    """Command shape accepted by minio-py's signed private transport."""

    value: str


class _BufferedAdminResponse:
    """Provide minio.crypto.decrypt a response over a preloaded body."""

    def __init__(self, data: bytes):
        self.data = data
        self._stream = BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()

    def release_conn(self) -> None:
        pass


def _idp_command(name: str) -> _AdminCommand:
    return _AdminCommand(f"idp-config/ldap/{name}")


def _idp_config_text(config: dict[str, str]) -> str:
    """Serialize IDP KVS input while preserving whitespace in values."""
    values = []
    for key, value in config.items():
        text = str(value)
        if any(character.isspace() for character in text) or any(character in text for character in ('"', "\\")):
            text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
        values.append(f"{key}={text}")
    return " ".join(values)


def _idp_request(client: Any, method: str, name: str, config: Optional[dict[str, str]] = None) -> Any:
    """Call the dedicated IDP Admin API through minio-py's signer and transport."""
    response = None
    try:
        body = None
        if config is not None:
            secret_key = client._provider.retrieve().secret_key
            body = encrypt(_idp_config_text(config).encode(), secret_key)
        response = client._url_open(
            method=method,
            command=_idp_command(name),
            body=body,
            # Preload errors so minio-py cannot discard the Admin API body.
            preload_content=True,
        )
        if method != "GET":
            return None
        secret_key = client._provider.retrieve().secret_key
        return json.loads(decrypt(_BufferedAdminResponse(response.data), secret_key).decode())
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def ldap_idp_get(client: Any, name: str = "_") -> dict[str, Any]:
    """Read an LDAP provider with an official method or the signed adapter."""
    method = getattr(client, "get_idp_config", None)
    if method:
        return parse_json(method("ldap", name), {}) or {}
    return _idp_request(client, "GET", name)


def ldap_idp_set(client: Any, name: str, config: dict[str, str], update: bool) -> None:
    """Create or update an LDAP provider through the dedicated IDP API."""
    method = getattr(client, "add_or_update_idp_config", None)
    if method:
        method("ldap", name, _idp_config_text(config), update=update)
        return
    _idp_request(client, "POST" if update else "PUT", name, config)


def ldap_idp_delete(client: Any, name: str) -> None:
    """Delete an LDAP provider through the dedicated IDP API."""
    method = getattr(client, "delete_idp_config", None)
    if method:
        method("ldap", name)
        return
    _idp_request(client, "DELETE", name)


def redact_url_credentials(value: str) -> str:
    """Mask URL userinfo without changing the destination or request value."""
    return _URL_USERINFO.sub(r"\1***@", value)


def url_sensitive_values(value: Any) -> list[str]:
    """Collect encoded and decoded URL credentials for the common redactor."""
    if not isinstance(value, str):
        return []
    values = []
    for match in _URL_USERINFO.finditer(value):
        userinfo = match.group(2)
        for part in (userinfo, *userinfo.split(":", 1)):
            if part:
                values.extend((part, unquote(part)))
    return values


def register_url_credentials(module: Any, *urls: Any) -> None:
    """Protect supplied and read-back credentials in Ansible results/invocation."""
    for url in urls:
        module.no_log_values.update(url_sensitive_values(url))


def _sensitive_values(params: dict[str, Any]) -> list[Any]:
    """Collect credentials that an API error could echo in its response."""
    auth = params.get("auth", {}) if isinstance(params.get("auth", {}), dict) else {}
    values = [auth.get("access_key"), auth.get("secret_key")]
    values.extend(params.get(field) for field in ("secret_key", "lookup_bind_password", "auth_token", "proxy"))
    for url in (auth.get("endpoint"), params.get("endpoint"), params.get("proxy")):
        values.extend(url_sensitive_values(url))
    for site in params.get("sites", []) or []:
        if isinstance(site, dict):
            values.extend(site.get(field) for field in ("access_key", "secret_key"))
    return [value for value in values if value]


def _redact(value: Any, sensitive_values: list[Any]) -> Any:
    """Redact known credentials from strings and structured diagnostics."""
    if isinstance(value, dict):
        return {_redact(key, sensitive_values): _redact(item, sensitive_values) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, sensitive_values) for item in value]
    if not isinstance(value, str):
        return value
    result = redact_url_credentials(value)
    for sensitive in sorted(sensitive_values, key=lambda item: len(str(item)), reverse=True):
        result = result.replace(str(sensitive), "***")
    return result


def _status_code(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _scalar_text(value: Any) -> Optional[str]:
    """Return text only for scalar diagnostic values."""
    if value is None or isinstance(value, (dict, list)):
        return None
    return str(value)


def _diagnostic_text(value: Any) -> Optional[str]:
    """Bound a scalar diagnostic value for safe module output."""
    value = _scalar_text(value)
    if value is None:
        return None
    if len(value) <= _MAX_ERROR_FIELD_LENGTH:
        return value
    omitted = len(value) - _MAX_ERROR_FIELD_LENGTH
    return f"{value[:_MAX_ERROR_FIELD_LENGTH]}... [{omitted} characters omitted]"


def _api_error_details(error: Exception) -> Optional[dict[str, Any]]:
    """Extract stable diagnostics from minio-py exception types."""
    details: dict[str, Any] = {"type": type(error).__name__}
    if isinstance(error, MinioAdminException):
        body = str(getattr(error, "_body", ""))
        details["status"] = _status_code(getattr(error, "_code", None))
        if len(body) > _MAX_ERROR_BODY_LENGTH:
            details.update({"body_omitted": True, "body_length": len(body)})
        else:
            try:
                parsed = json.loads(body)
            except (TypeError, ValueError, RecursionError):
                details.update({"body_omitted": True, "body_length": len(body)})
            else:
                if isinstance(parsed, dict):
                    details["code"] = _scalar_text(parsed.get("Code") or parsed.get("code"))
                    details["message"] = _scalar_text(parsed.get("Message") or parsed.get("message"))
                if not details.get("code") and not details.get("message"):
                    details.update({"body_omitted": True, "body_length": len(body)})
    elif isinstance(error, S3Error):
        details.update(
            {
                "status": _status_code(getattr(getattr(error, "response", None), "status", None)),
                "code": _scalar_text(getattr(error, "code", None)),
                "message": _scalar_text(getattr(error, "message", None)),
                "resource": _scalar_text(getattr(error, "resource", None)),
                "request_id": _scalar_text(getattr(error, "request_id", None)),
            }
        )
    elif isinstance(error, InvalidResponseError):
        body = getattr(error, "_body", None)
        details.update(
            {
                "status": _status_code(getattr(error, "_code", None)),
                "content_type": getattr(error, "_content_type", None),
            }
        )
        if body is not None:
            details.update({"body_omitted": True, "body_length": len(body) if isinstance(body, str) else None})
    elif isinstance(error, ServerError):
        details["status"] = _status_code(getattr(error, "status_code", None))
    else:
        return None
    return {key: value for key, value in details.items() if value is not None}


def _redact_api_error(details: dict[str, Any], sensitive_values: list[Any]) -> dict[str, Any]:
    """Redact server-controlled diagnostic fields without changing metadata."""
    redacted = {}
    for key, value in details.items():
        if key in ("type", "status") or not isinstance(value, str):
            redacted[key] = value
        else:
            redacted[key] = _diagnostic_text(_redact(value, sensitive_values))
    return redacted


def _api_error_message(details: dict[str, Any]) -> str:
    """Format concise human-readable text from structured API diagnostics."""
    labels = (
        ("status", "status"),
        ("code", "code"),
        ("message", "message"),
        ("resource", "resource"),
        ("request_id", "request ID"),
        ("content_type", "content type"),
    )
    values = [f"{label}: {details[key]}" for key, label in labels if details.get(key) not in (None, "")]
    if details.get("body_omitted"):
        values.append(f"response body omitted ({details.get('body_length', 'unknown')} characters)")
    return f"{details['type']}: " + ", ".join(values)


def fail_from_exception(module: Any, error: Exception) -> None:
    """Return an API failure without exposing request credentials."""
    params = module.params if isinstance(module.params, dict) else {}
    sensitive_values = _sensitive_values(params) + list(getattr(module, "no_log_values", ()))
    details = _api_error_details(error)
    if details:
        details = _redact_api_error(details, sensitive_values)
        message = _api_error_message(details)
    else:
        message = _diagnostic_text(_redact(str(error), sensitive_values)) or type(error).__name__
    result = {"msg": f"MinIO AIStor API request failed: {message}"}
    if details:
        result["api_error"] = details
    module.fail_json(**result)


def is_not_found(error: Exception) -> bool:
    """Return whether an admin exception represents HTTP 404."""
    return isinstance(error, MinioAdminException) and getattr(error, "_code", None) == "404"
