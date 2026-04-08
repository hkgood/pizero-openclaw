import logging
import logging.handlers
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path

import config

# ── 日志配置（自动 rotation，防止 SD 卡撑爆）───────────────────────────────
_log_file = os.environ.get(
    "OPENCLAW_LOG_FILE",
    os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
                 "pizero-openclaw.log"),
)
Path(_log_file).parent.mkdir(parents=True, exist_ok=True)

# RotatingFileHandler: 每个文件最大 1MB，保留最近 5 个文件
file_handler = logging.handlers.RotatingFileHandler(
    _log_file,
    mode="a",
    maxBytes=1_000_000,  # 1 MB
    backupCount=5,
    encoding="utf-8",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        file_handler,
    ],
)
log = logging.getLogger("openclaw")

# ── 硬件检测：测试模式 vs 真实硬件 ────────────────────────────────────────
_TEST_MODE = os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")
_HAS_WHISPLAY = False

if _TEST_MODE:
    log.info("TEST_MODE: 使用 mock display + 文本输入")
else:
    try:
        from display import Display
        _HAS_WHISPLAY = True
    except ImportError as e:
        err_str = str(e).lower()
        if "WhisPlay" in str(e) or "whisplay" in err_str or "no module named" in err_str:
            log.warning("WhisPlay 未安装，切换到测试模式 (设置 TEST_MODE=true 跳过此检测)")
            _TEST_MODE = True
        else:
            raise

