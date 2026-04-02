# pizero-openclaw

A voice-controlled AI assistant built on a Raspberry Pi Zero W with a [PiSugar WhisPlay board](https://www.pisugar.com). Press a button, speak, and get a streamed response on the LCD — powered by [OpenClaw](https://openclaw.ai) and **MiniMax**.

Supports **MiniMax STT + TTS** (recommended, free with MiniMax plan) and **OpenAI** (fallback).

## How it works

```
Button press → Record audio → Transcribe (MiniMax) → Stream LLM response (OpenClaw) → Display on LCD
                                                                                     → Speak aloud (MiniMax TTS, optional)
```

1. **Press & hold** the button to record your voice via ALSA
2. **Release** — the WAV is sent to MiniMax for transcription (~0.7s)
3. The transcript (with conversation history) is streamed to an **OpenClaw gateway** for a response
4. Text streams onto the **LCD** in real time with pixel-accurate word wrapping
5. Optionally **speaks the response** via MiniMax TTS as sentences complete
6. The idle screen shows a **clock, date, battery %, and WiFi status**

The device maintains **conversation memory** across exchanges and includes a **silence gate** to skip empty recordings.

## Hardware

- **Raspberry Pi Zero 2 W** (or Pi Zero W)
- **[PiSugar WhisPlay board](https://www.pisugar.com)** — 1.54" LCD (240x240), push-to-talk button, LED, speaker, microphone
- **PiSugar battery** (optional) — shows charge level on screen

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/hkgood/pizero-openclaw.git
cd pizero-openclaw
```

### 2. Install system packages

```bash
sudo apt update
sudo apt install python3-numpy python3-pil
```

### 3. Install Python packages

**Standard (all users):**
```bash
pip install -r requirements.txt
```

**Raspberry Pi with WhisPlay hardware — also install Pi dependencies:**
```bash
# Requires spi and gpio group membership; add your user if needed:
#   sudo usermod -aG spi,gpio $USER
pip install -r requirements.txt -r requirements-pi.txt
```

### 4. Configure

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```bash
export MINIMAX_API_KEY="your-minimax-api-key"
export OPENCLAW_TOKEN="your-openclaw-gateway-token"
```

### 5. Run

**Directly (any user):**
```bash
python3 main.py
```

**Or use the wrapper script** (recommended — handles `.env` export lines correctly):
```bash
./run-openclaw.sh
```

**Or with a virtual environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-pi.txt
./run-openclaw.sh
```
> ⚠️ **Do NOT run `.venv/bin/activate`** as a script (that causes "Permission denied"). Always `source .venv/bin/activate`.

### 6. Deploy as a systemd service

Edit `pizero-openclaw.service` and set `User=`, `Group=`, `WorkingDirectory=`, and `ExecStart=` to match your setup:

```ini
User=your-username
Group=your-username
WorkingDirectory=/path/to/pizero-openclaw
ExecStart=/path/to/pizero-openclaw/.venv/bin/python /path/to/pizero-openclaw/main.py
```

Then deploy:

```bash
# Default: pi@pizero.local
./sync.sh

# Custom host:
PI_HOST=rocky@pizero.local ./sync.sh
```

### Troubleshooting

#### `ModuleNotFoundError: No module named 'WhisPlay'`
WhisPlay driver not found. Set the path explicitly:
```bash
export WHISPLAY_DRIVER_PATH=~/Whisplay/Driver   # or your custom path
python3 main.py
```

#### `No module named 'spidev'` or `No module named 'RPi'`
Missing Pi hardware dependencies. Install them:
```bash
pip install -r requirements-pi.txt
```

#### `RuntimeError: Failed to add edge detection`
RPi.GPIO failed to register a button interrupt. This is a known upstream issue with some Pi kernels. Workaround: the WhisPlay driver will fall back to polling. No action needed — the button will still work.

#### `PermissionError: ... /tmp/openclaw.log`
Log file was created by a different user (e.g., running as root then as pi). Either:
- Delete the old log: `rm /tmp/openclaw.log`
- Or set a custom log path: `export OPENCLAW_LOG_FILE=~/pizero-openclaw.log`

#### `Permission denied` when activating venv
You ran `.venv/bin/activate` as a script instead of sourcing it. Use:
```bash
source .venv/bin/activate   # correct
```

## Configuration

All settings are configured via environment variables (loaded from `.env`):

| Variable | Default | Description |
|---|---|---|
| `STT_PROVIDER` | `minimax` | Speech-to-text provider: `minimax` or `openai` |
| `TTS_PROVIDER` | `minimax` | Text-to-speech provider: `minimax` or `openai` |
| `MINIMAX_API_KEY` | _(required)_ | MiniMax API key for STT and TTS |
| `MINIMAX_STT_MODEL` | `speech-01-mini` | MiniMax STT model |
| `MINIMAX_TTS_MODEL` | `speech-02-horo` | MiniMax TTS model |
| `MINIMAX_TTS_VOICE` | `male-qn-qingse` | MiniMax TTS voice |
| `MINIMAX_TTS_SPEED` | `1.0` | TTS speed (0.5–2.0) |
| `OPENCLAW_TOKEN` | _(required)_ | Auth token for the OpenClaw gateway |
| `OPENCLAW_BASE_URL` | `http://localhost:18789` | OpenClaw gateway URL |
| `WHISPLAY_DRIVER_PATH` | `~/Whisplay/Driver` | Path to WhisPlay driver |
| `OPENCLAW_LOG_FILE` | `~/.local/state/pizero-openclaw.log` | Log file path |
| `ENABLE_TTS` | `true` | Speak responses aloud |
| `AUDIO_DEVICE` | `plughw:1,0` | ALSA input device |
| `AUDIO_OUTPUT_DEVICE` | `default` | ALSA output device |
| `AUDIO_SAMPLE_RATE` | `16000` | Recording sample rate |
| `LCD_BACKLIGHT` | `70` | Backlight brightness (0–100) |
| `UI_MAX_FPS` | `4` | Max display refresh rate |
| `CONVERSATION_HISTORY_LENGTH` | `5` | Past exchanges to keep for context |
| `SILENCE_RMS_THRESHOLD` | `200` | Audio RMS below this is skipped |

### OpenAI fallback

To use OpenAI instead of MiniMax:

```bash
export STT_PROVIDER="openai"
export TTS_PROVIDER="openai"
export OPENAI_API_KEY="sk-your-openai-api-key"
export OPENAI_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe"
export OPENAI_TTS_MODEL="tts-1"
export OPENAI_TTS_VOICE="alloy"
```

## Deploy with systemd

Logs are available via:

```bash
# On the Pi:
sudo journalctl -u pizero-openclaw -f

# Or check the log file (default ~/.local/state/pizero-openclaw.log):
cat ~/.local/state/pizero-openclaw.log
```

## Project structure

```
main.py               — Entry point and orchestrator
display.py            — LCD rendering (status, responses, idle clock, spinner)
openclaw_client.py   — Streaming HTTP client for the OpenClaw gateway
transcribe_openai.py  — Speech-to-text via MiniMax (or OpenAI fallback)
tts_openai.py         — Text-to-speech via MiniMax (or OpenAI fallback) + ALSA playback
record_audio.py       — Audio recording via ALSA arecord
button_ptt.py         — Push-to-talk button state machine
config.py             — Centralized configuration from .env
run-openclaw.sh       — Wrapper script: sources .env then runs main.py
sync.sh               — Deploy script (rsync + systemd restart)
pizero-openclaw.service — systemd unit template
```

## License

MIT
