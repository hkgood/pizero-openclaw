#!/bin/bash
# PiZero OpenClaw Voice Assistant - Full Setup Script
# Usage: sudo bash setup.sh --openai-key "sk-..." --openclaw-url "https://..." --openclaw-token "..."
#
# Prerequisites:
#   - Fresh Raspberry Pi OS Lite 64-bit on Pi Zero 2 W
#   - WiFi configured and SSH enabled via Raspberry Pi Imager
#   - PiSugar WhisPlay HAT + WM8960 audio codec attached
#   - Tailscale account for secure gateway access
#
# This script runs in two phases:
#   Phase 1: Install drivers, dependencies, reboot
#   Phase 2: Deploy app, configure services, enable overlay filesystem
#
# Run once - it handles both phases automatically.

set -e

PHASE_FILE="/home/pi/.pizero-setup-phase"
REPO_URL="https://github.com/JamesTsetsekas/pizero-openclaw"
WHISPLAY_REPO="https://github.com/PiSugar/Whisplay.git"
WM8960_REPO="https://github.com/waveshare/WM8960-Audio-HAT"
APP_DIR="/home/pi/pizero-openclaw"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step() { echo -e "\n${BLUE}==>${NC} $1"; }

# ─── Parse arguments ───────────────────────────────────────────────
OPENAI_KEY=""
OPENCLAW_URL=""
OPENCLAW_TOKEN=""
WIFI_GATEWAY="192.168.200.1"
SKIP_OVERLAY=false
TTS_GAIN="18.0"

while [[ $# -gt 0 ]]; do
  case $1 in
    --openai-key) OPENAI_KEY="$2"; shift 2 ;;
    --openclaw-url) OPENCLAW_URL="$2"; shift 2 ;;
    --openclaw-token) OPENCLAW_TOKEN="$2"; shift 2 ;;
    --wifi-gateway) WIFI_GATEWAY="$2"; shift 2 ;;
    --tts-gain) TTS_GAIN="$2"; shift 2 ;;
    --skip-overlay) SKIP_OVERLAY=true; shift ;;
    --phase2) shift ;;
    -h|--help)
      echo "PiZero OpenClaw Setup"
      echo ""
      echo "Usage: sudo bash setup.sh [options]"
      echo ""
      echo "Required:"
      echo "  --openai-key KEY        OpenAI API key (for Whisper transcription + TTS)"
      echo "  --openclaw-url URL      OpenClaw gateway URL (e.g. https://your-instance.dynamisai.io)"
      echo "  --openclaw-token TOKEN  OpenClaw gateway auth token"
      echo ""
      echo "Optional:"
      echo "  --wifi-gateway IP       Router IP for WiFi watchdog (default: 192.168.200.1)"
      echo "  --tts-gain DB           TTS gain in dB (default: 18.0)"
      echo "  --skip-overlay          Don't enable overlay filesystem"
      echo "  -h, --help              Show this help"
      exit 0
      ;;
    *) err "Unknown option: $1. Use --help for usage." ;;
  esac
done

# ─── Root check ────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  err "Must run as root: sudo bash setup.sh ..."
fi

# ─── Phase detection ──────────────────────────────────────────────
if [ ! -f "$PHASE_FILE" ]; then
  PHASE=1
else
  PHASE=$(cat "$PHASE_FILE")
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 1: System setup, drivers, dependencies
# ═══════════════════════════════════════════════════════════════════
if [ "$PHASE" -eq 1 ]; then
  echo ""
  echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║  PiZero OpenClaw Setup - Phase 1 of 2       ║${NC}"
  echo -e "${BLUE}║  Installing drivers and dependencies         ║${NC}"
  echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
  echo ""

  # Save args for phase 2
  cat > /home/pi/.pizero-setup-args <<EOF
OPENAI_KEY="$OPENAI_KEY"
OPENCLAW_URL="$OPENCLAW_URL"
OPENCLAW_TOKEN="$OPENCLAW_TOKEN"
WIFI_GATEWAY="$WIFI_GATEWAY"
TTS_GAIN="$TTS_GAIN"
SKIP_OVERLAY=$SKIP_OVERLAY
EOF
  chown pi:pi /home/pi/.pizero-setup-args

  step "Updating system packages"
  apt update && apt upgrade -y

  step "Installing system dependencies"
  apt install -y \
    git python3-pip python3-venv python3-dev python3-lgpio \
    python3-pil python3-numpy python3-spidev python3-gpiozero \
    gcc libatlas-base-dev swig

  step "Installing Tailscale"
  if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    log "Tailscale installed. You'll need to authenticate after reboot."
    log "Run: sudo tailscale up"
  else
    log "Tailscale already installed"
  fi

  step "Installing WM8960 audio drivers"
  cd /home/pi
  if [ ! -d "WM8960-Audio-HAT" ]; then
    sudo -u pi git clone "$WM8960_REPO"
  fi
  cd WM8960-Audio-HAT
  bash ./install.sh

  step "Cloning WhisPlay driver"
  cd /home/pi
  if [ ! -d "Whisplay" ]; then
    sudo -u pi git clone "$WHISPLAY_REPO" --depth 1
  fi

  step "Enabling SPI interface"
  raspi-config nonint do_spi 0

  step "Enabling I2C interface"
  raspi-config nonint do_i2c 0

  # Mark phase 2
  echo "2" > "$PHASE_FILE"
  chown pi:pi "$PHASE_FILE"

  # Set up auto-run of phase 2 after reboot
  cat > /etc/systemd/system/pizero-setup-phase2.service <<'SVCEOF'
