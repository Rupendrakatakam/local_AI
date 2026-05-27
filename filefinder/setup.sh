#!/usr/bin/env bash
# setup.sh — Run once to install everything and start the indexer service.
# Usage: bash setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$HOME/.config/systemd/user"

echo ""
echo "═══════════════════════════════════════════"
echo "  FileChat Setup"
echo "═══════════════════════════════════════════"
echo ""

# 1. Install Python deps via system package manager (APT)
echo "▶ Installing system Python dependencies via apt..."
sudo apt update
sudo apt install -y python3-watchdog python3-rich python3-prompt-toolkit python3-requests python3-pip

# 2. Install Phase 2–4 pip dependencies
echo ""
echo "▶ Installing Phase 2–4 pip dependencies..."
pip install --quiet sentence-transformers lancedb pymupdf mammoth flask pystray pillow

# 2. Set up systemd user service
echo ""
echo "▶ Registering indexer as a systemd user service..."
mkdir -p "$SERVICE_DIR"

# Patch the service file with the correct Python path and script path
PYTHON_PATH="$(which python3)"
sed "s|/usr/bin/python3|$PYTHON_PATH|g; s|%h/Rupendra/local_AI/filefinder|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/filefinder.service" > "$SERVICE_DIR/filefinder.service"

systemctl --user daemon-reload
systemctl --user enable filefinder.service
systemctl --user start  filefinder.service

echo ""
echo "▶ Service status:"
systemctl --user status filefinder.service --no-pager

echo ""
echo "═══════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Start chatting:"
echo "    python3 $SCRIPT_DIR/chat.py"
echo ""
echo "  Useful commands:"
echo "    systemctl --user status filefinder   # check indexer"
echo "    systemctl --user restart filefinder  # restart indexer"
echo "    journalctl --user -u filefinder -f   # live logs"
echo "═══════════════════════════════════════════"
echo ""
