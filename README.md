# pizero-openclaw

一个基于 Raspberry Pi Zero W + [PiSugar WhisPlay](https://www.pisugar.com) 的语音控制 AI 助手。按住按钮说话，LCD 实时显示回复并朗读——由 [OpenClaw](https://openclaw.ai) 和**阿里云百炼**驱动。

支持**百炼 FunASR 语音识别** + **Qwen TTS 语音合成**，OpenAI 作为备选。

## 工作流程

```
按住按钮 → 录音 → 语音转文字 (FunASR) → 流式 LLM 回复 (OpenClaw) → LCD 实时显示
                                                                        → 语音朗读 (Qwen TTS，可选)
```

1. **按住按钮** 通过 ALSA 录音
2. **松开** — WAV 发送至 FunASR 进行语音转文字 (~0.7s)
3. 文字发送至 **OpenClaw Gateway**，通过新版 WebSocket `chat.send` 流式获取回复
4. 回复文字实时流式显示在 **LCD** 上，精确像素级自动换行
5. 句子完成后通过 **Qwen TTS** 朗读回复
6. 空闲屏幕显示 **时钟、日期、电量、WiFi 状态**

支持**多轮对话记忆**，内置**静音检测**过滤空白录音。

## 硬件要求

- **Raspberry Pi Zero 2 W**（或 Pi Zero W）
- **[PiSugar WhisPlay board](https://www.pisugar.com)** — 1.54" LCD (240x240)、按键、LED、扬声器、麦克风
- **PiSugar 电池**（可选）— 显示电量

## 快速开始

### 一键安装（任意终端，一行命令）

```bash
curl -fsSL https://raw.githubusercontent.com/hkgood/pizero-openclaw/main/install.sh -o /tmp/install.sh && chmod +x /tmp/install.sh && /tmp/install.sh
```

> ⚠️ 不要直接 `curl | bash`（不支持交互输入），请先下载再运行。

`install.sh` 会自动克隆仓库并运行安装向导。没有 WhisPlay 硬件的机器会自动进入**测试模式**。

**非交互式安装（CI / 自动化）：**
```bash
DASHSCOPE_API_KEY=your-key OPENCLAW_PASSWORD=your-password \
  ./install.sh --non-interactive
```

**环境变量说明：**
- `DASHSCOPE_API_KEY` — 阿里云百炼 API Key
- `OPENCLAW_TOKEN` — OpenClaw Gateway Token（和服务端 `auth.mode=token` 对应）
- `OPENCLAW_PASSWORD` — OpenClaw Gateway Password（和服务端 `auth.mode=password` 对应）
- `OPENCLAW_BASE_URL` — Gateway 地址。远程场景推荐保持 `http://127.0.0.1:18789`，通过 SSH 隧道转发。
- `OPENCLAW_USE_DEVICE_IDENTITY` — 新版默认 `true`。首次连接可能生成待批准配对，批准一次后自动复用本地身份和 `deviceToken`
- `INSTALL_BRANCH` — Git 分支（默认 `main`）
- `ENABLE_AUTOSTART` — 非交互模式下自动设置 systemd 自启动（`true`）

### 克隆后本地安装

```bash
git clone https://github.com/hkgood/pizero-openclaw.git
cd pizero-openclaw
chmod +x setup.sh install.sh
./setup.sh
```

`setup.sh` 会自动：
- 检测硬件环境（Raspberry Pi / macOS / Linux / Docker）
- 安装系统依赖（需要 sudo 权限，会提前提示）
- 安装 Python 依赖（基础 + 硬件专用）
- 引导配置 API Key
- 根据硬件情况选择运行模式
- 询问并设置 systemd 开机自启动（仅 Raspberry Pi / Linux）

### 测试模式（Mac / 无 WhisPlay 硬件）

在没有 WhisPlay 的机器上（macOS / Linux / 树莓派未装驱动），程序自动进入**测试模式**：

- **GUI 模拟窗口**：Tkinter 渲染 240×240 等比放大 3 倍的模拟 LCD
- **文本输入代替录音**：Console 输入文字按回车发送
- **完整 LLM 流程**：语音识别 → 流式回复 → 显示，全流程可测试

```bash
# 自动检测（推荐）
./run-openclaw.sh

# 手动强制测试模式
export TEST_MODE=true
./run-openclaw.sh
```

## 手动安装

### 1. 克隆代码

```bash
git clone https://github.com/hkgood/pizero-openclaw.git
cd pizero-openclaw
```

### 2. 安装系统依赖

```bash
# Raspberry Pi / Debian / Ubuntu
sudo apt update
sudo apt install python3-numpy python3-pil python3-pip alsa-utils sox libsox-fmt-all git curl

# macOS（需要先安装 homebrew）
brew install sox ffmpeg
```

安装向导会在需要 sudo 时提前提示密码。如果当前用户没有 sudo 权限，可以跳过（部分功能可能受限）。

### 3. 安装 Python 依赖

```bash
# 基础依赖
pip3 install -r requirements.txt

# Raspberry Pi 硬件依赖（仅 Pi 环境需要）
pip3 install -r requirements-pi.txt

# 或者一起安装：
pip3 install -r requirements.txt -r requirements-pi.txt
```

### 4. 配置

```bash
cp .env.example .env
```

编辑 `.env` 填写 Key：

```bash
# 阿里云百炼（默认，推荐）
export DASHSCOPE_API_KEY="your-bailian-api-key"

# OpenClaw（共享认证二选一；真实密码只放本地 .env，不要提交）
# token 模式：
export OPENCLAW_TOKEN="your-openclaw-gateway-token"
# password 模式：
export OPENCLAW_PASSWORD="your-openclaw-gateway-password"

# 官方推荐的远程方式：Gateway 保持 loopback，
# 设备端通过 SSH 隧道访问本地 127.0.0.1:18789
export OPENCLAW_BASE_URL="http://127.0.0.1:18789"
# 3.31+ 推荐：共享认证 + device identity 一起使用
export OPENCLAW_USE_DEVICE_IDENTITY="true"
export OPENCLAW_IDENTITY_FILE="~/.openclaw/identity/device.json"
export OPENCLAW_DEVICE_TOKEN_FILE="~/.openclaw/identity/device-auth.json"
export OPENCLAW_PAIRING_STATE_FILE="~/.openclaw/pizero/pairing-state.json"
export OPENCLAW_SESSION_KEY="main"
```

> API Key 获取地址：
> - 百炼：https://bailian.console.aliyun.com/
> - OpenClaw：http://127.0.0.1:18789 配置页（如果是远程 Gateway，请先建立 SSH 隧道）

### 官方推荐的远程连接方式

如果 OpenClaw Gateway 跑在另一台机器上，官方当前推荐：

1. 让 Gateway 保持 `bind: "loopback"`
2. 在设备端建立 SSH 隧道
3. 设备端继续把 `OPENCLAW_BASE_URL` 设为 `http://127.0.0.1:18789`
4. 在客户端握手里显式带上共享 `token` 或 `password`
5. 同时附带本地 `device identity`，首次连接可能需要批准一次配对
6. 配对完成后，客户端会把 Gateway 返回的 `deviceToken` 持久化到本地，后续重连更稳

例如从 Pi Zero 连接 Orange Pi：

```bash
ssh -N -L 18789:127.0.0.1:18789 rocky@100.108.209.26
```

这样做的原因：

- 不需要把 Gateway 直接暴露到 LAN/Tailnet 的 `18789`
- 和最新 OpenClaw 文档的 `Remote over SSH` / `loopback + Serve` 策略一致
- 能让 Pi Zero 走官方 3.31+ 的单次 `connect.challenge -> connect` 握手，而不是旧版双 `connect`
- 首次接入时如果返回 `NOT_PAIRED`，请求会落到本地 `OPENCLAW_PAIRING_STATE_FILE`，方便查看 `requestId`
- 一旦批准配对，后续就会稳定复用本地 `device identity` 和已缓存的 `deviceToken`

### 首次配对会发生什么

第一次把一台新的 Pi Zero 接到 Gateway 时，常见流程是：

1. Pi Zero 建立 SSH 隧道并连接 Gateway
2. Gateway 返回 `NOT_PAIRED`，同时生成待批准请求
3. 客户端把这次请求写入 `OPENCLAW_PAIRING_STATE_FILE`
4. 你在 Gateway 侧批准该设备
5. Pi Zero 下次重连时成功拿到 `deviceToken`，之后进入稳定工作状态

这属于正常行为，不是故障。

### 5. 运行

```bash
./run-openclaw.sh
```

### 6. 部署 systemd 服务（Pi）

安装向导支持自动设置自启动（交互模式下会询问），也可手动完成：

```bash
# 方式 A：安装向导自动设置（推荐）
./setup.sh
# 选择"是否设置开机自启动" → yes

# 方式 B：手动设置
# 编辑服务文件（路径和用户名），然后：
sudo cp pizero-openclaw.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pizero-openclaw
sudo systemctl start pizero-openclaw
```

**远程部署（从 Mac 推送到 Pi）：**
```bash
./sync.sh
# 或指定主机：
PI_HOST=pi@192.168.1.100 ./sync.sh
```

**查看日志：**
```bash
sudo journalctl -u pizero-openclaw -f
```

**其他常用命令：**
```bash
sudo systemctl status pizero-openclaw   # 查看状态
sudo systemctl restart pizero-openclaw   # 重启
sudo systemctl disable pizero-openclaw  # 取消自启
```

## 安装流程图

```
┌─────────────────────────────────────────────┐
│  curl -fsSL .../install.sh -o install.sh   │
│  chmod +x install.sh && ./install.sh       │
└─────────────────┬───────────────────────────┘
                  ▼
┌─────────────────────────────────────────────┐
│  检测环境（TTY / GitHub 下载 / 已有目录）  │
└─────────────────┬───────────────────────────┘
                  ▼
┌─────────────────────────────────────────────┐
│  克隆 / 更新代码到 ~/pizero-openclaw       │
└─────────────────┬───────────────────────────┘
                  ▼
┌─────────────────────────────────────────────┐
│  setup.sh — 自动化安装向导                  │
│  ├── 检测平台 (RPi / macOS / Linux / Docker) │
│  ├── 预检 sudo 权限                         │
│  ├── 安装系统依赖                          │
│  ├── 安装 Python 依赖（基础 + 硬件）        │
│  ├── 配置 API Key                          │
│  ├── 验证安装                              │
│  └── 设置 systemd 开机自启动（可选）        │
└─────────────────┬───────────────────────────┘
                  ▼
┌─────────────────────────────────────────────┐
│  完成 → ./run-openclaw.sh 启动             │
                  ▼
┌─────────────────────────────────────────────┐
│  完成 → ./run-openclaw.sh 启动             │
└─────────────────────────────────────────────┘
```

## Docker 环境

在 Docker 中运行时需要注意音频设备映射：

```bash
docker run --device /dev/snd:/dev/snd \
           -e ALSA_CARD=0 \
           your-image
```

或者使用 ALSA 环境变量映射到主机设备。安装脚本会检测 Docker 环境并给出相应提示。

## 配置参数

所有配置通过环境变量（`.env`）管理：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `STT_PROVIDER` | `funasr` | 语音识别：`funasr` 或 `openai` |
| `TTS_PROVIDER` | `bailian` | 语音合成：`bailian` 或 `openai` |
| `DASHSCOPE_API_KEY` | （必填）| 阿里云百炼 API Key |
| `BAILIAN_TTS_MODEL` | `qwen3-tts-flash` | 百炼 TTS 模型 |
| `BAILIAN_TTS_VOICE` | `Cherry` | 百炼 TTS 音色 |
| `BAILIAN_TTS_SPEED` | `1.0` | TTS 语速 |
| `OPENAI_API_KEY` | — | OpenAI API Key（备选）|
| `OPENAI_TRANSCRIBE_MODEL` | `whisper-1` | OpenAI Whisper 模型 |
| `OPENAI_TTS_MODEL` | `tts-1` | OpenAI TTS 模型 |
| `OPENAI_TTS_VOICE` | `coral` | OpenAI TTS 音色 |
| `OPENCLAW_TOKEN` | — | OpenClaw Gateway Token（token 模式） |
| `OPENCLAW_PASSWORD` | — | OpenClaw Gateway Password（password 模式） |
| `OPENCLAW_BASE_URL` | `http://127.0.0.1:18789` | OpenClaw Gateway 地址；远程推荐配合 SSH 隧道 |
| `OPENCLAW_USE_DEVICE_IDENTITY` | `true` | 3.31+ 推荐开启；首次接入可能需要批准一次配对 |
| `OPENCLAW_IDENTITY_FILE` | `~/.openclaw/identity/device.json` | 本地设备身份文件 |
| `OPENCLAW_DEVICE_TOKEN_FILE` | `~/.openclaw/identity/device-auth.json` | 已批准后缓存的 deviceToken |
| `OPENCLAW_PAIRING_STATE_FILE` | `~/.openclaw/pizero/pairing-state.json` | 首次待批准配对状态文件 |
| `OPENCLAW_SESSION_KEY` | `main` | `chat.send` 使用的会话键 |
| `WHISPLAY_DRIVER_PATH` | `~/Whisplay/Driver` | WhisPlay 驱动路径 |
| `ENABLE_TTS` | `true` | 是否开启语音朗读 |
| `TEST_MODE` | `false` | 测试模式（无硬件时自动开启）|
| `CONVERSATION_HISTORY_LENGTH` | `5` | 对话历史最大轮数 |
| `MAX_CONTEXT_TOKENS` | `16000` | 对话历史最大 token 数（防超出 context）|
| `LCD_BACKLIGHT` | `70` | 屏幕亮度 (0–100) |
| `AUDIO_DEVICE` | `plughw:1,0` | ALSA 输入设备 |
| `SILENCE_RMS_THRESHOLD` | `200` | 静音阈值 |

## 百炼 vs OpenAI

| | 阿里云百炼（默认）| OpenAI（备选）|
|---|---|---|
| STT | FunASR（有免费额度）| Whisper API |
| TTS | Qwen TTS | GPT-4o TTS |
| 推荐 | ✅ 推荐 | 备选 |

切换到 OpenAI：
```bash
export STT_PROVIDER="openai"
export TTS_PROVIDER="openai"
export OPENAI_API_KEY="sk-..."
```

## 故障排除

### 安装时提示 sudo 密码
安装向导会在需要 sudo 权限前提前提示。如果跳过，部分系统包会安装失败，但 Python 依赖仍可继续。

### `ModuleNotFoundError: No module named 'WhisPlay'`
WhisPlay 驱动未安装，程序自动切换到**测试模式**。如需硬件模式：
```bash
export WHISPLAY_DRIVER_PATH=~/Whisplay/Driver
```

### `No module named 'spidev'` 或 `No module named 'RPi'`
```bash
# 基础依赖（可能已有）
pip3 install -r requirements.txt
# Pi 硬件依赖
pip3 install -r requirements-pi.txt
```

### `PermissionError: ... log file`
日志文件被其他用户创建：
```bash
rm -f ~/.local/state/pizero-openclaw.log
```

### 首次连接报 `NOT_PAIRED`
这是新版链路的正常首连状态，不是“密码模式不能连”。

```bash
# 查看本地记录下来的待批准请求
cat ~/.openclaw/pizero/pairing-state.json
```

只要在 Gateway 侧批准这台设备一次，后续重连就会恢复正常。

### WhisPlay 按钮无反应
可能是 GPIO 中断注册失败，WhisPlay 驱动会自动降级到轮询，不影响使用。

### Docker 中无音频设备
```bash
# 方案 A：映射 ALSA 设备
docker run --device /dev/snd:/dev/snd your-image

# 方案 B：使用 PulseAudio
docker run -e PULSE_SERVER=unix:/run/user/1000/pulse/pulseaudio.socket ...

# 方案 C：只运行测试模式（不需要音频）
export TEST_MODE=true && ./run-openclaw.sh
```

### 安装验证失败
如果 `setup.sh` 结尾验证有警告，可手动检查：
```bash
# 检查 Python 包
python3 -c "import numpy; import PIL; import dotenv; import requests; print('OK')"

# 重新安装依赖
pip3 install -r requirements.txt -r requirements-pi.txt
```

## 项目结构

```
main.py               — 入口、流程编排、测试模式
display.py            — LCD 渲染（状态、回复、时钟、精灵动画）
display_mock.py       — 测试模式 WhisPlay 模拟接口
gui_display.py        — 测试模式 GUI 窗口（Tkinter，独立进程）
openclaw_client.py   — OpenClaw Gateway WebSocket 客户端（challenge / pairing / chat.send）
transcribe_openai.py — 语音识别（FunASR / Whisper，自动重试）
tts_openai.py        — 语音合成（Bailian Qwen TTS / OpenAI TTS）
record_audio.py       — ALSA 录音，文件权限 600 保护隐私
button_ptt.py         — 按键状态机（PTT）
config.py             — 集中配置（从 .env 加载）
setup.sh             — 自动化安装向导（交互 + 非交互）
install.sh           — 一键安装入口（curl 下载再运行）
run-openclaw.sh      — 启动脚本（兼容 systemd EnvironmentFile）
sync.sh              — 部署脚本（rsync + systemd）
pizero-openclaw.service — systemd 服务模板
requirements.txt      — 基础依赖
requirements-pi.txt   — Raspberry Pi 硬件依赖（不含 dashscope）
.env.example          — 配置模板
```

## License

MIT
