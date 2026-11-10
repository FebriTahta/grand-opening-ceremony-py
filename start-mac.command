#!/bin/bash
# Dobel-klik untuk menjalankan Grand Opening Ceremony di macOS.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run ceremony "$@"
