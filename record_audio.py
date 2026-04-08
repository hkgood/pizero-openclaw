import math
import os
import pathlib
import platform
import signal
import struct
import subprocess
import time
import wave

import config

_IS_MAC = platform.system() == "Darwin"

# 录音文件放在用户专属目录，权限 600（仅本人可读写）
_WAV_DIR = pathlib.Path.home() / ".local" / "state" / "pizero-openclaw"
_WAV_DIR.mkdir(parents=True, exist_ok=True)
_WAV_PATH = str(_WAV_DIR / "utterance.wav")


def check_audio_level(wav_path: str) -> float:
    """Return RMS energy of a 16-bit mono WAV. 0 = silence, ~32768 = max."""
    try:
        with wave.open(wav_path, "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0:
                return 0.0
            raw = wf.readframes(n_frames)
            n_samples = n_frames * wf.getnchannels()
            if len(raw) < n_samples * 2:
                return 0.0
            samples = struct.unpack(f"<{n_samples}h", raw[: n_samples * 2])
            return math.sqrt(sum(s * s for s in samples) / n_samples)
    except Exception as e:
        print(f"[rec] audio level check failed: {e}")
        return float("inf")


def _dump_audio_info():
    """Print audio device info for debugging."""
    print("--- /proc/asound/cards ---")
    try:
        with open("/proc/asound/cards") as f:
            print(f.read())
    except Exception as e:
        print(f"  (unavailable: {e})")

    print("--- arecord -l ---")
    try:
        result = subprocess.run(
            ["arecord", "-l"], capture_output=True, text=True, timeout=5
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
    except Exception as e:
        print(f"  (unavailable: {e})")


class Recorder:
    def __init__(self):
        self._proc: subprocess.Popen | None = None

    @property
    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.is_recording:
            return

        # 删除旧文件，防止 arecord 启动失败时透明复用过期录音
        if os.path.exists(_WAV_PATH):
            try:
                os.remove(_WAV_PATH)
            except OSError:
                pass

        # 设置录音文件权限：仅本人可读写（600）
        os.chmod(_WAV_DIR, 0o700)

        cmd = [
            "arecord",
            "-D", config.AUDIO_DEVICE,
            "-f", "S16_LE",
            "-r", str(config.AUDIO_SAMPLE_RATE),
            "-c", "1",
            "-t", "wav",
            _WAV_PATH,
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            print(f"[rec] started: {' '.join(cmd)}")
        except FileNotFoundError:
            print("[rec] ERROR: arecord not found — install alsa-utils")
            _dump_audio_info()
            raise
        except Exception:
            _dump_audio_info()
            raise

    def stop(self) -> str:
        """Stop recording. Returns path to the WAV file."""
        proc = self._proc
        if proc is None:
            return _WAV_PATH

        # Send SIGINT for clean WAV header finalization
        try:
            proc.send_signal(signal.SIGINT)
        except OSError:
            pass

        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

        stderr = ""
        if proc.stderr:
            try:
                stderr = proc.stderr.read().decode(errors="replace")
            except Exception:
                pass

        self._proc = None

        if not os.path.exists(_WAV_PATH) or os.path.getsize(_WAV_PATH) < 100:
            print(f"[rec] WARNING: WAV file missing or too small")
            if stderr:
                print(f"[rec] stderr: {stderr}")
            _dump_audio_info()

        # 录音设备错误时明确抛出，防止静默复用旧文件
        if stderr and ("error" in stderr.lower() or "cannot" in stderr.lower()):
            raise RuntimeError(f"Recording device error: {stderr.strip()[:200]}")

        # 录音结束立即设权限，防止中间被其他进程读取
        os.chmod(_WAV_PATH, 0o600)

        return _WAV_PATH

    def cancel(self) -> None:
        """Kill recording without caring about output."""
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        self._proc = None
