#!/bin/sh
# Trovia installer for macOS and Linux.
#
#   curl -LsSf https://abyssalwolf.github.io/trovia/install.sh | sh
#
# What it does (nothing needs sudo):
#   1. installs uv (a Python tool installer from astral.sh) if you don't have it
#   2. installs the `trovia` command with uv, in its own isolated environment
#   3. runs `trovia setup`, which walks you through API keys and defaults
#
# Options (environment variables):
#   TROVIA_PACKAGE=<spec>     package to install (default: trovia). Example: trovia==0.1.0
#   TROVIA_NO_SETUP=1         install only; don't run the setup wizard
#   TROVIA_NO_MODIFY_PATH=1   don't edit your shell profile to put `trovia` on your PATH
set -eu

PACKAGE="${TROVIA_PACKAGE:-trovia}"

say() { printf '%s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

say "Installing Trovia ($PACKAGE)"

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
    say "uv was not found; installing it from astral.sh ..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        fail "need curl or wget to download uv"
    fi
    # uv's installer puts it here (or in UV_INSTALL_DIR); make it visible to this script.
    PATH="${UV_INSTALL_DIR:-$HOME/.local/bin}:$PATH"
    export PATH
fi
command -v uv >/dev/null 2>&1 || fail "uv is still not on PATH after installing it; open a new terminal and run this again"

# 2. trovia (uv fetches a suitable Python itself if you have none)
uv tool install --upgrade --python ">=3.11,<3.15" "$PACKAGE" || fail "could not install $PACKAGE"
BIN_DIR="$(uv tool dir --bin)"

# 3. PATH
if [ -z "${TROVIA_NO_MODIFY_PATH:-}" ]; then
    uv tool update-shell >/dev/null 2>&1 || true
fi

say ""
say "Trovia is installed: $BIN_DIR/trovia"

# 4. setup wizard. When piped from curl, stdin is the script itself, so read answers from the terminal.
if [ -z "${TROVIA_NO_SETUP:-}" ]; then
    if [ -t 0 ]; then
        "$BIN_DIR/trovia" setup
    elif ( : </dev/tty ) 2>/dev/null; then
        "$BIN_DIR/trovia" setup </dev/tty
    else
        say "No terminal available for the setup questions. Run this yourself:  trovia setup"
    fi
fi

say ""
say "Start it with:  trovia"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) say "(Open a new terminal first so your PATH picks up the trovia command.)" ;;
esac
