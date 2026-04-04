"""
OpenClaw Gateway WebSocket client with full challenge-response support.
Uses ECDSA P-256 signing for device authentication.
"""
import hashlib
import json
import logging
import os
import uuid as uuid_module
from typing import Generator

import config

try:
    import websocket
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
except ImportError:
    websocket = None
    hashes = None
    serialization = None
    ec = None
    default_backend = None

log = logging.getLogger("openclaw")

IDENTITY_FILE = os.path.expanduser("~/.openclaw/identity/device.json")


def _load_identity() -> dict | None:
    """Load device identity from file."""
    if os.path.exists(IDENTITY_FILE):
        try:
            with open(IDENTITY_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            log.warning("Failed to load identity from %s: %s", IDENTITY_FILE, e)
    return None


def _sign_nonce(nonce: str, timestamp: str, private_key_pem: str) -> str:
    """
    Sign the challenge nonce using ECDSA P-256.
    Returns base64-encoded signature.
    """
    if hashes is None:
        raise RuntimeError("cryptography not installed. Run: pip3 install cryptography")

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=None,
        backend=default_backend()
    )

    message = f"{nonce}:{timestamp}".encode()
    der_signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    
    # Decode DER signature to raw r||s format
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    r, s = decode_dss_signature(der_signature)
    
    # Pack r and s as 32-byte big-endian integers
    import struct
    r_bytes = r.to_bytes(32, 'big')
    s_bytes = s.to_bytes(32, 'big')
    raw_signature = r_bytes + s_bytes
    
    import base64
    return base64.b64encode(raw_signature).decode()


def _get_origin(base_url: str) -> str:
    """Extract origin from base URL."""
    if base_url.startswith("https://"):
        return f"https://{base_url[8:]}"
    elif base_url.startswith("http://"):
        return f"http://{base_url[7:]}"
    return f"http://{base_url}"


def stream_response(
    user_text: str,
    history: list[dict] | None = None,
) -> Generator[str, None, None]:
    """
    Send user_text to OpenClaw Gateway via WebSocket with streaming.

    Yields text deltas as they arrive.
    """
    if websocket is None:
        raise RuntimeError(
            "websocket-client not installed. Run: pip3 install websocket-client"
        )

    token = config.OPENCLAW_TOKEN
    base_url = config.OPENCLAW_BASE_URL.rstrip("/")
    origin = _get_origin(base_url)

    if base_url.startswith("http://"):
        ws_url = "ws://" + base_url[7:]
    elif base_url.startswith("https://"):
        ws_url = "wss://" + base_url[8:]
    else:
        ws_url = f"ws://{base_url}"

    identity = _load_identity()
    if not identity:
        raise RuntimeError(
            f"No device identity found at {IDENTITY_FILE}. "
            "Generate one with the setup script."
        )

    device_id = identity.get("deviceId", "")
    private_key_pem = identity.get("privateKeyPem", "")

    if not device_id or not private_key_pem:
        raise RuntimeError("Identity file missing deviceId or privateKeyPem")

    log.info("Connecting to %s (device_id=%s)", ws_url, device_id[:8])

    try:
        ws = websocket.create_connection(
            ws_url,
            header=[
                f"Authorization: Bearer {token}",
            ],
            http_origin=origin,
            timeout=30,
        )
    except Exception as e:
        raise RuntimeError(f"Cannot connect to OpenClaw at {ws_url}: {e}") from e

    try:
        # Step 1: Send connect request
        connect_id = str(uuid_module.uuid4())
        connect_msg = {
            "type": "req",
            "method": "connect",
            "id": connect_id,
            "params": {
                "minProtocol": 1,
                "maxProtocol": 32,
                "client": {
                    "id": "cli",
                    "mode": "cli",
                    "version": "1.0.0",
                    "platform": "linux",
                },
            },
        }
        ws.send(json.dumps(connect_msg))
        log.info("Sent connect request")

        # Step 2: Read connect response (challenge)
        raw_resp = ws.recv()
        log.info("Connect response: %s", str(raw_resp)[:300])

        resp = json.loads(raw_resp)
        evt_type = resp.get("event", "") or resp.get("type", "")

        if evt_type == "connect.challenge" or resp.get("type") == "event":
            payload = resp.get("payload", {})
            nonce = payload.get("nonce")
            ts = payload.get("ts")
            if nonce and ts:
                sig = _sign_nonce(nonce, str(ts), private_key_pem)
                challenge_resp = {
                    "type": "req",
                    "method": "connect.challenge",
                    "id": str(uuid_module.uuid4()),
                    "params": {
                        "nonce": nonce,
                        "timestamp": ts,
                        "deviceId": device_id,
                        "signature": sig,
                    },
                }
                ws.send(json.dumps(challenge_resp))
                log.info("Sent challenge response")

                challenge_result = ws.recv()
                log.info("Challenge result: %s", str(challenge_result)[:300])
                result_data = json.loads(challenge_result)

                if result_data.get("error"):
                    err = result_data["error"]
                    raise RuntimeError(f"Gateway challenge failed: {err}")

        elif resp.get("error"):
            err = resp.get("error")
            raise RuntimeError(f"Gateway connect error: {err}")

        # Step 3: Send prompt request
        prompt_id = str(uuid_module.uuid4())

        if history:
            messages = [
                {"type": "message", "role": m["role"], "content": m["content"]}
                for m in history
            ]
        else:
            messages = []

        messages.append({"type": "message", "role": "user", "content": user_text})

        prompt_msg = {
            "type": "req",
            "method": "prompt",
            "id": prompt_id,
            "params": {
                "model": "openclaw",
                "input": messages,
                "stream": True,
            },
        }
        ws.send(json.dumps(prompt_msg))
        log.info("Sent prompt request, waiting for response stream...")

        # Step 4: Read streaming response
        buffer = ""
        while True:
            frame = ws.recv()
            if frame is None:
                break

            buffer += frame

            while "\n" in buffer:
                line, _, buffer = buffer.partition("\n")
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "error" or data.get("error"):
                    err = data.get("error", data.get("message", "Unknown error"))
                    raise RuntimeError(f"Gateway error: {err}")

                if msg_type in ("response.done", "response.completed", "done", "stop"):
                    log.info("Stream completed")
                    return

                text = _extract_text(data)
                if text:
                    yield text

    finally:
        ws.close()


def _extract_text(data: dict) -> str | None:
    """Extract text from WebSocket data frame."""
    msg_type = data.get("type", "")

    if msg_type == "response.output_text.delta":
        delta = data.get("delta")
        if isinstance(delta, str):
            return delta
        if isinstance(delta, dict):
            return delta.get("text")

    if msg_type == "content_block_delta":
        delta = data.get("delta", {})
        return delta.get("text")

    if msg_type == "response.content_part.delta":
        part = data.get("part", {})
        if isinstance(part, dict):
            return part.get("text")

    if msg_type == "text_delta":
        return data.get("delta")

    params = data.get("params", {})
    if isinstance(params, dict):
        delta = params.get("delta")
        if isinstance(delta, str):
            return delta

    return None
