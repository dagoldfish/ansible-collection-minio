# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared MinIO Admin client construction and response helpers."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import traceback
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Optional

from ansible.module_utils.basic import missing_required_lib

__all__ = ("PeerInfo", "PeerSite", "SiteReplicationStatusOptions")

MINIO_IMP_ERR = None
try:
    from minio import Minio, MinioAdmin
    from minio.credentials import StaticProvider
    from minio.crypto import decrypt, encrypt
    from minio.error import MinioAdminException
    from minio.minioadmin import PeerInfo, PeerSite, SiteReplicationStatusOptions
except ImportError:
    MINIO_IMP_ERR = traceback.format_exc()
    Minio = None  # type: ignore[assignment,misc]
    MinioAdmin = None  # type: ignore[assignment,misc]
    StaticProvider = None  # type: ignore[assignment,misc]
    decrypt = None  # type: ignore[assignment,misc]
    encrypt = None  # type: ignore[assignment,misc]
    MinioAdminException = Exception  # type: ignore[assignment,misc]
    PeerSite = None  # type: ignore[assignment,misc]
    PeerInfo = None  # type: ignore[assignment,misc]
    SiteReplicationStatusOptions = None  # type: ignore[assignment,misc]


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


def admin_client(module: Any) -> Any:
    """Build the official SDK admin client from module parameters."""
    if MINIO_IMP_ERR:
        module.fail_json(
            msg=missing_required_lib("minio", url="https://github.com/minio/minio-py"),
            exception=MINIO_IMP_ERR,
        )
    auth = module.params["auth"]
    endpoint = auth["endpoint"].removeprefix("https://").removeprefix("http://").rstrip("/")
    return MinioAdmin(
        endpoint=endpoint,
        credentials=StaticProvider(auth["access_key"], auth["secret_key"]),
        region=auth["region"],
        secure=auth["secure"],
        cert_check=auth["validate_certs"],
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
    )


def parse_json(value: Any, default: Any = None) -> Any:
    """Decode SDK JSON strings while accepting already-decoded test values."""
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


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


def fail_from_exception(module: Any, error: Exception) -> None:
    """Return an API failure without exposing request credentials."""
    message = str(error)
    params = module.params if isinstance(module.params, dict) else {}
    auth = params.get("auth", {})
    sensitive_values = [auth.get("access_key"), auth.get("secret_key")]
    sensitive_values.extend(params.get(field) for field in ("secret_key", "lookup_bind_password"))
    for value in sensitive_values:
        if value:
            message = message.replace(str(value), "***")
    module.fail_json(msg=f"MinIO AIStor API request failed: {message}")


def is_not_found(error: Exception) -> bool:
    """Return whether an admin exception represents HTTP 404."""
    return isinstance(error, MinioAdminException) and getattr(error, "_code", None) == "404"