if _TEST_MODE:
    # ── 测试模式依赖 ────────────────────────────────────────────────────
    import json
    from pathlib import Path
    from display_mock import MockWhisPlayBoard
    from record_audio import Recorder, check_audio_level
    from transcribe_openai import transcribe
    from openclaw_client import stream_response
    import subprocess
    import socket
    import json
    from enum import Enum
    class _TestInputState(Enum):
        IDLE = "idle"
        LISTENING = "listening"
        TRANSCRIBING = "transcribing"

    class _TestModePTT:
        """
        测试模式：pygame 子进程显示虚拟 PTT 按钮（空格按住说话）。
        终端文字输入在主进程处理。
        流程：
          IDLE → (空格按下) → LISTENING → (空格松开) → TRANSCRIBING
          → 用户在终端输入文字 → 回车发送
        """
        State = _TestInputState

        def __init__(self, board=None, on_press_cb=None, on_release_cb=None,
                     on_cancel_cb=None, cancel_allowed_cb=None,
                     on_any_press_cb=None, on_abort_listening_cb=None):
            self.state = _TestInputState.IDLE
            self._on_release = on_release_cb
            self._input_ready = threading.Event()  # 通知主进程可以输入
            self._input_done = threading.Event()   # 通知主进程输入已完成
            self._result = ""
            self._subprocess_ready = threading.Event()
            self._running = True

            # 启动 pygame 子进程
            repo_dir = Path(__file__).parent.resolve()
            script = repo_dir / "test_input.py"
            self._proc = subprocess.Popen(
                [sys.executable, str(script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # socket 服务器线程：接收 pygame 子进程发来的状态
            self._sock_path = "/tmp/pizero-test-input.sock"
            self._listener = threading.Thread(target=self._listen, daemon=True)
            self._listener.start()
            self._subprocess_ready.wait(timeout=3)
            log.info("TestInput pygame 窗口已启动，按空格说话，回车发送")

        def _listen(self):
            """监听子进程发来的状态变化。"""
            if os.path.exists(self._sock_path):
                os.unlink(self._sock_path)
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(self._sock_path)
            srv.listen(1)
            self._subprocess_ready.set()
            buf = ""
            while self._running:
                try:
                    srv.settimeout(0.5)
                    conn, _ = srv.accept()
                    buf = ""
                    while True:
                        chunk = conn.recv(256)
                        if not chunk:
                            break
                        buf += chunk.decode("utf-8", errors="replace")
                        while "\n" in buf:
                            line, _, buf = buf.partition("\n")
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                msg = json.loads(line)
                                self._handle_msg(msg)
                            except Exception:
                                pass
                    conn.close()
                except socket.timeout:
                    continue
                except Exception:
                    break
            try:
                srv.close()
            except Exception:
                pass

        def _handle_msg(self, msg):
            t = msg.get("type", "")
            if t == "quit":
                self._running = False
            elif t == "state":
                phase = msg.get("phase", "idle")
                if phase == "idle":
                    self.state = _TestInputState.IDLE
                elif phase == "listening":
                    self.state = _TestInputState.LISTENING
                elif phase == "typing":
                    self.state = _TestInputState.TRANSCRIBING
                    # 通知主线程开始读取输入
                    self._input_ready.set()
                    # 在子线程里读 stdin（主线程会等 _input_done）
                    t = threading.Thread(target=self._do_input, daemon=True)
                    t.start()

        def _do_input(self):
            try:
                print("\n" + "-" * 40)
                print("  Release SPACE — type your message below")
                print("-" * 40)
                line = sys.stdin.readline()
                text = line.strip() if line else ""
            except Exception:
                text = ""
            self._result = text
            self._input_done.set()

        def start_listening(self):
            self.state = _TestInputState.LISTENING

        def wait_for_input(self, timeout=None):
            # 等输入完成（用户按回车）
            return self._input_done.wait(timeout=timeout)

        def consume_input(self):
            text = self._result
            self._result = ""
            self._input_done.clear()
            self._input_ready.clear()
            self.state = _TestInputState.IDLE
            return text

        def stop_listening(self):
            pass

        def cleanup(self):
            self._running = False
            if hasattr(self, "_proc") and self._proc:
                self._proc.terminate()
            try:
                os.unlink(self._sock_path)
            except Exception:
                pass

    ButtonPTT = _TestModePTT

    class _DisabledTTS:
        def __init__(self):
            pass
        def submit(self, text):
            pass
        def flush(self):
            pass
        def cancel(self):
            pass

    TTSPlayer = _DisabledTTS
    config.ENABLE_TTS = False

    class _SocketDisplay:
        """
        测试模式 Display：通过 Unix socket 与 gui_display.py 子进程通信，
        在真实 GUI 窗口中渲染 240x240 模拟 LCD（放大 3x）。
        同时保留 console 输出用于调试。
        """
        _SOCK_PATH = "/tmp/pizero-gui.sock"

        def __init__(self, backlight=70):
            self._backlight = backlight
            self._width = 240
            self._height = 240
            self._sleeping = False
            self._response_buf = ""
            self._char_state = "idle"
            self._stop_event = threading.Event()
            self._conn = None
            self._lock = threading.Lock()
            self._board = MockWhisPlayBoard()
            self._frame_count = 0
            self._output_dir = self._board._output_dir
            self._start_gui()
            log.info(f"SocketDisplay: GUI 窗口已启动，输出目录 {self._output_dir}")

        def _start_gui(self):
            import subprocess, socket, os, time

            # Kill any stale gui process
            try:
                os.unlink(self._SOCK_PATH)
            except OSError:
                pass

            repo_dir = Path(__file__).parent.resolve()
            self._proc = subprocess.Popen(
                [sys.executable, str(repo_dir / "gui_display.py"), self._SOCK_PATH],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Wait for socket to be ready
            for _ in range(30):
                time.sleep(0.1)
                try:
                    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    conn.connect(self._SOCK_PATH)
                    conn.close()
                    break
                except (OSError, IOError):
                    pass

        def _send(self, msg: dict):
            with self._lock:
                try:
                    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    conn.settimeout(2.0)
                    conn.connect(self._SOCK_PATH)
                    conn.sendall((json.dumps(msg) + "\n").encode())
                    conn.close()
                except Exception as e:
                    log.debug(f"gui send failed: {e}")

        @property
        def is_sleeping(self):
            return self._sleeping

        def sleep(self):
            self._sleeping = True

        def wake(self):
            self._sleeping = False

        def set_idle_screen(self):
            now = datetime.now()
            print(f"\n┌─────────────────────────────┐")
            print(f"│  🕐 {now.strftime('%H:%M:%S')}               │")
            print(f"│  📅 {now.strftime('%a, %b %d')}              │")
            print(f"│  🟢 TEST MODE — 按回车说话  │")
            print(f"└─────────────────────────────┘")
            self._send({"type": "idle"})

        def set_status(self, text, color=(200,200,200), subtitle=None, accent_color=None):
            print(f"\n┌─────────────────────────────┐")
            print(f"│ {text[:25]:<25} │")
            if subtitle:
                print(f"│ {subtitle[:25]:<25} │")
            print(f"└─────────────────────────────┘")
            accent = "#{:02X}{:02X}{:02X}".format(*accent_color) if accent_color else "#282828"
            self._send({"type": "status", "text": text, "sub": subtitle or "", "accent": accent})

        def start_spinner(self, label="Thinking", color=(255,220,50)):
            print(f"\n⏳ {label}...", end="", flush=True)
            self._send({"type": "status", "text": f"⏳ {label}", "sub": "Getting answer…",
                        "accent": "#{:02X}{:02X}{:02X}".format(*color)})

        def stop_spinner(self):
            print()

        def set_response_text(self, text):
            self._response_buf = text
            self._send({"type": "response", "text": text})

        def append_response(self, delta):
            self._response_buf += delta
            self._send({"type": "append", "delta": delta})
            print(f"\r  💬 {self._response_buf[-60:]}", end="", flush=True)

        def flush_response(self):
            print(f"\n✅ 回复: {self._response_buf[:200]}")

        def start_character(self, state="done", tts_player=None):
            self._char_state = state
            print(f"\n🎭 {state.upper()}")
            self._send({"type": "character", "state": state})

        def set_character_state(self, state):
            self._char_state = state
            self._send({"type": "character", "state": state})

        def stop_character(self):
            pass

        def clear(self):
            print("\n" + "─" * 31)
            self._send({"type": "clear"})

        def set_backlight(self, level):
            self._backlight = level

        def cleanup(self):
            self._stop_event.set()
            try:
                self._send({"type": "quit"})
            except Exception:
                pass
            if hasattr(self, "_proc") and self._proc:
                self._proc.terminate()
            print(f"SocketDisplay done. Total renders: {self._frame_count}")

    Display = _SocketDisplay

    def check_audio_level(path):
        """测试模式跳过静音检测。"""
        return 5000

else:
    # ── 真实硬件模式 ────────────────────────────────────────────────────
    from display import Display
    from record_audio import Recorder, check_audio_level
    from transcribe_openai import transcribe
    from openclaw_client import stream_response
    from button_ptt import ButtonPTT
    from tts_openai import TTSPlayer

# State 枚举：硬件模式从 button_ptt 导入，测试模式用 Enum fallback
try:
    from button_ptt import State
except (ImportError, ModuleNotFoundError):
    from enum import Enum
    class State(Enum):
        IDLE = "idle"
        LISTENING = "listening"
        TRANSCRIBING = "transcribing"
        THINKING = "thinking"
        STREAMING = "streaming"
        ERROR = "error"

from datetime import datetime


class Assistant:
    def __init__(self):
        config.print_config()

        # ── 启动时检查 OpenClaw Gateway 连通性 ────────────────────────────
        if not _TEST_MODE:
            self._check_openclaw_connectivity()

        self.display = Display(backlight=config.LCD_BACKLIGHT)
        self.recorder = Recorder()
        # 测试模式用 _SocketDisplay，没有 .board 属性，ButtonPTT 忽略 board
        board = getattr(self.display, "board", None)
        self.ptt = ButtonPTT(
            board,
            on_press_cb=self._on_button_press,
            on_release_cb=self._on_button_release,
            on_cancel_cb=self._on_button_cancel,
            cancel_allowed_cb=lambda: (time.monotonic() - self._state_entered_at) >= 2.0,
            on_any_press_cb=self._touch,
            on_abort_listening_cb=self._on_abort_listening,
        )
        self._worker_thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._dismiss = threading.Event()
        self._worker_gen = 0
        self._response_hold_timeout = 30
        self._sleep_timeout = 60
        self._last_activity = time.monotonic()
        self._last_idle_refresh = 0.0
        self._state_entered_at = 0.0
        self._tts = TTSPlayer() if config.ENABLE_TTS else None
        self._conversation_history: list[dict] = []

    def _check_openclaw_connectivity(self):
        """启动时检查 OpenClaw Gateway 是否可达，不可达则提示用户。"""
        import urllib.request
        # 新版 Gateway 的 /v1/models 不能稳定代表 WebSocket 可用性，
        # 统一改为更轻量的 /health 探活。
        url = config.OPENCLAW_BASE_URL.rstrip("/") + "/health"
        try:
            req = urllib.request.Request(url)
            urllib.request.urlopen(req, timeout=config.OPENCLAW_HEALTHCHECK_TIMEOUT_MS / 1000.0)
            log.info("OpenClaw gateway reachable: %s", config.OPENCLAW_BASE_URL)
            # 更新屏幕龙虾图标为已连接状态
            if hasattr(self, "display") and hasattr(self.display, "set_openclaw_connected"):
                self.display.set_openclaw_connected(True)
        except Exception as e:
            log.warning(
                "OpenClaw gateway not reachable at %s: %s\n"
                "  - Is the OpenClaw gateway running? (openclaw gateway start)"
                "  - If you are using the official remote setup, is the SSH tunnel up?\n"
                "  - Is OPENCLAW_TOKEN or OPENCLAW_PASSWORD configured in .env?\n"
                "  - Is the URL correct? (current: %s)",
                config.OPENCLAW_BASE_URL, e, config.OPENCLAW_BASE_URL,
            )
            # 更新屏幕龙虾图标为未连接状态
            if hasattr(self, "display") and hasattr(self.display, "set_openclaw_connected"):
                self.display.set_openclaw_connected(False)

    def _is_stale(self, my_gen: int) -> bool:
        return self._worker_gen != my_gen

    def _prune_history(self):
        """按 token 数裁剪对话历史，防止超出模型 context window。
        
        简单估算：中文≈1 token/字，英文≈1 token/4 字符。
        留 20% buffer，实际用 (max_tokens * 0.8) 作为上限。
        """
        max_tokens = (
            getattr(config, "MAX_CONTEXT_TOKENS", 16000) * 80 // 100
        )
        # 估算当前总 token 数
        def _estimate_tokens(history: list[dict]) -> int:
            total = 0
            for msg in history:
                content = msg.get("content", "")
                # 粗略估算：汉字每个 1 token，英文每 4 字符 1 token
                chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
                other_chars = len(content) - chinese_chars
                total += chinese_chars + (other_chars + 3) // 4
            return total

        while len(self._conversation_history) > 2:
            estimated = _estimate_tokens(self._conversation_history)
            if estimated <= max_tokens:
                break
            # 每次移除最老的一对（user + assistant）
            self._conversation_history = self._conversation_history[2:]

    def _touch(self):
        self._last_activity = time.monotonic()
        if self.display.is_sleeping:
            self.display.wake()
            self._go_idle()

    def _on_button_cancel(self):
        """Cancel any active operation (transcribing, thinking, or streaming)."""
        self._touch()
        self._worker_gen += 1
        self._dismiss.set()
        self.display.stop_spinner()
        self.display.stop_character()
        if self._tts:
            self._tts.cancel()
        self._go_idle()
        log.info("button cancel -- back to Ready")

    def _on_abort_listening(self):
        """Called when user presses again while in LISTENING (stuck or abort): stop recorder, go Ready."""
        self.recorder.cancel()
        self.display.stop_character()
        self._go_idle()
        log.info("abort listening -- back to Ready")

    def _on_button_press(self):
        self._touch()
        self._dismiss.set()
        log.info("button pressed -- start recording")
        if self._tts:
            self._tts.cancel()  # 立即停止 TTS，防止麦克风录进扬声器的声音
        self.display.start_character("listening", self._tts)
        if not _TEST_MODE:
            try:
                self.recorder.start()
            except Exception as e:
                log.error("recording start failed: %s", e)
                self._show_error(str(e))
        else:
            # 测试模式：启动文本输入循环
            self.ptt.start_listening()

    def _on_button_release(self):
        log.info("button released -- processing")
        t = threading.Thread(target=self._process_utterance, daemon=True)
        t.start()
        self._worker_thread = t

    def _process_utterance(self):
        my_gen = self._worker_gen
        try:
            self._process_utterance_inner(my_gen)
        except Exception as e:
            if not self._is_stale(my_gen):
                log.error("error: %s", e)
                self.display.stop_spinner()
                self.display.stop_character()
                self._show_error(str(e)[:80])
        finally:
            self.display.stop_spinner()
            if not self._is_stale(my_gen) and self.ptt.state in (
                State.TRANSCRIBING, State.THINKING, State.STREAMING,
            ):
                self._go_idle()

    def _process_utterance_inner(self, my_gen: int):
        # --- 测试模式：pygame 窗口监听空格，终端输入文字 ---
        if _TEST_MODE:
            # 等待 pygame 线程收到文字输入（_input_done 信号）
            got_input = self.ptt.wait_for_input(timeout=120)
            if not got_input:
                log.info("test input timeout, returning to idle")
                self._go_idle()
                return
            transcript = self.ptt.consume_input()
            if not transcript:
                log.info("empty input, returning to idle")
                self._go_idle()
                return
            log.info("test input: %r", transcript[:80])
        else:
            # --- 真实硬件模式：录音 → 转写 ---
            wav_path = self.recorder.stop()

            # --- Silence gate ---
            rms = check_audio_level(wav_path)
            if rms < config.SILENCE_RMS_THRESHOLD:
                log.info("silence detected (RMS=%.0f), skipping", rms)
                if self._is_stale(my_gen):
                    return
                self.display.set_character_state("sleep")
                time.sleep(1.5)
                if not self._is_stale(my_gen):
                    self._go_idle()
                return

            if self._is_stale(my_gen):
                return

            # --- Transcribe ---
            self._state_entered_at = time.monotonic()
            self.ptt.state = State.TRANSCRIBING
            self.display.set_character_state("thinking")
            t0 = time.monotonic()
            transcript = transcribe(wav_path)
            log.info("transcribe took %.1fs => %r", time.monotonic() - t0, (transcript[:80] if transcript else "(empty)"))

            if not transcript or self._is_stale(my_gen):
                if not self._is_stale(my_gen):
                    log.info("empty transcript, returning to idle")
                    self._go_idle()
                return

        # --- Stream response from OpenClaw (with conversation context) ---
        if self._is_stale(my_gen):
            return
        self._state_entered_at = time.monotonic()
        self.ptt.state = State.THINKING
        self.display.set_character_state("thinking")

        self.ptt.state = State.STREAMING
        first_token = True
        full_response = ""
        tts_buffer = ""
        stream_t0 = time.monotonic()

        for delta in stream_response(transcript, history=self._conversation_history):
            if self._is_stale(my_gen) or self._shutdown.is_set():
                break
            if first_token:
                log.info("first token after %.1fs", time.monotonic() - stream_t0)
                self.display.set_character_state("talking")
                first_token = False
            full_response += delta
            self.display.append_response(delta)

            # Streaming TTS: batch sentences for natural flow
            # Supports both ASCII (. ! ?) and Chinese (。 ！ ？) punctuation
            if self._tts:
                tts_buffer += delta
                sentence_ends = list(re.finditer(r"[.!?。！？]\s?|\n", tts_buffer))
                if len(sentence_ends) >= 2:
                    cut = sentence_ends[1].end()
                    chunk = tts_buffer[:cut].strip()
                    tts_buffer = tts_buffer[cut:]
                    if chunk:
                        log.info("[tts] submit chunk (%d chars): %s", len(chunk), chunk[:60])
                        self._tts.submit(chunk)

        # Stale worker: exit without touching display, TTS, or history
        if self._is_stale(my_gen):
            return

        log.info("stream done in %.1fs, %d chars", time.monotonic() - stream_t0, len(full_response))

        # Submit remaining TTS buffer and wait for playback to finish
        if self._tts:
            if tts_buffer.strip():
                log.info("[tts] submit final chunk (%d chars): %s", len(tts_buffer.strip()), tts_buffer.strip()[:60])
                self._tts.submit(tts_buffer.strip())
            self._tts.flush()
        # 说完话：切换到 happy 状态短暂停留，然后 _go_idle 接管
        self.display.set_character_state("done")
        self.display.set_response_text(full_response)

        log.info("response complete -- holding on screen")

        # Update conversation history
        self._conversation_history.append({"role": "user", "content": transcript})
        self._conversation_history.append({"role": "assistant", "content": full_response})
        self._prune_history()

        self._dismiss.clear()
        self._dismiss.wait(timeout=self._response_hold_timeout)

        # Could have been cancelled during the hold
        if self._is_stale(my_gen):
            return

        if self._dismiss.is_set():
            log.info("dismissed by button press")
        else:
            log.info("display timeout, returning to idle")

        self._go_idle()

    def _go_idle(self):
        self._last_activity = time.monotonic()
        self._last_idle_refresh = time.monotonic()
        self.ptt.state = State.IDLE
        self.display.set_backlight(config.LCD_BACKLIGHT)
        self.display.stop_character()
        self.display.set_idle_screen()

    def _show_error(self, msg: str):
        self.ptt.state = State.ERROR
        self.display.stop_character()
        # 胶囊眼睛模式：展示 error 状态动画
        if getattr(self.display, "_eye", None) is not None:
            self.display.start_character("error")
            time.sleep(3)
        else:
            self.display.set_status(
                msg[:50] + ("..." if len(msg) > 50 else ""),
                color=(255, 120, 120),
                subtitle="Something went wrong",
                accent_color=(200, 0, 0),
            )
            time.sleep(3)
        self._go_idle()

    def run(self):
        self._go_idle()
        log.info("assistant ready -- press button to talk")

        try:
            while not self._shutdown.is_set():
                self._shutdown.wait(timeout=1.0)
                worker_busy = self._worker_thread is not None and self._worker_thread.is_alive()

                # Refresh idle screen periodically (clock update)
                if (
                    not self.display.is_sleeping
                    and self.ptt.state == State.IDLE
                    and not worker_busy
                    and time.monotonic() - self._last_idle_refresh > 30
                ):
                    self.display.set_idle_screen()
                    self._last_idle_refresh = time.monotonic()

                # Sleep display after inactivity
                if (
                    not self.display.is_sleeping
                    and self.ptt.state == State.IDLE
                    and not worker_busy
                    and time.monotonic() - self._last_activity > self._sleep_timeout
                ):
                    log.info("idle timeout -- sleeping display")
                    self.display.sleep()
        except KeyboardInterrupt:
            log.info("shutting down...")
        finally:
            self.shutdown()

    def shutdown(self):
        self._shutdown.set()
        self._worker_gen += 1
        self._dismiss.set()
        self.recorder.cancel()
        if self._tts:
            self._tts.cancel()
        self.display.stop_character()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        self.display.cleanup()
        log.info("cleanup done")


def main():
    assistant = Assistant()

    def _sigterm_handler(signum, frame):
        assistant.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)
    assistant.run()


if __name__ == "__main__":
    main()
