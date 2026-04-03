#!/usr/bin/env python3
"""
test_input.py — 测试模式 pygame 虚拟 PTT（tap-to-talk）
单击空格：IDLE → LISTENING（开始）→ LISTENING → TRANSCRIBING（输入文字）
"""
import json
import socket
import sys

try:
    import pygame
    pygame.init()
    pygame.font.init()
except Exception as e:
    print(f"[test_input] pygame 初始化失败: {e}")
    sys.exit(1)

SOCK_PATH = "/tmp/pizero-test-input.sock"
W, H = 260, 300
RADIUS = 80

def main():
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("pizero-openclaw TEST MODE")
    font = pygame.font.SysFont("Menlo", 13)
    font_big = pygame.font.SysFont("Menlo", 22)
    font_hint = pygame.font.SysFont("Menlo", 10)

    phase = "idle"  # idle | listening | typing
    clock = pygame.time.Clock()

    while True:
        clock.tick(60)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                _send({"type": "quit"})
                pygame.quit()
                return
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    _send({"type": "quit"})
                    pygame.quit()
                    return
                if event.key == pygame.K_SPACE:
                    if phase == "idle":
                        phase = "listening"
                        _send({"type": "state", "phase": "listening"})
                    elif phase == "listening":
                        phase = "typing"
                        _send({"type": "state", "phase": "typing"})
                    elif phase == "typing":
                        # 再次单击表示重新开始
                        phase = "listening"
                        _send({"type": "state", "phase": "listening"})

        screen.fill((15, 15, 20))

        # 标题
        t = font_hint.render("pizero-openclaw TEST MODE", True, (80, 80, 90))
        screen.blit(t, (W // 2 - t.get_width() // 2, 10))

        # 底部状态文字
        if phase == "idle":
            st_txt, st_color = "TAP SPACE to start", (80, 80, 90)
        elif phase == "listening":
            st_txt, st_color = "TAP SPACE to send", (60, 140, 255)
        else:
            st_txt, st_color = "type + ENTER to send", (0, 200, 100)
        st = font.render(st_txt, True, st_color)
        screen.blit(st, (W // 2 - st.get_width() // 2, H - 48))

        # 圆形按钮
        btn_color = {
            "idle": (50, 50, 60),
            "listening": (60, 140, 255),
            "typing": (0, 200, 100),
        }[phase]
        cx, cy = W // 2, H // 2 - 5
        pygame.draw.circle(screen, btn_color, (cx, cy), RADIUS)
        pygame.draw.circle(screen, (25, 25, 35), (cx, cy), RADIUS, 3)

        label = {"idle": "TAP", "listening": "TAP", "typing": "SEND"}[phase]
        mic = font_big.render(label, True, (255, 255, 255))
        mr = mic.get_rect(center=(cx, cy))
        screen.blit(mic, mr)

        # 麦克风辅助图标
        if phase == "listening":
            sub = font_hint.render("now recording", True, (60, 140, 255))
            sub_r = sub.get_rect(center=(cx, cy + 30))
            screen.blit(sub, sub_r)

        # 提示
        hints = []
        if phase == "idle":
            hints = ["TAP SPACE", "to start recording"]
        elif phase == "listening":
            hints = ["TAP SPACE", "to stop & send"]
        else:
            hints = ["type in terminal", "ENTER to send"]
        y = cy + RADIUS + 12
        for h in hints:
            s = font_hint.render(h, True, (220, 220, 220))
            screen.blit(s, (W // 2 - s.get_width() // 2, y))
            y += 15

        esc = font_hint.render("ESC = quit", True, (55, 55, 65))
        screen.blit(esc, (12, H - 22))

        pygame.display.flip()


def _send(msg: dict):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(SOCK_PATH)
        s.sendall((json.dumps(msg) + "\n").encode())
        s.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
