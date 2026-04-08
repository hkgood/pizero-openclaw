"""Speech-to-text via Bailian/DashScope FunASR (cloud) or OpenAI Whisper."""

import os
import time
import config

# ── Provider selection ─────────────────────────────────────────────────────────
_providers = {"funasr", "openai", "dryrun"}


def _provider() -> str:
    p = (getattr(config, "STT_PROVIDER", "") or "funasr").lower().strip()
    if p not in _providers:
        print(f"[transcribe] unknown STT_PROVIDER={p!r}, defaulting to funasr")
        p = "funasr"
    return p


def transcribe(wav_path: str) -> str:
    """Transcribe a WAV file to text.

    Provider is selected via config.STT_PROVIDER:
      funasr  — Bailian FunASR cloud (default)
      openai  — OpenAI Whisper API
      dryrun  — type input manually
    """
    p = _provider()

    if p == "dryrun" or (p == "funasr" and config.DRY_RUN):
        print("[transcribe] DRY RUN — type your message:")
        try:
            return input("> ").strip()
        except EOFError:
            return ""

    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    file_size = os.path.getsize(wav_path)
    if file_size < 100:
        raise ValueError(f"WAV file too small ({file_size} bytes), likely empty recording")

    if p == "funasr":
        return _transcribe_funasr(wav_path)
    else:
        return _transcribe_openai(wav_path)


# ── Bailian FunASR (cloud WebSocket via dashscope SDK) ─────────────────────

class _FunASRCallback:
    """Collects transcripts from the FunASR WebSocket stream."""

    def __init__(self):
        self._texts: list[str] = []
        self._done = False
        self._error: Exception | None = None

    def on_open(self) -> None:
        pass

    def on_close(self) -> None:
        pass

    def on_complete(self) -> None:
        self._done = True

    def on_error(self, message) -> None:
        self._error = RuntimeError(f"FunASR error: {message.message}")
        self._done = True

    def on_event(self, result) -> None:
        from dashscope.audio.asr import RecognitionResult
        sentence = result.get_sentence()
        if "text" in sentence:
            text = sentence["text"].strip()
            if text:
                self._merge_text(text)

    def _merge_text(self, text: str) -> None:
        """Keep only the latest version of an incremental FunASR chunk."""
        if not self._texts:
            self._texts.append(text)
            return

        last = self._texts[-1]
        if text == last:
            return

        # FunASR realtime callbacks often resend the current sentence with
        # more characters. Replace the tail chunk instead of appending it.
        if text.startswith(last) or last.startswith(text):
            self._texts[-1] = text if len(text) >= len(last) else last
            return

        # Handle partial overlap such as:
        #   "快 测试"
        #   "测试 测试测试"
        # by merging the suffix instead of duplicating the shared prefix.
        max_overlap = min(len(last), len(text))
        for overlap in range(max_overlap, 0, -1):
            if last.endswith(text[:overlap]):
                self._texts[-1] = last + text[overlap:]
                return

        self._texts.append(text)

    @property
    def texts(self) -> list[str]:
        return self._texts

    @property
    def error(self) -> Exception | None:
        return self._error


_FUNASR_TIMEOUT = 30  # 单次请求超时（秒）
_FUNASR_MAX_RETRIES = 3  # 最大重试次数


def _transcribe_funasr(wav_path: str) -> str:
    """Transcribe via Bailian FunASR cloud (WebSocket SDK). 自动重试，网络抖动也能成功。"""
    import dashscope
    from dashscope.audio.asr import Recognition, RecognitionCallback

    api_key = getattr(config, "DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY not set")
    dashscope.api_key = api_key

    base_url = getattr(config, "DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com")
    ws_base = base_url.replace("https://", "wss://").replace("http://", "ws://")
    dashscope.base_websocket_api_url = ws_base + "/api-ws/v1/inference"

    with open(wav_path, "rb") as f:
        file_buffer = f.read()

    last_error = None
    for attempt in range(1, _FUNASR_MAX_RETRIES + 1):
        callback = _FunASRCallback()
        try:
            recognition = Recognition(
                model="fun-asr-realtime",
                format="wav",
                sample_rate=16000,
                callback=callback,
                semantic_punctuation_enabled=False,
            )
            recognition.start()

            buffer_size = len(file_buffer)
            offset = 0
            chunk_size = 3200

            while offset < buffer_size:
                remaining = buffer_size - offset
                current_chunk = min(chunk_size, remaining)
                chunk_data = file_buffer[offset:offset + current_chunk]
                recognition.send_audio_frame(chunk_data)
                offset += current_chunk
                time.sleep(0.01)

            recognition.stop()

            # 等待结果，带超时
            t0 = time.time()
            while not callback._done and (time.time() - t0) < _FUNASR_TIMEOUT:
                time.sleep(0.1)

            if callback.error:
                raise callback.error

            transcript = " ".join(callback.texts).strip()
            print(f"[transcribe/funasr] result: {transcript[:120]} (attempt {attempt})")
            return transcript

        except Exception as e:
            last_error = e
            print(f"[transcribe/funasr] attempt {attempt}/{_FUNASR_MAX_RETRIES} failed: {e}")
            if attempt < _FUNASR_MAX_RETRIES:
                wait = 2 ** (attempt - 1)  # 指数退避：1s, 2s
                print(f"[transcribe/funasr] retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"[transcribe/funasr] all {_FUNASR_MAX_RETRIES} attempts failed")

    raise RuntimeError(
        f"FunASR transcription failed after {_FUNASR_MAX_RETRIES} attempts: {last_error}"
    )


# ── OpenAI Whisper (fallback) ─────────────────────────────────────────────────

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_http_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=[502, 503, 504], allowed_methods=["POST"])
        adapter = HTTPAdapter(max_retries=retry)
        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)
    return _http_session


def _transcribe_openai(wav_path: str) -> str:
    """Transcribe via OpenAI Whisper API."""
    api_key = getattr(config, "OPENAI_API_KEY", "")
    model = getattr(config, "OPENAI_TRANSCRIBE_MODEL", "whisper-1")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    with open(wav_path, "rb") as f:
        try:
            resp = _get_session().post(
                url, headers=headers,
                files={"file": ("utterance.wav", f, "audio/wav")},
                data={"model": model, "response_format": "text"},
                timeout=30,
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            raise RuntimeError(f"Transcription request failed: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(f"Transcription failed ({resp.status_code}): {resp.text[:300]}")

    transcript = resp.text.strip()
    print(f"[transcribe/openai] result: {transcript[:120]}")
    return transcript
