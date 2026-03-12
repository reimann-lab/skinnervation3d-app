#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  SkInnervation3D — macOS / Linux installer launcher
#  Double-click this file (or run:  bash install.sh)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$SCRIPT_DIR/install.py"

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  SkInnervation3D — Installer Launcher"
echo "════════════════════════════════════════════════════════════"
echo ""

# ── Make sure install.py is present ───────────────────────────────────────────
if [ ! -f "$INSTALLER" ]; then
    echo "ERROR: install.py not found in the same folder as this script."
    echo "Please download both files (install.sh AND install.py) and try again."
    exit 1
fi

# ── Locate Python 3.8+ ────────────────────────────────────────────────────────
PYTHON=""

for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(sys.version_info[:2])" 2>/dev/null || echo "(0, 0)")
        major=$(echo "$version" | tr -d '(),' | awk '{print $1}')
        minor=$(echo "$version" | tr -d '(),' | awk '{print $2}')
        if [ "${major:-0}" -ge 3 ] && [ "${minor:-0}" -ge 8 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

# ── If no Python, bootstrap from Miniforge ────────────────────────────────────
if [ -z "$PYTHON" ]; then
    echo "Python 3.8+ not found on PATH. Bootstrapping via Miniforge…"
    echo ""

    ARCH=$(uname -m)
    OS=$(uname -s)

    if [ "$OS" = "Darwin" ]; then
        URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-${ARCH}.sh"
    else
        URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${ARCH}.sh"
    fi

    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT

    echo "Downloading Miniforge from:"
    echo "  $URL"
    echo ""

    if command -v curl &>/dev/null; then
        curl -fsSL -o "$TMP/miniforge.sh" "$URL"
    elif command -v wget &>/dev/null; then
        wget -q -O "$TMP/miniforge.sh" "$URL"
    else
        echo "ERROR: Neither curl nor wget is available."
        echo "Please install one (e.g. 'brew install wget') and try again."
        exit 1
    fi

    bash "$TMP/miniforge.sh" -b -p "$HOME/miniforge3"
    PYTHON="$HOME/miniforge3/bin/python3"

    if [ ! -x "$PYTHON" ]; then
        echo "ERROR: Miniforge bootstrap failed."
        echo "Please install Miniforge manually from:"
        echo "  https://github.com/conda-forge/miniforge"
        exit 1
    fi

    echo ""
    echo "✓ Miniforge bootstrapped → $HOME/miniforge3"
fi

echo "Using Python: $PYTHON  ($($PYTHON --version))"
echo ""

# ── Hand off to the Python installer ──────────────────────────────────────────
exec "$PYTHON" "$INSTALLER"
