# Copyright: (c) 2026, Geoffrey Burger (@dagoldfish)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Targeted webhook configuration transport and MinIO KVS handling."""

from __future__ import annotations

import json
import re

from ansible_collections.dagoldfish.minio.plugins.module_utils.minio_admin import (
    MinioAdminException,
    _AdminCommand,
    _BufferedAdminResponse,
    decrypt,
    encrypt,
)

# These are configuration keys, not shell arguments. MinIO finds key boundaries
# before stripping quotes and does not interpret backslash escapes.
WIRE_FIELDS = (
    "enable", "endpoint", "auth_token", "client_cert", "client_key", "proxy",
    "queue_dir", "queue_size", "batch_size", "batch_max_size", "max_retry",
    "retry_interval", "http_timeout", "http_encoding", "tls_skip_verification", "comment",
)
# Match the same key vocabulary used when validating writes. Arbitrary
# assignments such as team=ops inside a comment are part of the value.
_KEY = re.compile(r"(?:^|\s)(" + "|".join(re.escape(field) for field in WIRE_FIELDS) + r")=")


def target_key(kind, name):
    """An explicit default target must never select the entire subsystem."""
    if kind not in ("logger", "audit") or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Webhook name must contain only letters, digits, underscores, or hyphens")
    return kind + "_webhook:" + name


def config_text(config):
    """Serialize without shell escaping, matching MinIO's SanitizeValue."""
    values = []
    for key, value in config.items():
        if key not in WIRE_FIELDS:
            raise ValueError("Unsupported webhook configuration field")
        value = str(value)
        if any(char in value for char in ("\n", "\r", "\x00")) or any(field + "=" in value for field in WIRE_FIELDS):
            raise ValueError("Webhook field %s contains a value that MinIO KVS cannot safely represent" % key)
        # The server strips one double-quote layer followed by one single-quote
        # layer. Supplying both preserves literal quotes and backslashes too.
        values.append(key + '=\"\'' + value + '\'\"')
    return " ".join(values)


def parse_config(text, key):
    """Read exactly one target, ignoring environment-variable comment lines."""
    subsystem, name = key.split(":", 1)
    accepted = {key}
    if name == "_":
        accepted.update((subsystem, subsystem + ":"))
    result = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if parts[0] not in accepted:
            continue
        if result is not None:
            raise ValueError("Duplicate webhook target in configuration response")
        result = {}
        remainder = parts[1] if len(parts) > 1 else ""
        matches = list(_KEY.finditer(remainder))
        if remainder and (not matches or matches[0].start() != 0):
            raise ValueError("Malformed webhook configuration response")
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(remainder)
            value = remainder[match.end():end].strip()
            # MinIO's KVS writer wraps whitespace-containing values in double
            # quotes, without escaping embedded quotes or backslashes.
            if len(value) >= 2 and value[0] == value[-1] == '"' and any(c.isspace() for c in value):
                value = value[1:-1]
            field = match.group(1)
            if field in result:
                raise ValueError("Duplicate field in webhook configuration response")
            result[field] = value
    return result


def _missing_target(error):
    if not isinstance(error, MinioAdminException):
        return False
    try:
        body = json.loads(getattr(error, "_body", ""))
    except (ValueError, TypeError):
        return False
    if not isinstance(body, dict):
        return False
    code = body.get("Code", body.get("code", ""))
    message = body.get("Message", body.get("message", ""))
    return code == "XMinioAdminNoSuchConfigTarget" or (
        code == "XMinioAdminConfigBadJSON" and isinstance(message, str)
        and re.fullmatch(r"there is no target `[^`]+` for subsystem `(?:logger|audit)_webhook`", message) is not None
    )


def read_config(client, key):
    """Read encrypted, redacted configuration through the signed SDK transport."""
    response = None
    try:
        response = client._url_open(
            method="GET", command=_AdminCommand("get-config-kv"),
            query_params={"key": key, "subSys": ""}, preload_content=True,
        )
        secret = client._provider.retrieve().secret_key
        text = decrypt(_BufferedAdminResponse(response.data), secret).decode()
        result = parse_config(text, key)
        if result is None and text.strip():
            raise ValueError("Requested webhook target missing from configuration response")
        return result
    except MinioAdminException as error:
        if _missing_target(error):
            return None
        raise
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def validate_config_fields(client, key, config):
    """Reject unsupported fields before MinIO can silently discard them."""
    response = None
    try:
        response = client._url_open(
            method="GET", command=_AdminCommand("help-config-kv"),
            query_params={"subSys": key.split(":", 1)[0], "key": ""}, preload_content=True,
        )
        help_data = json.loads(response.data)
        if not isinstance(help_data, dict) or not isinstance(help_data.get("keysHelp"), list):
            raise ValueError("Malformed webhook configuration help response")
        supported = {item["key"] for item in help_data["keysHelp"]
                     if isinstance(item, dict) and isinstance(item.get("key"), str)}
        if not supported:
            raise ValueError("Empty webhook configuration help response")
        # Enable is a common implicit config key, omitted from subsystem help.
        supported.add("enable")
        unsupported = set(config) - supported
        if unsupported:
            raise ValueError("Webhook settings unsupported by this server: " + ", ".join(sorted(unsupported)))
        for field, value in config.items():
            if any(other + "=" in str(value) for other in supported):
                raise ValueError("Webhook field %s contains a value that MinIO KVS cannot safely represent" % field)
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def write_config(client, key, config=None):
    """Set/reset one target and return whether a restart is required."""
    text = key if config is None else key + " " + config_text(config)
    response = None
    try:
        response = client._url_open(
            method="DELETE" if config is None else "PUT",
            command=_AdminCommand("del-config-kv" if config is None else "set-config-kv"),
            body=encrypt(text.encode(), client._provider.retrieve().secret_key),
            preload_content=True,
        )
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        return headers.get("x-minio-config-applied") != "true"
    finally:
        if response is not None:
            response.close()
            response.release_conn()
