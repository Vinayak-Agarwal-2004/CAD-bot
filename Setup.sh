#!/usr/bin/env bash
# Installs system dependencies, Blender 4.2 LTS and the Python packages.
# Tested on Ubuntu 22.04/24.04. Distro `apt install blender` is too old
# (3.x / 4.0) for this project, so the official build is downloaded instead.
set -euo pipefail

BLENDER_VERSION=4.2.3
BLENDER_DIR="$(pwd)/blender"

sudo apt-get update -y
sudo apt-get install -y ffmpeg fonts-dejavu-core python3-pip python3-venv \
    libxi6 libxxf86vm1 libxfixes3 libxrender1 libgl1 libxkbcommon0 libsm6 xz-utils curl

if [ ! -x "$BLENDER_DIR/blender" ]; then
    echo "Downloading Blender $BLENDER_VERSION..."
    curl -fL "https://download.blender.org/release/Blender4.2/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        -o /tmp/blender.tar.xz
    mkdir -p "$BLENDER_DIR"
    tar -xf /tmp/blender.tar.xz -C "$BLENDER_DIR" --strip-components=1
    rm /tmp/blender.tar.xz
fi

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

[ -f .env ] || cp .env.example .env
grep -q '^BLENDER_BIN=' .env || echo "BLENDER_BIN=$BLENDER_DIR/blender" >> .env

echo
echo "Done. Next:"
echo "  . .venv/bin/activate"
echo "  python main.py scan && python main.py produce -n 1 --preview"
