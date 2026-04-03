"""
Mock WhisPlay Board + GUI Display — 测试模式用 Tkinter 实时显示模拟 LCD。
每个状态变化都会更新窗口，支持：
  - 状态文字（Listening / Thinking / Transcribing）
  - 流式回复文字
  - 空闲时钟画面
  - 彩色 accent bar
"""
import math
import os
import queue
import struct
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from PIL import Image, ImageDraw, ImageFont

import config


# ── Mock WhisPlay Board ───────────────────────────────────────────────────────
class MockWhisPlayBoard:
    LCD_WIDTH = 240
    LCD_HEIGHT = 240

    def __init__(self):
        self._backlight = 70
        self._frame_count = 0
        out_dir = Path.home() / "pizero-openclaw-frames"
        out_dir.mkdir(exist_ok=True)
        self._output_dir = out_dir
        self._last_rgb565_buf = []

    def set_backlight(self, level: int):
        self._backlight = level

    def set_backlight_color(self, r: int, g: int, b: int):
        pass

    def draw_image(self, x: int, y: int, w: int, h: int, rgb565_buf: list):
        self._frame_count += 1
        self._last_rgb565_buf = rgb565_buf
        # Save frame to disk as PNG (for debugging)
        img = self._rgb565_to_image(w, h, rgb565_buf)
        path = self._output_dir / f"frame_{self._frame_count:04d}.png"
        try:
            img.save(path)
        except Exception:
            pass

    def _rgb565_to_image(self, w: int, h: int, buf: list) -> Image.Image:
        pixels = []
        for i in range(0, min(len(buf) - 1, w * h * 2), 2):
            hi, lo = buf[i], buf[i + 1]
            rgb565 = (hi << 8) | lo
            r = ((rgb565 >> 11) & 0x1F) << 3
            g = ((rgb565 >> 5) & 0x3F) << 2
            b = (rgb565 & 0x1F) << 3
            pixels.append((r, g, b))
        img = Image.new("RGB", (w, h))
        if pixels:
            img.putdata(pixels[:w * h])
        return img

    def fill_screen(self, color: int = 0):
        pass

    def cleanup(self):
        pass


