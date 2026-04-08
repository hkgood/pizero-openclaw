"""
OpenClaw Gateway WebSocket client.

Current verified flow for 3.31+:
- wait for `connect.challenge`
- send one canonical `connect` request with shared auth and device identity
- first connection may return `NOT_PAIRED` and create a pending request
- once approved, reconnect and stream replies through `chat.send`
"""
import base64
import hashlib
import json
import logging
import os
import platform
import time
import uuid as uuid_module
from typing import Generator

import config

try:
    import websocket
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError:
    websocket = None
    serialization = None
    Ed25519PrivateKey = None
    Ed25519PublicKey = None

log = logging.getLogger("openclaw")


def _expand_path(path: str) -> str:
    return os.path.expanduser(path)


def _load_json_file(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except Exception as exc:
        log.warning("Failed to load JSON from %s: %s", path, exc)
        return None


def _write_json_file(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=2)


def _split_scopes(raw_value: str) -> list[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _get_origin(base_url: str) -> str:
    if base_url.startswith("https://"):
        return f"https://{base_url[8:]}"
    if base_url.startswith("http://"):
        return f"http://{base_url[7:]}"
    return f"http://{base_url}"


def _get_ws_url(base_url: str) -> str:
    if base_url.startswith("http://"):
        return "ws://" + base_url[7:]
    if base_url.startswith("https://"):
        return "wss://" + base_url[8:]
    return f"ws://{base_url}"


def _identity_file_path() -> str:
    return _expand_path(config.OPENCLAW_IDENTITY_FILE)


def _device_token_file_path() -> str:
    return _expand_path(config.OPENCLAW_DEVICE_TOKEN_FILE)


def _pairing_state_file_path() -> str:
    return _expand_path(config.OPENCLAW_PAIRING_STATE_FILE)


def _device_auth_state() -> dict:
    return _load_json_file(_device_token_file_path()) or {}


def _stored_device_token(role: str) -> str:
    state = _device_auth_state()
    tokens = state.get("tokens", {})
    role_entry = tokens.get(role, {})
    token = role_entry.get("token", "")
    return token if isinstance(token, str) else ""


def _save_device_token(identity: dict | None, hello_auth: dict) -> None:
    device_token = hello_auth.get("deviceToken")
    if not isinstance(device_token, str) or not device_token:
        return

    role = hello_auth.get("role") or config.OPENCLAW_ROLE
    scopes = hello_auth.get("scopes")
    if not isinstance(scopes, list):
        scopes = _split_scopes(config.OPENCLAW_SCOPES)

    payload = {
        "version": 1,
        "deviceId": identity.get("deviceId") if identity else "",
        "updatedAtMs": int(time.time() * 1000),
        "tokens": {
            role: {
                "token": device_token,
                "role": role,
                "scopes": scopes,
                "updatedAtMs": int(time.time() * 1000),
            }
        },
    }
    _write_json_file(_device_token_file_path(), payload)


def _save_pairing_state(identity: dict | None, error: dict) -> None:
    details = error.get("details") if isinstance(error.get("details"), dict) else {}
    payload = {
        "version": 1,
        "status": "pending",
        "updatedAtMs": int(time.time() * 1000),
        "deviceId": identity.get("deviceId") if identity else "",
        "role": config.OPENCLAW_ROLE,
        "scopes": _split_scopes(config.OPENCLAW_SCOPES),
        "requestId": details.get("requestId", ""),
        "errorCode": error.get("code", ""),
        "errorMessage": error.get("message", ""),
        "details": details,
    }
    _write_json_file(_pairing_state_file_path(), payload)


def _clear_pairing_state() -> None:
    path = _pairing_state_file_path()
    if os.path.exists(path):
        os.remove(path)


def _require_crypto() -> None:
    if Ed25519PrivateKey is None or serialization is None:
        raise RuntimeError(
            "cryptography not installed. Run: pip3 install cryptography"
        )


def _identity_is_ed25519(private_key_pem: str) -> bool:
    _require_crypto()
    try:
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None,
        )
    except Exception:
        return False
    return isinstance(private_key, Ed25519PrivateKey)


def _load_or_create_identity() -> dict:
    path = _identity_file_path()
    identity = _load_json_file(path)
    if identity:
        device_id = identity.get("deviceId")
        private_key_pem = identity.get("privateKeyPem")
        public_key_pem = identity.get("publicKeyPem")
        if (
            isinstance(device_id, str)
            and private_key_pem
            and public_key_pem
            and _identity_is_ed25519(private_key_pem)
        ):
            return identity
        if isinstance(private_key_pem, str) and private_key_pem:
            legacy_backup = f"{path}.legacy-{int(time.time() * 1000)}"
            os.replace(path, legacy_backup)
            log.warning(
                "Existing OpenClaw identity is not Ed25519. Backed it up to %s",
                legacy_backup,
            )

    _require_crypto()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    device_id = hashlib.sha256(public_key_raw).hexdigest()
    payload = {
        "version": 1,
        "deviceId": device_id,
        "createdAtMs": int(time.time() * 1000),
        "publicKeyPem": public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8"),
        "privateKeyPem": private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8"),
        "publicKeyRawBase64": base64.b64encode(public_key_raw).decode("utf-8"),
    }
    _write_json_file(path, payload)
    log.info("Created OpenClaw device identity at %s", path)
    return payload


def _client_descriptor() -> dict:
    return {
        "id": config.OPENCLAW_CLIENT_ID,
        "mode": config.OPENCLAW_CLIENT_MODE,
        "version": config.OPENCLAW_CLIENT_VERSION,
        "platform": platform.system().lower() or "linux",
        "deviceFamily": config.OPENCLAW_DEVICE_FAMILY,
    }


def _build_connect_auth() -> dict:
    auth: dict[str, str] = {}
    if config.OPENCLAW_TOKEN:
        auth["token"] = config.OPENCLAW_TOKEN
    if config.OPENCLAW_PASSWORD:
        auth["password"] = config.OPENCLAW_PASSWORD

    stored_device_token = _stored_device_token(config.OPENCLAW_ROLE)
    if stored_device_token and not auth:
        auth["deviceToken"] = stored_device_token

    return auth


def _signature_token(auth: dict) -> str | None:
    token = auth.get("token") or auth.get("deviceToken")
    return token if isinstance(token, str) and token else None


def _build_device_auth_payload_v3(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    auth_token: str | None,
    nonce: str,
    platform_name: str,
    device_family: str,
) -> str:
    scopes_value = ",".join(scopes)
    token_value = auth_token or ""
    return (
        f"v3|{device_id}|{client_id}|{client_mode}|{role}|{scopes_value}|"
        f"{signed_at_ms}|{token_value}|{nonce}|{platform_name}|{device_family}"
    )


def _device_payload(identity: dict | None, auth: dict, nonce: str, timestamp: int) -> dict | None:
    if not config.OPENCLAW_USE_DEVICE_IDENTITY or not identity:
        return None

    _require_crypto()

    client = _client_descriptor()
    scopes = _split_scopes(config.OPENCLAW_SCOPES)
    signed_payload = _build_device_auth_payload_v3(
        device_id=identity["deviceId"],
        client_id=client["id"],
        client_mode=client["mode"],
        role=config.OPENCLAW_ROLE,
        scopes=scopes,
        signed_at_ms=int(timestamp),
        auth_token=_signature_token(auth),
        nonce=nonce,
        platform_name=client["platform"],
        device_family=client["deviceFamily"],
    )

    private_key = serialization.load_pem_private_key(
        identity["privateKeyPem"].encode("utf-8"),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise RuntimeError("OpenClaw identity must use an Ed25519 private key")

    signature = private_key.sign(signed_payload.encode("utf-8"))
    payload = {
        "id": identity["deviceId"],
        "publicKey": identity["publicKeyPem"],
        "signature": base64.b64encode(signature).decode("utf-8"),
        "signedAt": int(timestamp),
        "nonce": nonce,
    }
    if "deviceToken" in auth:
        payload["deviceToken"] = auth["deviceToken"]
    return payload


def _connect_request(connect_id: str, nonce: str, timestamp: int, identity: dict | None) -> dict:
    auth = _build_connect_auth()
    params = {
        "minProtocol": config.OPENCLAW_PROTOCOL_VERSION,
        "maxProtocol": config.OPENCLAW_PROTOCOL_VERSION,
        "client": _client_descriptor(),
        "role": config.OPENCLAW_ROLE,
        "scopes": _split_scopes(config.OPENCLAW_SCOPES),
        "locale": config.OPENCLAW_LOCALE,
        "userAgent": config.OPENCLAW_USER_AGENT,
        "caps": [],
        "commands": [],
        "permissions": {},
    }
    if auth:
        params["auth"] = auth
    device = _device_payload(identity, auth, nonce, timestamp)
    if device:
        params["device"] = device
    return {
        "type": "req",
        "method": "connect",
        "id": connect_id,
        "params": params,
    }


def _decode_json_messages(raw_frame: str) -> list[dict]:
    raw_frame = raw_frame.strip()
    if not raw_frame:
        return []
    try:
        return [json.loads(raw_frame)]
    except json.JSONDecodeError:
        messages = []
        for line in raw_frame.splitlines():
            line = line.strip()
            if not line:
                continue
            messages.append(json.loads(line))
        return messages


def _read_json_messages(ws) -> list[dict]:
    raw = ws.recv()
    if raw is None:
        raise RuntimeError("Gateway closed the WebSocket before sending a response")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return _decode_json_messages(raw)


def _raise_connect_error(error: dict, identity: dict | None) -> None:
    code = error.get("code", "UNKNOWN")
    message = error.get("message", "OpenClaw connect failed")
    details = error.get("details")

    if code == "NOT_PAIRED":
        _save_pairing_state(identity, error)
        request_id = details.get("requestId") if isinstance(details, dict) else ""
        request_id_hint = f" requestId={request_id}" if request_id else ""
        raise RuntimeError(
            "OpenClaw device is pending approval."
            f"{request_id_hint} "
            f"Pairing details saved to {_pairing_state_file_path()}."
        )

    raise RuntimeError(
        f"Gateway connect failed: {code}: {message} details={details or error}"
    )


def _perform_handshake(ws, identity: dict | None) -> None:
    connect_id = str(uuid_module.uuid4())
    challenge_payload = None

    while challenge_payload is None:
        for frame in _read_json_messages(ws):
            if frame.get("type") == "event" and frame.get("event") == "connect.challenge":
                challenge_payload = frame.get("payload", {})
                break
            if frame.get("error"):
                _raise_connect_error(frame["error"], identity)

    nonce = challenge_payload.get("nonce")
    timestamp = challenge_payload.get("ts")
    if not nonce or timestamp is None:
        raise RuntimeError(f"Gateway challenge missing nonce/ts: {challenge_payload}")

    ws.send(json.dumps(_connect_request(connect_id, nonce, int(timestamp), identity)))
    log.info("Sent OpenClaw connect request")

    while True:
        for frame in _read_json_messages(ws):
            if frame.get("type") == "res" and frame.get("id") == connect_id:
                if frame.get("ok") is False or frame.get("error"):
                    _raise_connect_error(frame.get("error", {}), identity)

                payload = frame.get("payload", {})
                hello_auth = payload.get("auth", {})
                if isinstance(hello_auth, dict):
                    _save_device_token(identity, hello_auth)
                _clear_pairing_state()
                log.info("OpenClaw connect established")
                return

            if frame.get("error"):
                _raise_connect_error(frame["error"], identity)


def _raise_rpc_error(error: dict) -> None:
    code = error.get("code", "UNKNOWN")
    message = error.get("message", "OpenClaw request failed")
    details = error.get("details")

    if code == "INVALID_REQUEST" and "missing scope" in str(message):
        raise RuntimeError(
            "OpenClaw accepted the connection but did not grant operator write scope. "
            "Make sure the client is using shared auth plus device identity, and the "
            "device has been approved on the gateway."
        )

    raise RuntimeError(
        f"OpenClaw request failed: {code}: {message} details={details or error}"
    )


def _diff_text(already_emitted: str, candidate: str) -> str:
    if not candidate:
        return ""
    if not already_emitted:
        return candidate
    if candidate.startswith(already_emitted):
        return candidate[len(already_emitted):]
    return ""


def _extract_chat_message_text(message: dict) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _extract_agent_delta(payload: dict) -> str:
    if payload.get("stream") != "assistant":
        return ""
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return ""
    delta = data.get("delta")
    return delta if isinstance(delta, str) else ""


def stream_response(
    user_text: str,
    history: list[dict] | None = None,
) -> Generator[str, None, None]:
    """Send user_text to OpenClaw Gateway via WebSocket with streaming."""
    del history

    if websocket is None:
        raise RuntimeError(
            "websocket-client not installed. Run: pip3 install websocket-client"
        )

    identity = _load_or_create_identity() if config.OPENCLAW_USE_DEVICE_IDENTITY else None
    if not identity and not (config.OPENCLAW_TOKEN or config.OPENCLAW_PASSWORD):
        stored_device_token = _stored_device_token(config.OPENCLAW_ROLE)
        if not stored_device_token:
            raise RuntimeError(
                "No shared OpenClaw auth or stored device token is available. "
                "Configure OPENCLAW_PASSWORD / OPENCLAW_TOKEN, or enable device identity."
            )

    base_url = config.OPENCLAW_BASE_URL.rstrip("/")
    origin = _get_origin(base_url)
    ws_url = _get_ws_url(base_url)
    headers = []
    if config.OPENCLAW_TOKEN:
        headers.append(f"Authorization: Bearer {config.OPENCLAW_TOKEN}")

    connect_timeout_sec = max(config.OPENCLAW_CONNECT_TIMEOUT_MS / 1000.0, 1.0)
    event_timeout_sec = max(config.OPENCLAW_STREAM_EVENT_TIMEOUT_MS / 1000.0, 1.0)
    stream_timeout_sec = max(config.OPENCLAW_STREAM_TIMEOUT_MS / 1000.0, event_timeout_sec)

    log.info("Connecting to %s", ws_url)
    try:
        ws = websocket.create_connection(
            ws_url,
            header=headers,
            http_origin=origin,
            timeout=connect_timeout_sec,
        )
    except Exception as exc:
        raise RuntimeError(f"Cannot connect to OpenClaw at {ws_url}: {exc}") from exc

    try:
        _perform_handshake(ws, identity)

        request_id = str(uuid_module.uuid4())
        run_id = str(uuid_module.uuid4())
        ws.send(
            json.dumps(
                {
                    "type": "req",
                    "method": "chat.send",
                    "id": request_id,
                    "params": {
                        "sessionKey": config.OPENCLAW_SESSION_KEY,
                        "message": user_text,
                        "idempotencyKey": run_id,
                    },
                }
            )
        )
        log.info("Sent OpenClaw chat.send request")

        emitted_text = ""
        request_acked = False
        deadline = time.monotonic() + stream_timeout_sec

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if emitted_text:
                    return
                raise RuntimeError("Timed out while waiting for OpenClaw response stream")

            ws.settimeout(min(event_timeout_sec, remaining))
            try:
                messages = _read_json_messages(ws)
            except websocket.WebSocketTimeoutException:
                if emitted_text:
                    return
                continue

            for message in messages:
                if message.get("type") == "res" and message.get("id") == request_id:
                    if message.get("ok") is False or message.get("error"):
                        _raise_rpc_error(message.get("error", {}))
                    request_acked = True
                    continue

                if message.get("error"):
                    _raise_rpc_error(message["error"])

                if message.get("type") != "event":
                    continue

                payload = message.get("payload", {})
                if not isinstance(payload, dict):
                    continue
                if payload.get("runId") != run_id:
                    continue

                event_name = message.get("event")
                if event_name == "agent":
                    delta = _extract_agent_delta(payload)
                    if delta:
                        emitted_text += delta
                        yield delta
                        continue

                    if payload.get("stream") == "lifecycle" and payload.get("phase") == "end":
                        return

                if event_name == "chat":
                    message_text = _extract_chat_message_text(payload.get("message", {}))
                    delta = _diff_text(emitted_text, message_text)
                    if delta:
                        emitted_text += delta
                        yield delta
                    if payload.get("state") == "final":
                        return

            if request_acked and emitted_text:
                deadline = time.monotonic() + event_timeout_sec
    finally:
        ws.close()
