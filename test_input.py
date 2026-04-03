"""
test_input.py — 测试模式专用：pygame 虚拟 PTT 按键 + 终端文本输入
按住空格(hold-to-talk) → 终端输入文字 → 回车发送
"""
import sys
import threading

try:
    import pygame
    pygame.init()
except Exception as e:
    print("[test_input] pygame 未安装，请运行: pip3 install pygame")
    print("Error:", e)
    sys.exit(1)


from enum import Enum


class State(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"


class TestInput:
    W = 260
    H = 300
    RADIUS = 80
    BG = (15, 15, 20)
    BTN_IDLE = (50, 50, 60)
    BTN_LISTENING = (60, 140, 255)
    BTN_TRANSCRIBING = (0, 200, 100)
    TEXT_COLOR = (220, 220, 220)
    DIM_COLOR = (80, 80, 90)

    def __init__(self):
        pygame.font.init()
        self.screen = pygame.display.set_mode((self.W, self.H))
        pygame.display.set_caption("pizero-openclaw TEST MODE")
        self.font = pygame.font.SysFont("Menlo", 13)
        self.font_mic = pygame.font.SysFont("Menlo", 20)
        self.font_hint = pygame.font.SysFont("Menlo", 10)

        self.state = State.IDLE
        self._lock = threading.Lock()
        self._running = True
        self._result = ""
        self._input_done = threading.Event()
        self._clock = pygame.time.Clock()

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            self._clock.tick(60)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                    pygame.quit()
                    return
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._running = False
                        pygame.quit()
                        return
                    if event.key == pygame.K_SPACE and self.state == State.IDLE:
                        self._on_press()
                elif event.type == pygame.KEYUP:
                    if event.key == pygame.K_SPACE and self.state == State.LISTENING:
                        self._on_release()
            self._draw()
        try:
            pygame.quit()
        except Exception:
            pass

    def _on_press(self):
        with self._lock:
            self.state = State.LISTENING

    def _on_release(self):
        with self._lock:
            self.state = State.TRANSCRIBING
        print("")
        print("-" * 40)
        print("  Release SPACE - type your message in the terminal below")
        print("-" * 40)
        t = threading.Thread(target=self._do_input, daemon=True)
        t.start()

    def _do_input(self):
        try:
            line = sys.stdin.readline()
            text = line.strip() if line else ""
        except Exception:
            text = ""
        with self._lock:
            self._result = text
            self._input_done.set()
            self.state = State.IDLE

    def _draw(self):
        self.screen.fill(self.BG)

        title = self.font_hint.render("pizero-openclaw TEST MODE", True, self.DIM_COLOR)
        self.screen.blit(title, ((self.W - title.get_width()) // 2, 10))

        if self.state == State.IDLE:
            st_txt = "hold SPACE to talk"
            st_color = self.DIM_COLOR
        elif self.state == State.LISTENING:
            st_txt = "RELEASE to send"
            st_color = self.BTN_LISTENING
        elif self.state == State.TRANSCRIBING:
            st_txt = "type + ENTER in terminal"
            st_color = self.BTN_TRANSCRIBING
        st = self.font.render(st_txt, True, st_color)
        self.screen.blit(st, ((self.W - st.get_width()) // 2, self.H - 48))

        with self._lock:
            if self.state == State.IDLE:
                btn_color = self.BTN_IDLE
            elif self.state == State.LISTENING:
                btn_color = self.BTN_LISTENING
            elif self.state == State.TRANSCRIBING:
                btn_color = self.BTN_TRANSCRIBING

        cx = self.W // 2
        cy = self.H // 2 - 5
        pygame.draw.circle(self.screen, btn_color, (cx, cy), self.RADIUS)
        pygame.draw.circle(self.screen, (25, 25, 35), (cx, cy), self.RADIUS, 3)

        label = "MIC"
        if self.state == State.LISTENING:
            label = "REC"
        elif self.state == State.TRANSCRIBING:
            label = "SEND"
        mic = self.font_mic.render(label, True, (255, 255, 255))
        mr = mic.get_rect(center=(cx, cy))
        self.screen.blit(mic, mr)

        hints = []
        if self.state == State.IDLE:
            hints = ["HOLD SPACE to talk", "ESC to quit"]
        elif self.state == State.LISTENING:
            hints = ["RELEASE SPACE", "to send"]
        elif self.state == State.TRANSCRIBING:
            hints = ["type in terminal", "ENTER to send"]
        y = cy + self.RADIUS + 12
        for h in hints:
            s = self.font_hint.render(h, True, self.TEXT_COLOR)
            self.screen.blit(s, ((self.W - s.get_width()) // 2, y))
            y += 15

        esc = self.font_hint.render("ESC = quit", True, (55, 55, 65))
        self.screen.blit(esc, (12, self.H - 22))

        pygame.display.flip()

    def close(self):
        self._running = False
        try:
            pygame.quit()
        except Exception:
            pass
