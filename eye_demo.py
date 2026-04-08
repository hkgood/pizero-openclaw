#!/usr/bin/env python3
"""
eye_demo.py — 胶囊眼睛角色本地预览

设计语言：
  · 两个竖向高瘦胶囊（白色粗描边，无填充，无眼珠）
  · 一个嘴巴（弧线 / 椭圆轮廓），随状态变化
  · 说话时嘴巴自然开合，眼睛同步变化
  · 简洁、可爱、流畅

键盘控制：
    1  idle      — 待机（呼吸 + 眨眼 + 微笑）
    2  listening — 聆听（蓝色光晕 + 小圆嘴）
    3  thinking  — 思考（眼睛压矮 + 三点等待 + 平嘴）
    4  talking   — 说话（眼 + 嘴随音量开合）
    5  happy     — 高兴（弦月眼 + 大笑弧 + 弹跳）
    6  sleep     — 休眠（扁线眼 + ZZZ + 小闭嘴）
    7  error     — 错误（抖动 + 皱眉）
    空格          — 自动循环所有状态
    a / ←         — talking 状态降低音量
    d / →         — talking 状态提高音量
    q / Esc       — 退出
"""

import math
import random
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont

try:
    from PIL import ImageTk as _PILImageTk
    _HAS_PIL_TK = True
except ImportError:
    _HAS_PIL_TK = False

# 从独立渲染核心导入所有常量、工具函数和 EyeRenderer
from eye_renderer import (
    W, H, FPS, BG, ACCENT, LABEL_TEXT, STATES,
    EYE_W, EYE_H, EYE_CY, EYE_L_CX, EYE_R_CX,
    MOUTH_CX, MOUTH_CY, SIG_CX, SIG_CY,
    EyeRenderer, _DEMO_ENVELOPE,
)

SCALE = 3




# ══════════════════════════════════════════════════════════════════════════════
# DemoWindow
# ══════════════════════════════════════════════════════════════════════════════

class DemoWindow:
    _AUTO_HOLD_SEC = 2.5

    def __init__(self):
        self._renderer      = EyeRenderer()
        self._state         = "idle"
        self._tick          = 0
        self._amplitude     = 0.4
        self._auto_cycle    = False
        self._auto_elapsed  = 0.0
        self._running       = True
        self._demo_idx      = 0    # 当前 demo 包络帧指针
        self._wifi_strength = 3    # WiFi 信号格数 0-3
        self._sys_connected = True # 系统连接状态（龙虾图标）

        self._root = tk.Tk()
        self._root.title(
            "eye_demo  |  1-7=状态  空格=自动  a/d=音量  w=WiFi  c=连接  i=加载图标  I=清除  q=退出"
        )
        self._root.resizable(False, False)
        self._root.configure(bg="#000")

        cw, ch = W * SCALE, H * SCALE
        self._canvas = tk.Canvas(self._root, width=cw, height=ch,
                                 bg="#000", highlightthickness=0)
        self._canvas.pack()
        self._img_id = self._canvas.create_image(0, 0, anchor="nw")
        self._tk_img = None

        self._info_var = tk.StringVar(value="")

        self._bind_keys()
        self._schedule()

    def _bind_keys(self):
        r = self._root
        r.bind("q",        lambda _: self._quit())
        r.bind("<Escape>", lambda _: self._quit())
        for key, state in zip("1234567", STATES):
            r.bind(key, lambda _, s=state: self._set_state(s))
        r.bind("<space>",  lambda _: self._toggle_auto())
        r.bind("a",        lambda _: self._adj_amp(-0.15))
        r.bind("d",        lambda _: self._adj_amp(+0.15))
        r.bind("<Left>",   lambda _: self._adj_amp(-0.15))
        r.bind("<Right>",  lambda _: self._adj_amp(+0.15))
        r.bind("w",        lambda _: self._cycle_wifi())
        r.bind("c",        lambda _: self._toggle_connected())
        r.bind("i",        lambda _: self._pick_icon())
        r.bind("I",        lambda _: self._renderer.clear_icon())

    def _set_state(self, s: str):
        self._state, self._auto_cycle = s, False
        self._auto_elapsed = self._tick = 0
        if s == "talking":
            self._demo_idx = 0   # 每次进入 talking 从头播放

    def _toggle_auto(self):
        self._auto_cycle   = not self._auto_cycle
        self._auto_elapsed = self._tick = 0

    def _adj_amp(self, d: float):
        self._amplitude = round(max(0.0, min(1.0, self._amplitude + d)), 2)

    def _cycle_wifi(self):
        """循环切换 WiFi 信号强度：3 → 2 → 1 → 0 → 3。"""
        self._wifi_strength = (self._wifi_strength - 1) % 4

    def _toggle_connected(self):
        """切换龙虾系统连接状态。"""
        self._sys_connected = not self._sys_connected

    def _pick_icon(self):
        """打开文件选择对话框，加载图标文件叠加到画面中央。"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择图标文件",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            ok = self._renderer.load_icon(path)
            print(f"[icon] {'已加载' if ok else '加载失败'}: {path}")

    def _quit(self):
        self._running = False
        self._root.quit()

    def _schedule(self):
        if not self._running:
            return
        self._render_frame()
        self._root.after(int(1000 / FPS), self._schedule)

    def _render_frame(self):
        if self._auto_cycle:
            self._auto_elapsed += 1.0 / FPS
            if self._auto_elapsed >= self._AUTO_HOLD_SEC:
                self._auto_elapsed = 0.0
                self._tick = 0
                idx = (STATES.index(self._state) + 1) % len(STATES)
                self._state = STATES[idx]
                if self._state == "talking":
                    self._demo_idx = 0

        # talking 状态：用 demo 包络驱动嘴部音量
        if self._state == "talking":
            self._amplitude = _DEMO_ENVELOPE[
                self._demo_idx % len(_DEMO_ENVELOPE)
            ]
            self._demo_idx += 1

        pil_img = self._renderer.draw_frame(
            self._state, self._tick, self._amplitude,
            wifi_strength=self._wifi_strength,
            sys_connected=self._sys_connected)
        if SCALE != 1:
            pil_img = pil_img.resize((W * SCALE, H * SCALE), Image.NEAREST)

        if _HAS_PIL_TK:
            self._tk_img = _PILImageTk.PhotoImage(pil_img)
        else:
            cw, ch = W * SCALE, H * SCALE
            raw   = pil_img.tobytes("raw", "RGB")
            photo = tk.PhotoImage(width=cw, height=ch)
            rows  = []
            for y in range(ch):
                row = []
                for x in range(cw):
                    i = (y * cw + x) * 3
                    row.append("#{:02x}{:02x}{:02x}".format(
                        raw[i], raw[i + 1], raw[i + 2]))
                rows.append("{" + " ".join(row) + "}")
            photo.put(" ".join(rows))
            self._tk_img = photo

        self._canvas.itemconfig(self._img_id, image=self._tk_img)

        self._tick += 1

    def run(self):
        self._root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import PIL
    if tuple(int(x) for x in PIL.__version__.split(".")[:2]) < (8, 2):
        print(f"WARNING: Pillow {PIL.__version__} < 8.2，建议 pip install -U Pillow")

    print(f"eye_demo  后端: {'PIL.ImageTk（快速）' if _HAS_PIL_TK else 'PhotoImage.put'}")
    print("键盘: 1-7 切换 | 空格 自动循环 | a/d 调音量 | w=WiFi | c=连接 | i=加载图标 | I=清除图标 | q 退出")
    print(f"窗口: {W*SCALE}×{H*SCALE}px")

    DemoWindow().run()
