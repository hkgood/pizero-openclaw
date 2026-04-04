"""
OpenClaw Gateway WebSocket client.

Uses WebSocket to communicate with the OpenClaw Gateway,
which only exposes WS endpoints (not HTTP REST).
"""
import json
import logging
import uuid
from typing import Generator

try:
    import websocket
except ImportError:
    websocket = None

import config

log = logging.getLogger("openclaw")


def _generate_device_id() -> str:
    """Generate a persistent device ID based on machine info."""
    import hashlib
    import uuid as uuid_module

    # Try to use a stable machine ID
    try:
        with open("/etc/machine-id", "r") as f:
            machine_id = f.read().strip()
    except (FileNotFoundError, PermissionError):
        machine_id = str(uuid_module.getnode())

    return hashlib.sha256(machine_id.encode()).hexdigest()[:32]


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
    request_id = str(uuid.uuid4())

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
        connect_msg = {
            "type": "req",
            "method": "connect",
            "id": request_id,
            "params": {
                "host": base_url.replace("http://", "").replace("https://", ""),
                "deviceId": device_id,
            },
        }
        ws.send(json.dumps(connect_msg))
        log.info("Sent connect request")

        # Step 2: Read connect response
        resp = ws.recv()
        resp_data = json.loads(resp)
        log.info("Connect response: %s", str(resp_data)[:200])

        if resp_data.get("error"):
            err = resp_data["error"]
            raise RuntimeError(f"Gateway connect error: {err}")

        # Step 3: Send prompt request
        prompt_id = str(uuid.uuid4())

        # Build conversation history
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

            # Process complete JSON messages (newline-delimited JSON)
            while "\n" in buffer:
                line, _, buffer = buffer.partition("\n")
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("Invalid JSON in stream: %s", line[:100])
                    continue

                msg_type = data.get("type", "")
                msg_id = data.get("id")

                # Check for errors
                if msg_type == "error" or data.get("error"):
                    err = data.get("error", data.get("message", "Unknown error"))
                    raise RuntimeError(f"Gateway error: {err}")

                # Handle response.done / response.completed
                if msg_type in ("response.done", "response.completed", "done", "stop"):
                    log.info("Stream completed (type=%s)", msg_type)
                    return

                # Extract text from various delta formats
                text = _extract_text_from_ws_data(data)
                if text:
                    yield text

    finally:
        ws.close()


def _extract_text_from_ws_data(data: dict) -> str | None:
    """Extract text content from a WebSocket data frame."""
    msg_type = data.get("type", "")

    # response.output_text.delta
    if msg_type == "response.output_text.delta":
        delta = data.get("delta")
        if isinstance(delta, str):
            return delta
        if isinstance(delta, dict):
            return delta.get("text") or delta.get("content")

    # content_block_delta (OpenAI compatible)
    if msg_type == "content_block_delta":
        delta = data.get("delta", {})
        return delta.get("text") or delta.get("content")

    # response.content_part.delta
    if msg_type == "response.content_part.delta":
        part = data.get("part", {})
        if isinstance(part, dict):
            return part.get("text")

    # text delta event
    if msg_type == "text_delta":
        return data.get("delta")

    # Extract from params (some servers put delta in params)
    params = data.get("params", {})
    if isinstance(params, dict):
        delta = params.get("delta")
        if isinstance(delta, str):
            return delta

    return None
