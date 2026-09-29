#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.12 was not found. Install Python 3.12 with Tcl/Tk, then rerun this script." >&2
  exit 1
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Use Python 3.12"'

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-macos.txt
.venv/bin/python -c 'import mediapipe as mp; assert hasattr(mp, "solutions"), "This build needs MediaPipe 0.10.x with mp.solutions"; assert hasattr(mp.solutions, "hands"), "MediaPipe hand tracking is unavailable"'
.venv/bin/python -m PyInstaller --noconfirm --clean "Hand Gesture AI macOS.spec"

APP_PATH="dist/Hand Gesture AI.app"
DMG_PATH="dist/Hand-Gesture-AI-macOS.dmg"
if [ ! -d "$APP_PATH" ]; then
  echo "Build finished without the expected app bundle: $APP_PATH" >&2
  exit 1
fi
rm -f "$DMG_PATH"
hdiutil create -volname "Hand Gesture AI" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"
echo "App: $APP_PATH"
echo "Disk image: $DMG_PATH"