[Unit]
Description=PiZero OpenClaw Setup Phase 2
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'sleep 10 && bash /home/pi/pizero-setup.sh --phase2'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SVCEOF

  # Copy this script for phase 2
  cp "$0" /home/pi/pizero-setup.sh 2>/dev/null || true
  chmod +x /home/pi/pizero-setup.sh

  systemctl daemon-reload
  systemctl enable pizero-setup-phase2.service

  echo ""
  log "Phase 1 complete. Rebooting in 5 seconds..."
  log "Phase 2 will run automatically after reboot."
  log "Check progress: sudo journalctl -fu pizero-setup-phase2"
  echo ""
  sleep 5
  reboot
  exit 0
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 2: Deploy app, configure services
# ═══════════════════════════════════════════════════════════════════
if [ "$PHASE" -eq 2 ] || [ "$1" = "--phase2" ]; then
  echo ""
  echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║  PiZero OpenClaw Setup - Phase 2 of 2       ║${NC}"
  echo -e "${BLUE}║  Deploying app and configuring services       ║${NC}"
  echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
  echo ""

  # Load saved args
  if [ -f /home/pi/.pizero-setup-args ]; then
    source /home/pi/.pizero-setup-args
  fi

  step "Cloning pizero-openclaw"
  cd /home/pi
  if [ ! -d "pizero-openclaw" ]; then
    sudo -u pi git clone "$REPO_URL"
  fi

  step "Copying WhisPlay driver"
  cp /home/pi/Whisplay/Driver/WhisPlay.py "$APP_DIR/"
  chown pi:pi "$APP_DIR/WhisPlay.py"

  step "Creating Python virtual environment"
  cd "$APP_DIR"
  sudo -u pi python3 -m venv --system-site-packages venv

  step "Installing Python dependencies"
  sudo -u pi bash -c "cd $APP_DIR && source venv/bin/activate && pip install -r requirements.txt && pip install spidev"

  step "Configuring .env"
  cat > "$APP_DIR/.env" <<EOF
OPENAI_API_KEY=${OPENAI_KEY}
OPENCLAW_BASE_URL=${OPENCLAW_URL}
OPENCLAW_TOKEN=${OPENCLAW_TOKEN}
AUDIO_DEVICE=plughw:0,0
AUDIO_OUTPUT_DEVICE=default
OPENAI_TTS_GAIN_DB=${TTS_GAIN}
ENABLE_TTS=true
EOF
  chown pi:pi "$APP_DIR/.env"

  step "Creating systemd service"
  cat > /etc/systemd/system/pizero-openclaw.service <<'EOF'
[Unit]
Description=Pi Zero OpenClaw Voice Terminal
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/pi/pizero-openclaw
EnvironmentFile=/home/pi/pizero-openclaw/.env
ExecStartPre=/usr/bin/amixer -c 0 sset Speaker 100%%
ExecStartPre=/usr/bin/amixer -c 0 cset name='Speaker AC Volume' 5
ExecStartPre=/usr/bin/amixer -c 0 cset name='Speaker DC Volume' 5
ExecStart=/home/pi/pizero-openclaw/venv/bin/python3 /home/pi/pizero-openclaw/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable pizero-openclaw

  step "Setting up WiFi watchdog"
  (crontab -l 2>/dev/null || true; echo "*/3 * * * * ping -c 1 ${WIFI_GATEWAY} > /dev/null 2>&1 || (ip link set wlan0 down && sleep 2 && ip link set wlan0 up)") | sort -u | crontab -

  step "Reducing SD card writes"
  if ! grep -q "tmpfs /tmp" /etc/fstab; then
    echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,size=50m 0 0" >> /etc/fstab
    echo "tmpfs /var/log tmpfs defaults,noatime,nosuid,size=30m 0 0" >> /etc/fstab
    log "Added tmpfs mounts to fstab"
  else
    log "tmpfs mounts already in fstab"
  fi

  step "Cleaning up setup files"
  systemctl disable pizero-setup-phase2.service 2>/dev/null || true
  rm -f /etc/systemd/system/pizero-setup-phase2.service
  rm -f /home/pi/.pizero-setup-phase
  rm -f /home/pi/.pizero-setup-args
  rm -f /home/pi/pizero-setup.sh
  systemctl daemon-reload

  # ─── Overlay filesystem ────────────────────────────────────────
  if [ "$SKIP_OVERLAY" = true ]; then
    warn "Skipping overlay filesystem (--skip-overlay)"
    warn "Run 'sudo raspi-config' → Performance → Overlay FS to enable later"
  else
    step "Enabling overlay filesystem (read-only protection)"
    raspi-config nonint do_overlayfs 0
    # Also make boot read-only
    raspi-config nonint do_boot_rom 0 2>/dev/null || true
  fi

  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║  Setup complete!                             ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
  echo ""
  log "Voice assistant service: enabled"
  log "WiFi watchdog: enabled"
  log "SD write protection: $([ "$SKIP_OVERLAY" = true ] && echo 'skipped' || echo 'enabled')"
  echo ""
  warn "IMPORTANT: You still need to authenticate Tailscale:"
  warn "  sudo tailscale up"
  warn "  (Visit the URL it gives you to authorize)"
  echo ""
  log "Rebooting in 5 seconds..."
  sleep 5
  reboot
  exit 0
fi
