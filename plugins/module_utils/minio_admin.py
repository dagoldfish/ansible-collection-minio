# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared MinIO Admin client construction and response helpers."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import traceback
from typing import Any

from ansible.module_utils.basic import missing_required_lib

__all__ = ("PeerInfo", "PeerSite", "SiteReplicationStatusOptions")

MINIO_IMP_ERR = None
try:
    from minio import MinioAdmin
    from minio.credentials import StaticProvider
    from minio.error import MinioAdminException
    from minio.minioadmin import PeerInfo, PeerSite, SiteReplicationStatusOptions
except ImportError:
    MINIO_IMP_ERR = traceback.format_exc()
    MinioAdmin = None  # type: ignore[assignment,misc]
    StaticProvider = None  # type: ignore[assignment,misc]
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


def parse_json(value: Any, default: Any = None) -> Any:
    """Decode SDK JSON strings while accepting already-decoded test values."""
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def canonical_json(value: Any) -> str:
    """Return a stable representation suitable for policy comparisons."""
    if isinstance(value, str):
        value = json.loads(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fail_from_exception(module: Any, error: Exception) -> None:
    """Return an API failure without exposing request credentials."""
    message = str(error)
    auth = module.params.get("auth", {}) if isinstance(module.params, dict) else {}
    for field in ("access_key", "secret_key"):
        value = auth.get(field)
        if value:
            message = message.replace(str(value), "***")
    module.fail_json(msg=f"MinIO AIStor API request failed: {message}")


def is_not_found(error: Exception) -> bool:
    """Return whether an admin exception represents HTTP 404."""
    return isinstance(error, MinioAdminException) and getattr(error, "_code", None) == "404"
