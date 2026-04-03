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

或者非交互式（CI / 自动化 / 已有 API Key）：
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
- 配置 API Key
- 选择运行模式（硬件模式 / 测试模式）

### 手动安装

#### 1. 克隆代码

### 手动安装

#### 1. 克隆代码

```bash
git clone https://github.com/hkgood/pizero-openclaw.git
cd pizero-openclaw
```

#### 2. 安装系统包

```bash
sudo apt update
sudo apt install python3-numpy python3-pil python3-pip alsa-utils sox libsox-fmt-all curl
```

#### 3. 安装 Python 包

```bash
# 基础依赖
pip install -r requirements.txt

# Raspberry Pi 硬件依赖
pip install -r requirements-pi.txt

# 百炼 SDK（含 FunASR + Qwen TTS）
pip install dashscope
```

#### 4. 配置

```bash
cp .env.example .env
```

编辑 `.env`，填写你的 Key：

```bash
# 阿里云百炼（默认）
export DASHSCOPE_API_KEY="your-bailian-api-key"

# OpenClaw
export OPENCLAW_TOKEN="your-openclaw-gateway-token"
```

> API Key 获取地址：
> - 百炼：https://bailian.console.aliyun.com/
> - OpenClaw：http://localhost:18789 配置页

#### 5. 运行

```bash
# 推荐方式（自动加载 .env）
./run-openclaw.sh

# 直接运行
python3 main.py

# 虚拟环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-pi.txt
./run-openclaw.sh
```

> ⚠️ **不要运行 `.venv/bin/activate`**（会导致 "Permission denied"）。始终用 `source .venv/bin/activate`。

#### 6. 部署 systemd 服务

编辑 `pizero-openclaw.service`，修改对应路径：

```ini
User=pi
Group=pi
WorkingDirectory=/home/pi/pizero-openclaw
ExecStart=/home/pi/pizero-openclaw/.venv/bin/python /home/pi/pizero-openclaw/main.py
```

部署到 Pi：

```bash
# 默认: pi@pizero.local
./sync.sh

# 自定义主机:
PI_HOST=rocky@pizero.local ./sync.sh
```

查看日志：

```bash
# systemd 日志
sudo journalctl -u pizero-openclaw -f

# 或日志文件
cat ~/.local/state/pizero-openclaw.log
```

## 测试模式（Mac / 无硬件环境）

在没有 WhisPlay 硬件的机器上（Mac/Linux），可以使用**测试模式**：

```bash
# 在 setup.sh 中选择测试模式，或手动设置：
export TEST_MODE=true
export ENABLE_TTS=false
./run-openclaw.sh
```

测试模式下：
- 用**文本输入**代替麦克风录音
- LCD 显示由 **Pillow 生成的帧序列**代替
- 完整测试 LLM 对话流程

## 配置参数

所有配置通过环境变量（`.env`）管理：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `STT_PROVIDER` | `funasr` | 语音识别：`funasr`（百炼）或 `openai` |
| `TTS_PROVIDER` | `bailian` | 语音合成：`bailian`（百炼）或 `openai` |
| `DASHSCOPE_API_KEY` | （必填）| 阿里云百炼 API Key |
| `BAILIAN_TTS_MODEL` | `qwen3-tts-flash` | 百炼 TTS 模型 |
| `BAILIAN_TTS_VOICE` | `Cherry` | 百炼 TTS 音色 |
| `BAILIAN_TTS_SPEED` | `1.0` | TTS 语速 (0.5–2.0) |
| `OPENAI_API_KEY` | — | OpenAI API Key（备选）|
| `OPENAI_TRANSCRIBE_MODEL` | `whisper-1` | OpenAI Whisper 模型 |
| `OPENAI_TTS_MODEL` | `tts-1` | OpenAI TTS 模型 |
| `OPENAI_TTS_VOICE` | `coral` | OpenAI TTS 音色 |
| `OPENCLAW_TOKEN` | （必填）| OpenClaw Gateway Token |
| `OPENCLAW_BASE_URL` | `http://localhost:18789` | OpenClaw Gateway 地址 |
| `WHISPLAY_DRIVER_PATH` | `~/Whisplay/Driver` | WhisPlay 驱动路径 |
| `ENABLE_TTS` | `true` | 是否开启语音朗读 |
| `AUDIO_DEVICE` | `plughw:1,0` | ALSA 输入设备 |
| `AUDIO_OUTPUT_DEVICE` | `default` | ALSA 输出设备 |
| `LCD_BACKLIGHT` | `70` | 屏幕亮度 (0–100) |
| `UI_MAX_FPS` | `4` | 屏幕最大刷新率 |
| `CONVERSATION_HISTORY_LENGTH` | `5` | 对话历史轮数 |
| `SILENCE_RMS_THRESHOLD` | `200` | 静音阈值（低于此值跳过）|
| `TEST_MODE` | `false` | 测试模式（无硬件时设为 true）|

## 百炼 vs OpenAI

| | 阿里云百炼（默认）| OpenAI（备选）|
|---|---|---|
| STT | FunASR（免费额度）| Whisper API |
| TTS | Qwen TTS（qwen3-tts-flash）| GPT-4o TTS |
| 费用 | 有免费额度 | 按量计费 |
| 推荐 | ✅ 推荐 | 备选方案 |

切换到 OpenAI：

```bash
export STT_PROVIDER="openai"
export TTS_PROVIDER="openai"
export OPENAI_API_KEY="sk-your-openai-api-key"
```

## 故障排除

### `ModuleNotFoundError: No module named 'WhisPlay'`
WhisPlay 驱动未找到。设置路径：
```bash
export WHISPLAY_DRIVER_PATH=~/Whisplay/Driver
python3 main.py
```

### `No module named 'spidev'` 或 `No module named 'RPi'`
Pi 硬件依赖缺失。安装：
```bash
pip install -r requirements-pi.txt
```

### `RuntimeError: Failed to add edge detection`
RPi.GPIO 注册按键中断失败。这是已知问题，WhisPlay 驱动会自动降级到轮询，不影响使用。

### `PermissionError: ... /tmp/openclaw.log`
日志文件由其他用户创建。删除旧日志或设置自定义路径：
```bash
rm /tmp/openclaw.log
# 或
export OPENCLAW_LOG_FILE=~/pizero-openclaw.log
```

### `Permission denied` when activating venv
用了脚本方式而非 source：
```bash
source .venv/bin/activate   # 正确
```

## 项目结构

```
main.py              — 入口和流程编排
display.py           — LCD 渲染（状态、回复、时钟、动画）
openclaw_client.py   — OpenClaw Gateway 流式 HTTP 客户端
transcribe_openai.py — 语音识别（FunASR / Whisper）
tts_openai.py        — 语音合成（Bailian Qwen TTS / OpenAI TTS）+ ALSA 播放
record_audio.py       — ALSA 录音（arecord）
button_ptt.py         — 按键状态机（PTT）
config.py             — 集中配置管理（从 .env 加载）
setup.sh             — 自动化安装脚本
run-openclaw.sh      — 启动脚本（加载 .env 后运行 main.py）
sync.sh              — 部署脚本（rsync + systemd 重启）
pizero-openclaw.service — systemd 服务模板
```

## License

MIT
