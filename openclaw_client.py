import json
import logging
from typing import Generator
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

log = logging.getLogger("openclaw")

_http_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)
    return _http_session


def _extract_text_from_data(data: dict) -> Generator[str, None, None]:
    """
    从 SSE data 对象中提取文本。兼容所有已知的 OpenAI-compatible 响应格式，
    防止因事件类型名称不匹配而丢 token。
    """
    # 格式 1: {"type": "response.output_text.delta", "delta": "..."}
    delta = data.get("delta")
    if delta and isinstance(delta, str):
        yield delta
        return

    # 格式 2: {"type": "response.output_text.delta", "delta": {"text": "..."}}
    if isinstance(delta, dict):
        text = delta.get("text") or delta.get("content") or delta.get("value")
        if text:
            yield text
            return

    # 格式 3: {"type": "response.content_part.added", "part": {"text": "..."}}
    part = data.get("part") or data.get("content") or {}
    if isinstance(part, dict):
        text = part.get("text") or part.get("content") or part.get("value")
        if text:
            yield text
            return

    # 格式 4: {"type": "content_block_delta", "delta": {"text": "..."}}
    # OpenAI Chat Completions 兼容格式
    if data.get("type") == "content_block_delta":
        delta = data.get("delta", {})
        text = delta.get("text") or delta.get("content")
        if text:
            yield text
            return

    # 格式 5: {"choices": [{"delta": {"content": "..."}}]}
    # OpenAI 旧版格式
    choices = data.get("choices")
    if choices and isinstance(choices, list):
        for choice in choices:
            delta = choice.get("delta", {})
            text = delta.get("content") or delta.get("text")
            if text:
                yield text

    # 格式 6: {"message": {"content": "..."}}  # 非流式（降级）
    msg = data.get("message", {})
    content = msg.get("content")
    if content and isinstance(content, str):
        yield content


def stream_response(
    user_text: str,
    history: list[dict] | None = None,
) -> Generator[str, None, None]:
    """Send user_text to OpenClaw /v1/responses with streaming.

    Yields text deltas as they arrive via SSE.
    兼容多种 SSE 事件格式，防止丢 token。
    """
    base = config.OPENCLAW_BASE_URL.rstrip("/")
    url = f"{base}/v1/responses"
    headers = {
        "Authorization": f"Bearer {config.OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    if history:
        input_val: str | list[dict] = [
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

    log.info("POST %s (stream=true)", url)

    try:
        resp = _get_session().post(
            url, json=body, headers=headers, stream=True, timeout=(30, 120)
        )
    except (requests.ConnectionError, requests.Timeout) as e:
        raise RuntimeError(
            f"Cannot reach OpenClaw at {config.OPENCLAW_BASE_URL}: {e}"
        ) from e

    if resp.status_code != 200:
        raise RuntimeError(
            f"OpenClaw request failed ({resp.status_code}): {resp.text[:300]}"
        )

    buf = ""
    for chunk in resp.iter_content(chunk_size=256, decode_unicode=True):
        if chunk is None:
            continue
        buf += chunk

        # 提取完整的 SSE 行
        while "\n" in buf or "\r" in buf:
            line, _, buf = buf.partition("\n")
            line = line.strip().rstrip("\r")
            if not line:
                continue

            # 解析 data: 行
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str or data_str == "[DONE]":
                continue

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                log.warning("invalid JSON in SSE stream: %s", data_str[:100])
                continue

            msg_type = data.get("type", "")

            # 终止信号
            if msg_type in ("response.completed", "done", "stop"):
                log.info("stream completed (type=%s)", msg_type)
                return

            if msg_type == "error":
                err_msg = data.get("error", {})
                if isinstance(err_msg, dict):
                    err_msg = err_msg.get("message", str(err_msg))
                raise RuntimeError(f"OpenClaw stream error: {err_msg}")

            # 提取文本 delta（所有兼容格式）
            for text in _extract_text_from_data(data):
                if text:
                    yield text
