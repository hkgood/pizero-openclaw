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
3. 文字（带对话历史）发送至 **OpenClaw gateway** 流式获取回复
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
curl -fsSL https://raw.githubusercontent.com/hkgood/pizero-openclaw/main/install.sh | bash
```

`install.sh` 会自动克隆仓库并运行安装向导。没有 WhisPlay 硬件的机器会自动进入**测试模式**。

非交互式安装（CI / 自动化）：
```bash
DASHSCOPE_API_KEY=your-key OPENCLAW_TOKEN=your-token \
  ./install.sh --non-interactive
```

### 克隆后本地安装

```bash
git clone https://github.com/hkgood/pizero-openclaw.git
cd pizero-openclaw
chmod +x setup.sh install.sh
./setup.sh
```

`setup.sh` 会自动：
- 检测硬件环境（Raspberry Pi / macOS / Linux）
- 安装系统依赖和 Python 依赖
- 引导配置 API Key
- 根据硬件情况选择运行模式

## 测试模式（Mac / 无 WhisPlay 硬件）

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

### 2. 安装系统包

```bash
# Raspberry Pi
sudo apt update
sudo apt install python3-numpy python3-pil python3-pip alsa-utils sox libsox-fmt-all git curl

# macOS（需要先安装 homebrew）
brew install sox
```

### 3. 安装 Python 包

```bash
# 基础依赖
pip3 install -r requirements.txt

# Raspberry Pi 硬件依赖
pip3 install -r requirements-pi.txt
```

### 4. 配置

```bash
cp .env.example .env
```

编辑 `.env` 填写 Key：

```bash
# 阿里云百炼（默认，推荐）
export DASHSCOPE_API_KEY="your-bailian-api-key"

# OpenClaw（必填）
export OPENCLAW_TOKEN="your-openclaw-gateway-token"
```

> API Key 获取地址：
> - 百炼：https://bailian.console.aliyun.com/
> - OpenClaw：http://localhost:18789 配置页

### 5. 运行

```bash
./run-openclaw.sh
```

### 6. 部署 systemd 服务（Pi）

编辑 `pizero-openclaw.service` 里的路径和用户名，然后：

```bash
./sync.sh
# 或指定主机：
PI_HOST=pi@192.168.1.100 ./sync.sh
```

查看日志：
```bash
sudo journalctl -u pizero-openclaw -f
```

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
| `OPENCLAW_TOKEN` | （必填）| OpenClaw Gateway Token |
| `OPENCLAW_BASE_URL` | `http://localhost:18789` | OpenClaw Gateway 地址 |
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

### `ModuleNotFoundError: No module named 'WhisPlay'`
WhisPlay 驱动未安装，程序自动切换到**测试模式**。如需硬件模式：
```bash
export WHISPLAY_DRIVER_PATH=~/Whisplay/Driver
```

### `No module named 'spidev'` 或 `No module named 'RPi'`
```bash
pip install -r requirements-pi.txt
```

### `PermissionError: ... log file`
日志文件被其他用户创建：
```bash
rm -f ~/.local/state/pizero-openclaw.log
```

### WhisPlay 按钮无反应
可能是 GPIO 中断注册失败，WhisPlay 驱动会自动降级到轮询，不影响使用。

## 项目结构

```
main.py               — 入口、流程编排、测试模式
display.py            — LCD 渲染（状态、回复、时钟、精灵动画）
display_mock.py       — 测试模式 WhisPlay 模拟接口
gui_display.py        — 测试模式 GUI 窗口（Tkinter，独立进程）
openclaw_client.py   — OpenClaw Gateway 流式 HTTP 客户端
transcribe_openai.py — 语音识别（FunASR / Whisper，自动重试）
tts_openai.py        — 语音合成（Bailian Qwen TTS / OpenAI TTS）
record_audio.py       — ALSA 录音，文件权限 600 保护隐私
button_ptt.py         — 按键状态机（PTT）
config.py             — 集中配置（从 .env 加载）
setup.sh             — 自动化安装向导（交互 + 非交互）
install.sh           — 一键安装入口（curl | bash）
run-openclaw.sh      — 启动脚本（兼容 systemd EnvironmentFile）
sync.sh              — 部署脚本（rsync + systemd）
pizero-openclaw.service — systemd 服务模板
requirements.txt      — 基础依赖
requirements-pi.txt   — Raspberry Pi 硬件依赖
```

## License

MIT
