"""
OpenClaw Gateway WebSocket client with full pairing and challenge-response support.
"""
import hashlib
import hmac
import json
import logging
import time
import uuid as uuid_module
from typing import Generator

try:
    import websocket
except ImportError:
    websocket = None

import config

log = logging.getLogger("openclaw")


def _generate_device_id() -> str:
    """
    Generate a stable device ID. First checks for a cached ID in
    ~/.local/state/pizero-openclaw/device-id, then falls back to
    machine characteristics and caches the result.
    """
    import os
    state_dir = os.path.expanduser("~/.local/state/pizero-openclaw")
    id_file = os.path.join(state_dir, "device-id")
    
    # Try to load cached device ID
    try:
        if os.path.exists(id_file):
            with open(id_file, "r") as f:
                cached = f.read().strip()
            if cached:
                return cached
    except Exception:
        pass
    
    # Derive device ID from machine characteristics
    machine_id = None
    for path in ["/etc/machine-id", "/sys/class/dmi/id/product_uuid"]:
        try:
            with open(path, "r") as f:
                machine_id = f.read().strip()
                if machine_id:
                    break
        except Exception:
            pass
    
    if not machine_id:
        # Last resort: use network MAC address
        mac = str(uuid_module.getnode())
        machine_id = mac
    
    device_id = hashlib.sha256(machine_id.encode()).hexdigest()[:32]
    
    # Cache it for next time
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(id_file, "w") as f:
            f.write(device_id)
    except Exception:
        pass
    
    return device_id


def _sign_nonce(nonce: str, timestamp: str, device_id: str, token: str) -> str:
    """Sign the challenge nonce using HMAC-SHA256."""
    msg = f"{nonce}:{timestamp}:{device_id}"
    sig = hmac.new(
        token.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()
    return sig


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

    # Convert HTTP URL to WebSocket URL
    if base_url.startswith("http://"):
        ws_url = "ws://" + base_url[7:]
    elif base_url.startswith("https://"):
        ws_url = "wss://" + base_url[8:]
    else:
        ws_url = f"ws://{base_url}"

    device_id = _generate_device_id()
    request_id = str(uuid_module.uuid4())

    log.info("Connecting to %s (device_id=%s)", ws_url, device_id[:8])

    try:
        ws = websocket.create_connection(
            ws_url,
            header=[f"Authorization: Bearer {token}"],
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
                "host": base_url.replace("http://", "").replace("https://", ""),
                "deviceId": device_id,
            },
        }
        ws.send(json.dumps(connect_msg))
        log.info("Sent connect request")

        # Step 2: Read connect response (may be challenge or error)
        raw_resp = ws.recv()
        log.info("Connect response: %s", str(raw_resp)[:300])

        resp = json.loads(raw_resp)
        evt_type = resp.get("event", "") or resp.get("type", "")

        # If challenge, respond with signed nonce
        if evt_type == "connect.challenge" or resp.get("type") == "event":
            payload = resp.get("payload", {})
            nonce = payload.get("nonce")
            ts = payload.get("ts")
            if nonce and ts:
                sig = _sign_nonce(nonce, str(ts), device_id, token)
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

                # Read challenge result
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
