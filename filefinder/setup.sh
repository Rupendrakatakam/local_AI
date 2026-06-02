#!/usr/bin/env bash
# setup.sh — Run once to install everything and start the indexer service.
# Usage: bash setup.sh

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}▶ Checking Python version...${NC}"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    echo -e "${RED}Error: Python 3.10+ is required.${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Identify the real home directory of the user running sudo
if [ -n "$SUDO_USER" ]; then
    REAL_USER="$SUDO_USER"
    REAL_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
else
    REAL_USER="$(whoami)"
    REAL_HOME="$HOME"
fi
SERVICE_DIR="$REAL_HOME/.config/systemd/user"

run_user_systemctl() {
    if [ -n "$SUDO_USER" ]; then
        # Run as the original non-root user who invoked sudo
        sudo -u "$REAL_USER" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$REAL_USER")/bus" systemctl --user "$@"
    else
        systemctl --user "$@"
    fi
}

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
echo -e "${GREEN}▶ Installing Phase 2–4 pip dependencies...${NC}"
if ! pip install --break-system-packages --ignore-installed sentence-transformers lancedb pymupdf mammoth flask pystray pillow pynput markdown tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript tree-sitter-c tree-sitter-rust tree-sitter-go tree-sitter-java flask-socketio pytest mypy ruff hdbscan scikit-learn networkx duckdb spacy; then
    echo -e "${RED}Error installing pip dependencies. Retrying...${NC}"
    pip install --break-system-packages --ignore-installed sentence-transformers lancedb pymupdf mammoth flask pystray pillow pynput markdown tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript tree-sitter-c tree-sitter-rust tree-sitter-go tree-sitter-java flask-socketio pytest mypy ruff hdbscan scikit-learn networkx duckdb spacy
fi

# Download spaCy model silently if spacy is installed
if python3 -c "import spacy" &> /dev/null; then
    echo -e "${GREEN}▶ Downloading spaCy NER model...${NC}"
    PIP_BREAK_SYSTEM_PACKAGES=1 PIP_IGNORE_INSTALLED=1 python3 -m spacy download en_core_web_sm --quiet || true
fi

# 2b. Silence HuggingFace Hub warnings (model is cached locally)
echo ""
echo "▶ Configuring environment..."
grep -q "HF_HUB_DISABLE_TELEMETRY" ~/.bashrc 2>/dev/null || \
    echo 'export HF_HUB_DISABLE_TELEMETRY=1' >> ~/.bashrc
export HF_HUB_DISABLE_TELEMETRY=1

# 2. Set up systemd user service
echo ""
echo "▶ Registering indexer as a systemd user service..."
mkdir -p "$SERVICE_DIR"
if [ -n "$SUDO_USER" ]; then
    chown -R "$REAL_USER:$REAL_USER" "$REAL_HOME/.config" 2>/dev/null || true
fi

# Patch the service file with the correct Python path and script path
PYTHON_PATH="$(which python3)"
sed "s|/usr/bin/python3|$PYTHON_PATH|g; s|%h/Rupendra/local_AI/filefinder|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/filefinder.service" > "$SERVICE_DIR/filefinder.service"

if [ -n "$SUDO_USER" ]; then
    chown "$REAL_USER:$REAL_USER" "$SERVICE_DIR/filefinder.service" 2>/dev/null || true
fi

run_user_systemctl daemon-reload
run_user_systemctl enable filefinder.service
run_user_systemctl start  filefinder.service

echo ""
echo "▶ Registering backup timer..."
sed "s|/usr/bin/python3|$PYTHON_PATH|g; s|%h/Rupendra/local_AI/filefinder|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/filefinder-backup.service" > "$SERVICE_DIR/filefinder-backup.service"
cp "$SCRIPT_DIR/filefinder-backup.timer" "$SERVICE_DIR/filefinder-backup.timer"

if [ -n "$SUDO_USER" ]; then
    chown "$REAL_USER:$REAL_USER" "$SERVICE_DIR/filefinder-backup.service" "$SERVICE_DIR/filefinder-backup.timer" 2>/dev/null || true
fi

run_user_systemctl daemon-reload
run_user_systemctl enable filefinder-backup.timer
run_user_systemctl start  filefinder-backup.timer

echo ""
echo "▶ Registering hotkey service..."
sed "s|/usr/bin/python3|$PYTHON_PATH|g; s|%h/Rupendra/local_AI/filefinder|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/filefinder-hotkey.service" > "$SERVICE_DIR/filefinder-hotkey.service"

if [ -n "$SUDO_USER" ]; then
    chown "$REAL_USER:$REAL_USER" "$SERVICE_DIR/filefinder-hotkey.service" 2>/dev/null || true
fi

run_user_systemctl daemon-reload
run_user_systemctl enable filefinder-hotkey.service
run_user_systemctl start  filefinder-hotkey.service

echo ""
echo "▶ Service status:"
run_user_systemctl status filefinder.service --no-pager

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
