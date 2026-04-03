import os
from dotenv import load_dotenv

load_dotenv()

# ─── Provider selection ───────────────────────────────────────────────────────
# TTS_PROVIDER: "bailian" (default) or "openai"
# STT_PROVIDER: "funasr" (default, cloud) or "openai" or "dryrun"
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "bailian").lower()
STT_PROVIDER = os.environ.get("STT_PROVIDER", "funasr").lower()

# ─── Bailian / DashScope ────────────────────────────────────────────────────
# Get your API key from: https://bailian.console.aliyun.com/
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_API_BASE = os.environ.get("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com")

# Bailian TTS (qwen3-tts-flash)
BAILIAN_TTS_MODEL = os.environ.get("BAILIAN_TTS_MODEL", "qwen3-tts-flash")
BAILIAN_TTS_VOICE = os.environ.get("BAILIAN_TTS_VOICE", "Cherry")
BAILIAN_TTS_SPEED = float(os.environ.get("BAILIAN_TTS_SPEED", "1.0"))
BAILIAN_TTS_GAIN_DB = float(os.environ.get("BAILIAN_TTS_GAIN_DB", "9"))

# ─── OpenAI API (fallback) ───────────────────────────────────────────────────
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "coral")
OPENAI_TTS_SPEED = float(os.environ.get("OPENAI_TTS_SPEED", "1.1"))
OPENAI_TTS_GAIN_DB = float(os.environ.get("OPENAI_TTS_GAIN_DB", "9"))
OPENAI_TTS_INSTRUCTIONS = os.environ.get(
    "OPENAI_TTS_INSTRUCTIONS",
    "Speak in a warm, sweet, and playful tone with a gentle high pitch. "
    "Sound like an adorable, tiny friend who is genuinely excited to help. "
    "Use natural breathing and smooth pacing — never robotic or monotone. "
    "Let sentences flow into each other without awkward pauses.",
)

# ─── OpenClaw ───────────────────────────────────────────────────────────────
OPENCLAW_BASE_URL = os.environ.get("OPENCLAW_BASE_URL", "http://localhost:18789")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")

# ─── Audio ───────────────────────────────────────────────────────────────────
AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "plughw:1,0")
AUDIO_OUTPUT_DEVICE = os.environ.get("AUDIO_OUTPUT_DEVICE", "default")
AUDIO_OUTPUT_CARD = int(os.environ.get("AUDIO_OUTPUT_CARD", "0"))
AUDIO_SAMPLE_RATE = int(os.environ.get("AUDIO_SAMPLE_RATE", "16000"))

# ─── UI ──────────────────────────────────────────────────────────────────────
LCD_BACKLIGHT = int(os.environ.get("LCD_BACKLIGHT", "70"))
UI_MAX_FPS = int(os.environ.get("UI_MAX_FPS", "4"))

# ─── Behaviour ─────────────────────────────────────────────────────────────
ENABLE_TTS = os.environ.get("ENABLE_TTS", "true").lower() in ("true", "1", "yes")
CONVERSATION_HISTORY_LENGTH = int(os.environ.get("CONVERSATION_HISTORY_LENGTH", "5"))
MAX_CONTEXT_TOKENS = int(os.environ.get("MAX_CONTEXT_TOKENS", "16000"))
SILENCE_RMS_THRESHOLD = float(os.environ.get("SILENCE_RMS_THRESHOLD", "200"))

# Dry run when no API keys are configured
DRY_RUN = not DASHSCOPE_API_KEY and not OPENAI_API_KEY


def print_config():
    """Print non-secret config for debugging."""
    print(f"STT_PROVIDER           = {STT_PROVIDER}")
    print(f"TTS_PROVIDER           = {TTS_PROVIDER}")
    if TTS_PROVIDER == "bailian":
        print(f"BAILIAN_TTS_MODEL     = {BAILIAN_TTS_MODEL}")
        print(f"BAILIAN_TTS_VOICE    = {BAILIAN_TTS_VOICE}")
        print(f"BAILIAN_TTS_SPEED    = {BAILIAN_TTS_SPEED}")
    elif TTS_PROVIDER == "openai":
        print(f"OPENAI_TTS_MODEL     = {OPENAI_TTS_MODEL}")
        print(f"OPENAI_TTS_VOICE     = {OPENAI_TTS_VOICE}")
        print(f"OPENAI_TTS_SPEED     = {OPENAI_TTS_SPEED}")
    if STT_PROVIDER == "funasr":
        print(f"DASHSCOPE_API_BASE   = {DASHSCOPE_API_BASE}")
    elif STT_PROVIDER == "openai":
        print(f"OPENAI_TRANSCRIBE_MODEL = {OPENAI_TRANSCRIBE_MODEL}")
    print(f"OPENCLAW_BASE_URL     = {OPENCLAW_BASE_URL}")
    print(f"AUDIO_DEVICE          = {AUDIO_DEVICE}")
    print(f"AUDIO_OUTPUT_DEVICE   = {AUDIO_OUTPUT_DEVICE}")
    print(f"AUDIO_SAMPLE_RATE    = {AUDIO_SAMPLE_RATE}")
    print(f"DRY_RUN               = {DRY_RUN}")
    print(f"LCD_BACKLIGHT         = {LCD_BACKLIGHT}")
    print(f"DASHSCOPE_API_KEY set = {bool(DASHSCOPE_API_KEY)}")
    print(f"OPENAI_API_KEY set    = {bool(OPENAI_API_KEY)}")
    print(f"OPENCLAW_TOKEN set    = {bool(OPENCLAW_TOKEN)}")
    print(f"ENABLE_TTS            = {ENABLE_TTS}")
    print(f"CONVERSATION_HISTORY  = {CONVERSATION_HISTORY_LENGTH}")
    print(f"MAX_CONTEXT_TOKENS    = {MAX_CONTEXT_TOKENS}")
    print(f"SILENCE_RMS_THRESHOLD = {SILENCE_RMS_THRESHOLD}")
