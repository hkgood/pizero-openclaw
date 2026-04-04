"""
OpenClaw Gateway HTTP streaming client.
Uses HTTP POST with SSE (Server-Sent Events) for streaming.
"""
import json
import logging
from typing import Generator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

log = logging.getLogger("openclaw")


def _get_session() -> requests.Session:
    """Create a requests session with retry logic."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.3,
        status_forcelist=[502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def stream_response(
    user_text: str,
    history: list[dict] | None = None,
) -> Generator[str, None, None]:
    """
    Send user_text to OpenClaw Gateway /v1/responses with streaming.

    Yields text deltas as they arrive via SSE.
    """
    url = f"{config.OPENCLAW_BASE_URL}/v1/responses"
    headers = {
        "Authorization": f"Bearer {config.OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    if history:
        input_val = [
            {"type": "message", "role": m["role"], "content": m["content"]}
            for m in history
        ]
        input_val.append({"type": "message", "role": "user", "content": user_text})
    else:
        input_val = user_text

    body = {
        "model": "openclaw",
        "stream": True,
        "input": input_val,
    }

    log.info("[openclaw] POST %s (stream=true)", url)

    try:
        resp = _get_session().post(
            url, json=body, headers=headers, stream=True, timeout=(30, 120)
        )
    except (requests.ConnectionError, requests.Timeout) as e:
        raise RuntimeError(f"Cannot reach OpenClaw at {config.OPENCLAW_BASE_URL}: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(
            f"OpenClaw request failed ({resp.status_code}): {resp.text[:300]}"
        )

    # Process stream in small chunks so we yield tokens as soon as a full SSE line
    # arrives (lower latency than iter_lines() with default buffering).
    event_type = None
    buf = ""
    for chunk in resp.iter_content(chunk_size=512, decode_unicode=True):
        if chunk is None:
            continue
        buf += chunk
        while "\n" in buf or "\r" in buf:
            line, _, buf = buf.partition("\n")
            line = line.strip("\r")
            if not line:
                event_type = None
                continue
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
                continue
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                msg_type = data.get("type", "")

                if msg_type == "response.output_text.delta":
                    delta = data.get("delta")
                    if isinstance(delta, str):
                        yield delta
                    elif isinstance(delta, dict):
                        yield delta.get("text", "")

                elif msg_type == "response.content_part.added":
                    part = data.get("part", {})
                    if isinstance(part, dict):
                        yield part.get("text", "")

                elif msg_type == "response.completed":
                    return

                elif msg_type == "error":
                    err_msg = data.get("error", {}).get("message", str(data))
                    raise RuntimeError(f"OpenClaw stream error: {err_msg}")

            elif line.startswith("error:"):
                err_msg = line[len("error:"):].strip()
                raise RuntimeError(f"OpenClaw stream error: {err_msg}")