# ── GUI Display — Tkinter 实时窗口 ─────────────────────────────────────────
class GUIDisplay:
    """
    测试模式用 Tkinter 显示模拟的 240x240 WhisPlay LCD。
    窗口等比放大 3x (720x720)，每帧实时更新。
    """

    _ACCENT_COLORS = {
        "listening":  "#3C8CFF",
        "thinking":    "#FFDC32",
        "talking":     "#00C864",
        "done":        "#00A050",
        "idle":        "#282828",
        "error":       "#FF0000",
        "transcribing":"#FFE600",
    }

    _STATE_LABELS = {
        "listening":   "🎤 Listening...",
        "thinking":     "💭 Thinking...",
        "talking":      "🗣️  Talking...",
        "transcribing": "📝 Transcribing...",
        "done":         "✅ Done",
        "idle":         "🟢 Ready",
        "error":        "❌ Error",
    }

    def __init__(self, backlight: int = 70):
        self._width = 240
        self._height = 240
        self._scale = 3  # 放大倍数
        self._backlight = backlight
        self._sleeping = False
        self._response_buf = ""
        self._char_state = "idle"
        self._subtitle = ""
        self._accent_color = self._ACCENT_COLORS["idle"]
        self._status_text = ""
        self._status_sub = ""
        self._battery_pct = None
        self._wifi_on = True
        self._clock_str = ""
        self._date_str = ""
        self._frame_count = 0
        self._last_draw = 0.0
        self._min_interval = 0.1
        self._board = MockWhisPlayBoard()
        self._dirty = threading.Event()
        self._dirty.set()

        self._window = None
        self._canvas = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self._start_gui_thread()

    def _start_gui_thread(self):
        """启动 Tkinter 主循环在独立线程中。"""
        def run_tk():
            import tkinter as tk
            from tkinter import font as tkfont

            root = tk.Tk()
            root.title("pizero-openclaw (TEST MODE)")
            root.resizable(False, False)

            # 画布：240*3 x 240*3
            cw = self._width * self._scale
            ch = self._height * self._scale
            canvas = tk.Canvas(root, width=cw, height=ch, bg="#111", highlightthickness=0)
            canvas.pack()

            self._tk_root = root
            self._tk_canvas = canvas
            self._tk_scale = self._scale

            # 预加载字体
            try:
                self._font_bold = tkfont.Font(family="Menlo", size=11, weight="bold")
                self._font_reg = tkfont.Font(family="Menlo", size=9)
                self._font_clock = tkfont.Font(family="Menlo", size=20, weight="bold")
                self._font_small = tkfont.Font(family="Menlo", size=7)
            except Exception:
                self._font_bold = ("Menlo", 11, "bold")
                self._font_reg = ("Menlo", 9)
                self._font_clock = ("Menlo", 20, "bold")
                self._font_small = ("Menlo", 7)

            # 背景 rect
            self._bg_rect = canvas.create_rectangle(0, 0, cw, ch, fill="#000", outline="")
            # Accent bar
            self._accent_bar = canvas.create_rectangle(0, 0, cw, 3*self._scale, fill="#282828", outline="")
            # Status text
            self._status_id = canvas.create_text(
                5*self._scale, 10*self._scale,
                text="", fill="#CCC", font=self._font_bold, anchor="nw",
            )
            # Sub text
            self._sub_id = canvas.create_text(
                5*self._scale, 24*self._scale,
                text="", fill="#666", font=self._font_reg, anchor="nw",
            )
            # Response text (multi-line)
            self._resp_id = canvas.create_text(
                5*self._scale, 30*self._scale,
                text="", fill="#E6EBF0", font=self._font_reg, anchor="nw",
            )
            # Battery
            self._bat_id = canvas.create_text(
                cw - 5*self._scale, 5*self._scale,
                text="", fill="#666", font=self._font_small, anchor="ne",
            )
            # WiFi
            self._wifi_id = canvas.create_text(
                5*self._scale, 5*self._scale,
                text="●", fill="#00B450", font=self._font_small, anchor="nw",
            )
            # Clock
            self._clock_id = canvas.create_text(
                cw // 2, 80*self._scale,
                text="", fill="#DDD", font=self._font_clock, anchor="center",
            )
            # Date
            self._date_id = canvas.create_text(
                cw // 2, 108*self._scale,
                text="", fill="#666", font=self._font_reg, anchor="center",
            )
            # Hint
            self._hint_id = canvas.create_text(
                cw // 2, 225*self._scale,
                text="TEST MODE — 按回车说话", fill="#444",
                font=self._font_small, anchor="center",
            )

            def tick():
                if self._stop.is_set():
                    root.destroy()
                    return
                if self._dirty.is_set():
                    self._dirty.clear()
                    self._render_tk(root, canvas)
                root.after(80, tick)

            tick()
            root.mainloop()

        t = threading.Thread(target=run_tk, daemon=True)
        t.start()
        self._thread = t
        # 等待窗口就绪
        for _ in range(50):
            if hasattr(self, "_tk_root") and self._tk_root is not None:
                break
            time.sleep(0.05)

    def _render_tk(self, root, canvas):
        """将当前状态渲染到 Tk canvas。"""
        try:
            if self._char_state == "idle":
                # 空闲时钟画面
                canvas.itemconfig(self._status_id, text="")
                canvas.itemconfig(self._sub_id, text="")
                canvas.itemconfig(self._resp_id, text="")
                canvas.itemconfig(self._accent_bar, fill=self._accent_color)

                now = datetime.now()
                canvas.itemconfig(self._clock_id, text=now.strftime("%H:%M"))
                canvas.itemconfig(self._date_id, text=now.strftime("%a, %b %d"))
                canvas.itemconfig(self._hint_id, text="TEST MODE — 按回车说话")

                canvas.itemconfig(self._bat_id, text="—")
                canvas.itemconfig(self._wifi_id, text="●", fill="#00B450")

                self._frame_count += 1
            else:
                # 状态/回复画面
                canvas.itemconfig(self._clock_id, text="")
                canvas.itemconfig(self._date_id, text="")
                canvas.itemconfig(self._hint_id, text="")

                canvas.itemconfig(self._accent_bar, fill=self._accent_color)
                canvas.itemconfig(self._status_id, text=self._status_text)

                if self._status_sub:
                    canvas.itemconfig(self._sub_id, text=self._status_sub)
                else:
                    canvas.itemconfig(self._sub_id, text="")

                if self._response_buf:
                    canvas.itemconfig(self._resp_id, text=self._response_buf)
                else:
                    canvas.itemconfig(self._resp_id, text="")

                self._frame_count += 1

        except Exception as e:
            pass

    def _mark_dirty(self):
        self._dirty.set()

    # ── Public API（与真实 Display 接口一致）───────────────────────────────

    @property
    def is_sleeping(self):
        return self._sleeping

    def sleep(self):
        self._sleeping = True

    def wake(self):
        self._sleeping = False

    def set_idle_screen(self):
        self._char_state = "idle"
        self._accent_color = self._ACCENT_COLORS.get("idle", "#282828")
        self._status_text = ""
        self._status_sub = ""
        self._response_buf = ""
        self._mark_dirty()

    def set_status(self, text, color=(200, 200, 200), subtitle=None, accent_color=None):
        self._char_state = "status"
        self._status_text = text
        self._status_sub = subtitle or ""
        self._response_buf = ""
        if accent_color:
            hex_c = "#{:02X}{:02X}{:02X}".format(*accent_color)
            self._accent_color = hex_c
        self._mark_dirty()

    def start_spinner(self, label="Thinking", color=(255, 220, 50)):
        self._char_state = "thinking"
        self._status_text = f"⏳ {label}"
        self._status_sub = "Getting answer…"
        self._response_buf = ""
        hex_c = "#{:02X}{:02X}{:02X}".format(*color)
        self._accent_color = hex_c
        self._mark_dirty()

    def stop_spinner(self):
        self._mark_dirty()

    def set_response_text(self, text):
        self._response_buf = text
        self._char_state = "talking"
        self._accent_color = self._ACCENT_COLORS["talking"]
        self._mark_dirty()

    def append_response(self, delta):
        self._response_buf += delta
        self._mark_dirty()

    def flush_response(self):
        self._mark_dirty()

    def start_character(self, state="done", tts_player=None):
        self._char_state = state
        self._accent_color = self._ACCENT_COLORS.get(state, "#282828")
        self._status_text = self._STATE_LABELS.get(state, state.upper())
        self._status_sub = ""
        self._mark_dirty()

    def set_character_state(self, state):
        self._char_state = state
        self._accent_color = self._ACCENT_COLORS.get(state, "#282828")
        self._status_text = self._STATE_LABELS.get(state, state.upper())
        self._mark_dirty()

    def stop_character(self):
        pass

    def clear(self):
        self._char_state = "idle"
        self._response_buf = ""
        self._status_text = ""
        self._status_sub = ""
        self._mark_dirty()

    def set_backlight(self, level):
        self._backlight = level

    def cleanup(self):
        self._stop.set()
        if hasattr(self, "_tk_root"):
            try:
                self._tk_root.destroy()
            except Exception:
                pass
        print(f"[GUIDisplay] done. Total renders: {self._frame_count}")


# ── 兼容性别名 ────────────────────────────────────────────────────────────────
MockDisplay = GUIDisplay
