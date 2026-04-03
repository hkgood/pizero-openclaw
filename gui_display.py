#!/usr/bin/env python3
"""
gui_display.py — 测试模式 GUI 窗口（独立进程）
由 main.py 的 _MockDisplay 启动，渲染 240x240 等比放大 3x 的模拟 LCD。

通信协议（Unix socket）：
  接收 JSON 消息，格式：
    {"type": "idle"}
    {"type": "status", "text": "...", "sub": "...", "accent": "#RRGGBB"}
    {"type": "response", "text": "..."}
    {"type": "character", "state": "listening|thinking|talking|done|idle"}
    {"type": "clear"}
    {"type": "quit"}
"""
import json
import socket
import struct
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path.home() / "pizero-openclaw-frames"
OUT_DIR.mkdir(exist_ok=True)


def rgb565_to_img(w, h, buf):
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


ACCENT_COLORS = {
    "listening":   "#3C8CFF",
    "thinking":    "#FFDC32",
    "talking":     "#00C864",
    "done":        "#00A050",
    "idle":        "#282828",
    "error":       "#FF0000",
    "transcribing":"#FFE600",
}

STATE_LABELS = {
    "listening":   "🎤 Listening...",
    "thinking":    "💭 Thinking...",
    "talking":     "🗣️  Talking...",
    "transcribing":"📝 Transcribing...",
    "done":        "✅ Done",
    "idle":        "🟢 Ready",
    "error":       "❌ Error",
}


class GUIPanel:
    def __init__(self, scale=3):
        import tkinter as tk
        from tkinter import font as tkfont

        self._scale = scale
        self._w = 240
        self._h = 240
        cw = self._w * scale
        ch = self._h * scale

        self._state = "idle"
        self._status_text = ""
        self._status_sub = ""
        self._response_buf = ""
        self._accent = ACCENT_COLORS["idle"]

        # Build window
        self._root = tk.Tk()
        self._root.title("pizero-openclaw — TEST MODE")
        self._root.resizable(False, False)

        # PhotoImage buffer for LCD rendering
        self._photo = tk.PhotoImage(width=cw, height=ch)
        self._canvas = tk.Canvas(self._root, width=cw, height=ch,
                                  bg="#111", highlightthickness=0)
        self._canvas.pack()
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)

        # Pre-load fonts
        try:
            self._f_bold   = tkfont.Font(family="Menlo", size=11, weight="bold")
            self._f_reg    = tkfont.Font(family="Menlo", size=9)
            self._f_clock  = tkfont.Font(family="Menlo", size=22, weight="bold")
            self._f_small  = tkfont.Font(family="Menlo", size=7)
        except Exception:
            self._f_bold   = ("Menlo", 11, "bold")
            self._f_reg    = ("Menlo", 9)
            self._f_clock  = ("Menlo", 22, "bold")
            self._f_small  = ("Menlo", 7)

        # Canvas text items
        self._canvas.create_rectangle(0, 0, cw, 3*scale, fill="#282828", tag="bar")
        self._sid  = self._canvas.create_text(5*scale, 10*scale, text="",     fill="#CCC", font=self._f_bold,  anchor="nw")
        self._subid = self._canvas.create_text(5*scale, 26*scale, text="",    fill="#666", font=self._f_reg,   anchor="nw")
        self._rid   = self._canvas.create_text(5*scale, 36*scale, text="",    fill="#E6EBF0", font=self._f_reg, anchor="nw", width=(240-10)*scale)
        self._batid = self._canvas.create_text(cw-5*scale, 5*scale, text="—", fill="#666", font=self._f_small, anchor="ne")
        self._wfiid = self._canvas.create_text(5*scale, 5*scale, text="●",   fill="#00B450", font=self._f_small, anchor="nw")
        self._clkid = self._canvas.create_text(cw//2, 75*scale, text="",    fill="#DDD", font=self._f_clock, anchor="center")
        self._datid = self._canvas.create_text(cw//2, 105*scale, text="",   fill="#666", font=self._f_reg, anchor="center")
        self._hntid = self._canvas.create_text(cw//2, 222*scale, text="TEST MODE — press ENTER to talk", fill="#444", font=self._f_small, anchor="center")

        self._frame_count = 0
        self._render()

    def _render(self):
        s, sc, sc2, resp, accent = self._state, self._status_text, self._status_sub, self._response_buf, self._accent
        cw = self._w * self._scale

        self._canvas.itemconfig("bar", fill=accent)

        if s == "idle":
            now = datetime.now()
            self._canvas.itemconfig(self._sid,   text="")
            self._canvas.itemconfig(self._subid, text="")
            self._canvas.itemconfig(self._rid,   text="")
            self._canvas.itemconfig(self._clkid, text=now.strftime("%H:%M"))
            self._canvas.itemconfig(self._datid, text=now.strftime("%a, %b %d"))
            self._canvas.itemconfig(self._hntid, text="TEST MODE — press ENTER to talk")
            self._canvas.itemconfig(self._batid, text="—")
            self._canvas.itemconfig(self._wfiid, text="●")
        else:
            self._canvas.itemconfig(self._clkid, text="")
            self._canvas.itemconfig(self._datid, text="")
            self._canvas.itemconfig(self._hntid, text="")
            self._canvas.itemconfig(self._sid,   text=sc)
            self._canvas.itemconfig(self._subid, text=sc2 or "")
            self._canvas.itemconfig(self._rid,   text=resp or "")

        self._frame_count += 1
        self._root.after(80, self._render)

    def handle(self, msg: dict):
        t = msg.get("type", "")
        if t == "idle":
            self._state = "idle"
            self._status_text = ""
            self._status_sub = ""
            self._response_buf = ""
            self._accent = ACCENT_COLORS["idle"]
        elif t == "status":
            self._state = "status"
            self._status_text = msg.get("text", "")
            self._status_sub  = msg.get("sub", "")
            self._accent = msg.get("accent", ACCENT_COLORS["idle"])
            self._response_buf = ""
        elif t == "response":
            self._state = "talking"
            self._response_buf = msg.get("text", "")
            self._accent = ACCENT_COLORS["talking"]
        elif t == "append":
            self._response_buf += msg.get("delta", "")
        elif t == "character":
            self._state = msg.get("state", "idle")
            self._accent = ACCENT_COLORS.get(self._state, ACCENT_COLORS["idle"])
            self._status_text = STATE_LABELS.get(self._state, self._state.upper())
            self._status_sub = ""
        elif t == "clear":
            self._state = "idle"
            self._status_text = ""
            self._status_sub = ""
            self._response_buf = ""
        elif t == "accent":
            self._accent = msg.get("color", ACCENT_COLORS["idle"])

    def run(self):
        self._root.mainloop()


def main():
    sock_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/pizero-gui.sock"

    # Clean up stale socket
    if Path(sock_path).exists():
        Path(sock_path).unlink()

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(sock_path)
    srv.listen(1)

    gui = GUIPanel()
    t = threading.Thread(target=gui.run, daemon=True)
    t.start()

    buf = ""
    while True:
        try:
            conn, _ = srv.accept()
            buf = ""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, _, buf = buf.partition("\n")
                    line = line.strip()
                    if not line:
                        continue
                    if line == "QUIT":
                        conn.close()
                        Path(sock_path).unlink(missing_ok=True)
                        return
                    try:
                        msg = json.loads(line)
                        gui.handle(msg)
                    except json.JSONDecodeError:
                        pass
                conn.close()
        except Exception as e:
            break


if __name__ == "__main__":
    main()
