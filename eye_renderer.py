#!/usr/bin/env python3
"""
eye_renderer.py — EyeRenderer 渲染核心。
供 display.py（真机）和 eye_demo.py（本地预览）共用。
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

W, H  = 240, 240
SCALE = 3
FPS   = 15

# ── 眼睛（竖向胶囊，无眼珠）─────────────────────────────────────────────────
EYE_W       = 31    # 胶囊宽度（原34 缩小约10%）
EYE_H       = 60    # 胶囊高度（原66 缩小约10%）
EYE_CY      = 98    # 眼睛垂直中心
EYE_L_CX    = 64    # 左眼水平中心
EYE_R_CX    = 176   # 右眼水平中心
OUTLINE_W   = 3     # 描边粗细

# ── 嘴巴 ─────────────────────────────────────────────────────────────────────
MOUTH_CX    = W // 2   # 嘴巴水平中心
MOUTH_CY    = 172      # 嘴巴垂直中心（原178 上移6px）

# ── 信号指示器（顶部居中，聆听/思考共用同一 Y 轴）──────────────────────────
SIG_CX = W // 2   # 信号/思考点水平中心
SIG_CY = 12       # 贴近屏幕顶边

BG = (8, 8, 14)        # 背景色（深黑蓝）

# ── 状态配色 ─────────────────────────────────────────────────────────────────
ACCENT = {
    "idle":      (200, 200, 212),
    "listening": (50,  120, 255),
    "thinking":  (215, 180,  28),
    "talking":   (24,  196, 100),
    "happy":     (255, 200,  76),
    "sleep":     (105, 105, 122),
    "error":     (218,  38,  38),
}

LABEL_TEXT = {
    "idle":      "idle",
    "listening": "listening",
    "thinking":  "thinking ...",
    "talking":   "talking",
    "happy":     "( ^ ▽ ^ )",
    "sleep":     "z z z",
    "error":     "! error !",
}

STATES = ["idle", "listening", "thinking", "talking", "happy", "sleep", "error"]

# ── 说话演示文本 & 音量包络 ───────────────────────────────────────────────────
_DEMO_TEXT = "大家好，我是王子，我是Rocky的助理"

def _build_speech_envelope(text: str) -> list:
    """
    将文本映射为逐帧音量包络（float 0-1）。
    每个汉字约 0.22s，标点停顿约 0.3s。
    """
    frames: list[float] = []
    for ch in text:
        if ch in "，,":
            frames.extend([0.0] * int(FPS * 0.30))
        elif ch in "。.！!？?":
            frames.extend([0.0] * int(FPS * 0.20))
        else:
            n = max(1, int(FPS * 0.22))
            for i in range(n):
                # sin 包络：快起慢落，自然发音感
                amp = math.sin(i / n * math.pi) * 0.50 + 0.38
                frames.append(float(amp))
    return frames

_DEMO_ENVELOPE: list[float] = _build_speech_envelope(_DEMO_TEXT)


# ── 基础绘图工具 ──────────────────────────────────────────────────────────────

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def capsule_outline(draw: ImageDraw.ImageDraw,
                    cx: float, cy: float, w: float, h: float,
                    color, lw: int = OUTLINE_W):
    """描边胶囊（无填充）。"""
    r = max(1.0, min(w, h) / 2)
    draw.rounded_rectangle(
        (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
        radius=r, fill=None, outline=color, width=lw,
    )


def capsule_fill(draw: ImageDraw.ImageDraw,
                 cx: float, cy: float, w: float, h: float, color):
    r = max(1.0, min(w, h) / 2)
    draw.rounded_rectangle(
        (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
        radius=r, fill=color,
    )


def glow_ellipse(img: Image.Image,
                 cx: float, cy: float, rx: float, ry: float,
                 color: tuple, layers: int = 5):
    r, g, b = color[:3]
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(layers, 0, -1):
        alpha  = int(22 * i / layers)
        factor = 1 + (layers - i + 1) * 0.28
        d.ellipse(
            (cx - rx * factor, cy - ry * factor,
             cx + rx * factor, cy + ry * factor),
            fill=(r, g, b, alpha),
        )
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


# ── 嘴巴绘图工具 ──────────────────────────────────────────────────────────────

def mouth_smile(draw: ImageDraw.ImageDraw,
                cx: float, cy: float, w: float,
                color, lw: int = 2):
    """下弧微笑线。w = 弧宽，弧高约 w/4。"""
    hw = w / 2
    hh = max(4.0, w / 4)
    # Pillow arc: 0→180 顺时针 = 椭圆下半弧 = 微笑 ✓
    draw.arc(
        (cx - hw, cy - hh, cx + hw, cy + hh),
        start=0, end=180, fill=color, width=lw,
    )


def mouth_frown(draw: ImageDraw.ImageDraw,
                cx: float, cy: float, w: float,
                color, lw: int = 2):
    """上弧皱眉线（180→360 = 上半弧）。"""
    hw = w / 2
    hh = max(4.0, w / 4)
    draw.arc(
        (cx - hw, cy - hh, cx + hw, cy + hh),
        start=180, end=360, fill=color, width=lw,
    )


def mouth_open(draw: ImageDraw.ImageDraw,
               cx: float, cy: float, w: float, h: float,
               color, lw: int = 2):
    """椭圆轮廓张嘴（水平椭圆）。"""
    if h < 4:
        # 太小时退化为横线
        draw.line(
            (cx - w / 2, cy, cx + w / 2, cy),
            fill=color, width=lw,
        )
    else:
        r = min(w, h) / 2
        draw.rounded_rectangle(
            (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
            radius=r, fill=None, outline=color, width=lw,
        )


def mouth_flat(draw: ImageDraw.ImageDraw,
               cx: float, cy: float, w: float,
               color, lw: int = 2):
    """平直横线嘴。"""
    draw.line((cx - w / 2, cy, cx + w / 2, cy), fill=color, width=lw)


# ── 状态栏图标 ────────────────────────────────────────────────────────────────

def _draw_wifi_icon(img: Image.Image,
                    x: int, y: int,
                    strength: int = 3,
                    base_color=(155, 175, 200)):
    """
    macOS 风格 WiFi 图标，超采样抗锯齿（4× → LANCZOS 缩回）。
    三层同心弧：内层实心扇形 + 中/外层等宽弧，两端圆头，110° 弧角。
    strength 0-3 控制亮起层数。结果直接合成到 img。
    """
    SC  = 4          # 超采样倍数
    IW  = 24         # 图标宽（1×）
    IH  = 19         # 图标高（1×）
    dim = (35, 38, 50)

    # ── 在 SC× 画布上绘制 ─────────────────────────────────
    tmp = Image.new("RGBA", (IW * SC, IH * SC), (0, 0, 0, 0))
    td  = ImageDraw.Draw(tmp)

    cx = 12 * SC     # 圆心 x
    by = 17 * SC     # 圆心 y（扇形基点，向上展开）

    AW = 3 * SC      # 弧线宽度
    r1 = 4 * SC      # 内扇形半径（实心）
    r2 = 9 * SC      # 中弧中线（gap=r2-AW/2-r1 = 9-1.5-4=3.5px ✓）
    r3 = 15 * SC     # 外弧中线（gap=r3-AW/2-r2-AW/2 = 15-1.5-9-1.5=3px ✓）
    S, E = 225, 315  # 90° 顶弧（对齐 macOS 标准角度）

    c1 = base_color if strength >= 1 else dim
    c2 = base_color if strength >= 2 else dim
    c3 = base_color if strength >= 3 else dim

    # 外 → 内绘制（LANCZOS 缩放已提供天然平滑，不额外加圆头）
    td.arc([cx-r3, by-r3, cx+r3, by+r3], start=S, end=E, fill=c3, width=AW)
    td.arc([cx-r2, by-r2, cx+r2, by+r2], start=S, end=E, fill=c2, width=AW)
    td.pieslice([cx-r1, by-r1, cx+r1, by+r1], start=S, end=E, fill=c1)

    # ── LANCZOS 缩回 1× 并 alpha 合成到主图 ──────────────
    icon = tmp.resize((IW, IH), Image.LANCZOS)
    img.paste(icon, (x, y), icon)


def _draw_claw_icon(draw: ImageDraw.ImageDraw,
                    rx: int, y: int,
                    connected: bool = True):
    """
    可爱卡通龙虾角色，22×22px。
    圆润大身体 + 两侧小钳 + 青色眼睛 + 细触角 + 短腿。
    connected=False 时整体压暗为深灰红。
    rx = 图标右边界 x。
    """
    lx = rx - 22

    if connected:
        bd  = (162, 32, 24)   # 身体阴影/深色
        bb  = (205, 52, 38)   # 身体基础红
        bm  = (228, 85, 65)   # 身体中调
        bh  = (248, 118, 92)  # 身体高光
        bsp = (255, 155, 122) # 身体亮点
        cl  = (178, 36, 26)   # 侧钳（比身体略深）
        clh = (210, 68, 52)   # 侧钳高光
        at  = (218, 80, 58)   # 触角
        ey  = (14, 14, 16)    # 眼睛黑色
        ehi = (0,  198, 172)  # 眼睛青色高光
    else:
        bd  = (48, 48, 52)    # 灰色调
        bb  = (72, 72, 78)
        bm  = (90, 90, 96)
        bh  = (110, 110, 118)
        bsp = (130, 130, 138)
        cl  = (58, 58, 64)
        clh = (80, 80, 86)
        at  = (82, 82, 88)
        ey  = (14, 14, 16)
        ehi = (95, 95, 100)

    # ── 触角（先画，身体覆盖底部）────────────────────────
    # 左触角：从头顶向左上弯曲
    draw.line([(lx+9,  y+5), (lx+7,  y+3)], fill=at, width=1)
    draw.line([(lx+7,  y+3), (lx+5,  y+1)], fill=at, width=1)
    # 右触角：向右上弯曲
    draw.line([(lx+13, y+5), (lx+15, y+3)], fill=at, width=1)
    draw.line([(lx+15, y+3), (lx+17, y+1)], fill=at, width=1)

    # ── 两侧小钳子（先画，身体覆盖内侧）─────────────────
    draw.ellipse([lx+0,  y+10, lx+6,  y+17], fill=cl)   # 左钳
    draw.ellipse([lx+16, y+10, lx+22, y+17], fill=cl)    # 右钳（lx+22=rx）
    draw.ellipse([lx+1,  y+11, lx+3,  y+13], fill=clh)  # 左钳高光
    draw.ellipse([lx+19, y+11, lx+21, y+13], fill=clh)  # 右钳高光

    # ── 圆润大身体（覆盖触角底部和钳子内侧）─────────────
    draw.ellipse([lx+3, y+4, lx+19, y+20], fill=bb)       # 主体
    # 上左高光区域（球面光感）
    draw.ellipse([lx+4,  y+5,  lx+13, y+13], fill=bm)
    draw.ellipse([lx+5,  y+6,  lx+11, y+12], fill=bh)
    draw.ellipse([lx+6,  y+7,  lx+9,  y+10], fill=bsp)
    draw.point  ((lx+7, y+8),                 fill=bsp)
    # 右下阴影
    draw.ellipse([lx+13, y+15, lx+18, y+20], fill=bd)

    # ── 短腿（从身体底部伸出两条）────────────────────────
    draw.rectangle([lx+8,  y+19, lx+10, y+21], fill=bd)
    draw.rectangle([lx+12, y+19, lx+14, y+21], fill=bd)

    # ── 眼睛：黑色圆 + 青色高光点 ────────────────────────
    draw.ellipse([lx+7,  y+8, lx+10, y+11], fill=ey)   # 左眼（3×3）
    draw.ellipse([lx+12, y+8, lx+15, y+11], fill=ey)   # 右眼（3×3）
    draw.point  ((lx+8,  y+9),               fill=ehi)  # 左眼青色
    draw.point  ((lx+9,  y+9),               fill=ehi)
    draw.point  ((lx+13, y+9),               fill=ehi)  # 右眼青色
    draw.point  ((lx+14, y+9),               fill=ehi)


# ── 字体 ──────────────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/oppo/OPPOSans4.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf".format(
            "-Bold" if bold else ""),
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


_FONT_LABEL = _load_font(11)


# ══════════════════════════════════════════════════════════════════════════════
# EyeRenderer
# ══════════════════════════════════════════════════════════════════════════════

class EyeRenderer:
    """状态 + tick → PIL Image (RGB 240×240)。"""

    def __init__(self):
        self._icon: Image.Image | None = None   # 叠加图标（RGBA）
        self._icon_pos: tuple[int, int] = (0, 0)

    def load_icon(self, path: str,
                  pos: tuple[int, int] = (W // 2 - 16, MOUTH_CY - 50),
                  max_size: int = 48) -> bool:
        """
        从文件加载图标并居中显示在画面上。
        支持 PNG / JPEG / GIF 等 Pillow 可读格式。
        pos = 图标左上角坐标；max_size = 最长边限制（像素）。
        返回 True 表示加载成功。
        """
        try:
            raw = Image.open(path).convert("RGBA")
            w, h = raw.size
            scale = min(max_size / w, max_size / h, 1.0)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            self._icon = raw.resize((nw, nh), Image.LANCZOS)
            # 默认让图标水平居中
            self._icon_pos = (pos[0] - nw // 2 + max_size // 2, pos[1])
            return True
        except Exception as e:
            print(f"[icon] 加载失败: {e}")
            self._icon = None
            return False

    def clear_icon(self):
        self._icon = None

    def draw_frame(self, state: str, tick: int,
                   amplitude: float = 0.0,
                   wifi_strength: int = 3,
                   sys_connected: bool = True) -> Image.Image:
        img  = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        t    = tick / FPS

        {
            "idle":      self._idle,
            "listening": self._listening,
            "thinking":  self._thinking,
            "talking":   self._talking,
            "happy":     self._happy,
            "sleep":     self._sleep,
            "error":     self._error,
        }.get(state, self._idle)(img, draw, t, amplitude)

        self._bottom_glow(img, state)

        # 叠加自定义图标（如果已加载）
        if self._icon is not None:
            x, y = self._icon_pos
            # 用 RGBA alpha 通道做蒙版，正确叠加到 RGB 底图
            base = img.convert("RGBA")
            base.paste(self._icon, (x, y), self._icon)
            img = base.convert("RGB")

        draw = ImageDraw.Draw(img)   # 光晕/图标合成后重建 draw 对象
        self._status_icons(img, draw, state, wifi_strength, sys_connected)
        return img

    # ── 各状态 ────────────────────────────────────────────────────────────────

    def _idle(self, img, draw, t, _amp):
        """待机：呼吸 + 眨眼 + 淡淡微笑。"""
        breathe = math.sin(t * 2 * math.pi / 3.0) * 2.0
        ew = EYE_W
        eh = EYE_H + breathe

        # 眨眼（约 160ms，高度上下压合）
        blink_t = t % 4.0
        if blink_t < 0.16:
            phase = blink_t / 0.08       # 0→1 闭合，1→2 张开
            eh = max(2.0, eh * (1 - phase) if phase <= 1.0
                          else eh * (phase - 1.0))

        col = ACCENT["idle"]
        for cx in (EYE_L_CX, EYE_R_CX):
            capsule_outline(draw, cx, EYE_CY, ew, eh, color=col)

        # 嘴：细小微笑弧，随呼吸微微拉宽
        smile_w = 22 + breathe * 0.8
        mouth_smile(draw, MOUTH_CX, MOUTH_CY, smile_w,
                    color=(160, 160, 172), lw=2)

    def _listening(self, img, draw, t, _amp):
        """聆听：眼睛略大偏蓝 + 两眼上方信号波动画 + 微笑不变。"""
        pulse   = math.sin(t * 2 * math.pi * 1.2) * 0.5 + 0.5
        breathe = math.sin(t * 2 * math.pi / 3.0) * 1.5

        ew  = EYE_W + 2 + pulse * 2
        eh  = EYE_H + breathe + 4 + pulse * 3
        brt = int(180 + pulse * 40)
        col = (brt - 40, brt - 20, brt)

        for cx in (EYE_L_CX, EYE_R_CX):
            capsule_outline(draw, cx, EYE_CY, ew, eh, color=col)

        mouth_smile(draw, MOUTH_CX, MOUTH_CY, 22,
                    color=(brt - 80, brt - 50, brt - 10), lw=2)

        # ── 信号接收动画：贴近顶边，3 道弧向下扩散（旋转 180°） ──
        # 基准点：屏幕顶部居中小点
        draw.ellipse((SIG_CX - 2, SIG_CY - 2, SIG_CX + 2, SIG_CY + 2),
                     fill=(80, 130, 240))
        for i in range(3):
            phase = (t * 1.6 - i * 0.28) % 1.0
            alpha = int(max(0.0, 1 - phase) * 190)
            if alpha < 12:
                continue
            r  = 6 + i * 8 + phase * 5
            rh = r * 0.6
            ca = int(alpha * 0.35)
            cb = alpha
            # 底弧：Pillow 0→180 顺时针 = 右→底→左 = 开口向下 ✓
            draw.arc(
                (SIG_CX - r, SIG_CY - rh, SIG_CX + r, SIG_CY + rh),
                start=0, end=180,
                fill=(ca, ca + 20, cb),
                width=2,
            )

    def _thinking(self, img, draw, t, _amp):
        """思考：眼睛轻微收窄（65%）+ 中性色 + 平嘴 + 极小暗点。"""
        # 眼睛收窄但不夸张，保持和 idle 的连续感
        eh = EYE_H * 0.65
        # 极缓慢的竖向微浮动，体现"内心转动"
        drift = math.sin(t * 0.7) * 1.2
        col   = (195, 192, 200)   # 中性白，不做色偏

        for cx in (EYE_L_CX, EYE_R_CX):
            capsule_outline(draw, cx, EYE_CY + drift, EYE_W, eh, color=col)

        # 嘴：和 idle 接近的微笑，仅略平一点点
        mouth_smile(draw, MOUTH_CX, MOUTH_CY, 20,
                    color=(140, 138, 148), lw=2)

        # ── 思考三点：屏幕顶部水平居中，与信号动画同一 Y 轴 ──
        dot_idx = int(t * 2.0) % 4
        for i, dx in enumerate((-13, 0, 13)):
            lit = i < dot_idx
            c   = (145, 138, 65) if lit else (32, 30, 18)
            x   = W // 2 + dx
            draw.ellipse((x - 3, SIG_CY - 3, x + 3, SIG_CY + 3), fill=c)

    def _talking(self, img, draw, t, amplitude):
        """说话：眼睛与 idle 完全一致，只有嘴部随音量自然开合。"""
        # 眼睛：完全沿用 idle 的呼吸动画和颜色
        breathe = math.sin(t * 2 * math.pi / 3.0) * 2.0
        eh  = EYE_H + breathe
        col = ACCENT["idle"]

        # 眨眼节奏同 idle
        blink_t = t % 4.0
        if blink_t < 0.16:
            phase = blink_t / 0.08
            eh = max(2.0, eh * (1 - phase) if phase <= 1.0
                          else eh * (phase - 1.0))

        for cx in (EYE_L_CX, EYE_R_CX):
            capsule_outline(draw, cx, EYE_CY, EYE_W, eh, color=col)

        # 嘴巴：微小自然开合，幅度克制
        jitter = math.sin(t * 20.0) * 0.04
        amp    = max(0.0, min(1.0, amplitude + jitter))
        mh     = lerp(0, 14, amp)   # 最大开口 14px，不夸张
        mw     = lerp(22, 28, amp)  # 宽度几乎不变
        mouth_open(draw, MOUTH_CX, MOUTH_CY, mw, mh,
                   color=(190, 192, 202), lw=2)

    def _happy(self, img, draw, t, _amp):
        """高兴：弦月眼（上弧）+ 大弧笑容 + 弹跳 + 两眼靠拢。"""
        bounce  = abs(math.sin(t * math.pi * 1.7)) * 8
        eye_y   = EYE_CY - int(bounce * 0.5)
        squeeze = int(bounce * 0.35)   # 两眼向中间靠拢
        lx      = EYE_L_CX + squeeze
        rx      = EYE_R_CX - squeeze

        ew, eh = EYE_W + 4, EYE_H
        col    = (255, 215, 80)

        for cx in (lx, rx):
            capsule_outline(draw, cx, eye_y, ew, eh, color=col)
            # 覆盖下半，保留上弧（弦月效果）
            draw.rectangle(
                (cx - ew / 2 - 1, eye_y,
                 cx + ew / 2 + 1, eye_y + eh / 2 + OUTLINE_W),
                fill=BG,
            )

        # 嘴：宽弧大笑（随弹跳微微拉宽）
        smile_w = 48 + bounce * 0.6
        mouth_smile(draw, MOUTH_CX, MOUTH_CY, smile_w,
                    color=(255, 210, 70), lw=3)


    def _sleep(self, img, draw, t, _amp):
        """休眠：眼睛压成细扁线 + 小闭嘴 + ZZZ 向上飘散。"""
        ew, eh = EYE_W + 14, 5
        for cx in (EYE_L_CX, EYE_R_CX):
            capsule_outline(draw, cx, EYE_CY, ew, eh,
                            color=ACCENT["sleep"], lw=2)

        # 嘴：微小闭合横线（睡着的平静感）
        mouth_flat(draw, MOUTH_CX, MOUTH_CY, 14,
                   color=(80, 80, 92), lw=2)

        # ZZZ 向上漂移渐隐
        for i in range(3):
            phase = (t * 0.55 + i * 0.38) % 1.0
            alpha = int(200 * (1 - phase))
            if alpha < 15:
                continue
            fy  = int(EYE_CY - 20 - phase * 60)
            fx  = W // 2 - 18 + i * 18
            sz  = 10 + i * 3
            dim = int(alpha * 0.52)
            draw.text((fx, fy), "z",
                      font=_load_font(sz, bold=True),
                      fill=(dim, dim, int(dim * 1.12)))

    def _error(self, img, draw, t, _amp):
        """错误：高频抖动 + 眼内 × + 皱眉嘴。"""
        shake = math.sin(t * math.pi * 7) * 5

        for cx in (EYE_L_CX, EYE_R_CX):
            ex  = cx + shake
            exi = int(ex)
            capsule_outline(draw, ex, EYE_CY, EYE_W, EYE_H,
                            color=ACCENT["error"])
            s = 9
            draw.line((exi - s, EYE_CY - s, exi + s, EYE_CY + s),
                      fill=(80, 16, 16), width=3)
            draw.line((exi + s, EYE_CY - s, exi - s, EYE_CY + s),
                      fill=(80, 16, 16), width=3)

        # 嘴：皱眉（上弧），随抖动微移
        mouth_frown(draw, MOUTH_CX + shake * 0.3, MOUTH_CY, 26,
                    color=(200, 50, 50), lw=2)

    # ── 装饰层 ────────────────────────────────────────────────────────────────

    def _status_icons(self, img: Image.Image, draw: ImageDraw.ImageDraw,
                      state: str, wifi_strength: int, sys_connected: bool):
        """底部状态线 + 左上角 WiFi 图标（超采样）+ 右上角龙虾图标。"""
        _draw_wifi_icon(img, x=12, y=7, strength=wifi_strength,
                        base_color=(55, 210, 100))
        _draw_claw_icon(draw, rx=W - 12, y=7, connected=sys_connected)
        draw.rectangle((0, H - 3, W, H), fill=ACCENT.get(state, ACCENT["idle"]))

    def _bottom_glow(self, img: Image.Image, state: str):
        """底部椭圆光晕：从屏幕底部渗出，多层叠加，柔和自然。"""
        r, g, b = ACCENT.get(state, ACCENT["idle"])
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        cx = W // 2
        # 光晕中心稍微低于屏幕底部，让它看起来是"从底下透上来"
        for i in range(7):
            alpha = int(30 * (7 - i) / 7)
            rx    = int(W * 0.52 * (1 + i * 0.16))
            ry    = int(28 * (1 + i * 0.28))
            cy    = H + ry // 2        # 中心在底边以下
            d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry),
                      fill=(r, g, b, alpha))
        img.paste(
            Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        )

    def _label(self, draw: ImageDraw.ImageDraw, state: str, t: float):
        text   = LABEL_TEXT.get(state, state)
        accent = ACCENT.get(state, (80, 80, 95))
        if state == "listening":
            fade   = math.sin(t * math.pi * 2.8) * 0.28 + 0.72
            accent = tuple(int(c * fade) for c in accent)
        try:
            tw = _FONT_LABEL.getlength(text)
        except AttributeError:
            tw = len(text) * 7
        draw.text((int((W - tw) / 2), H - 20), text,
                  font=_FONT_LABEL, fill=accent)


# ══════════════════════════════════════════════════════════════════════════════
# DemoWindow
# ══════════════════════════════════════════════════════════════════════════════

