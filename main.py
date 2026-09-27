"""
NOVA Smart Hand Gesturing - Application Entry Point.

This module is intentionally thin. Its only job is to:
    1. Load configuration.
    2. Initialize the camera subsystem.
    3. Run a minimal display loop so we can visually confirm the
       camera pipeline works.
    4. Shut everything down cleanly on exit.

No gesture recognition, tracking, or system-control logic lives here.
All of that belongs in its own module (see the `tracking/`, `gestures/`,
and `actions/` packages), which are currently placeholders for future
layers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import cv2

from camera.camera import Camera, CameraError

CONFIG_PATH = Path(__file__).parent / "config" / "settings.json"


def load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load application configuration from a JSON file.

    Args:
        config_path: Path to the settings JSON file.

    Returns:
        A dictionary of configuration values. Falls back to sensible
        defaults if the file is missing or malformed.
    """
    defaults: dict[str, Any] = {
        "camera_index": 0,
        "frame_width": 640,
        "frame_height": 480,
        "fps": 30,
        "window_name": "NOVA - Camera Feed (press 'q' to quit)",
    }

    if not config_path.exists():
        print(f"[NOVA] No config file found at {config_path}, using defaults.")
        return defaults

    try:
        with config_path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        defaults.update(loaded)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[NOVA] Failed to read config ({exc}); using defaults.")

    return defaults


def run(config: dict[str, Any]) -> int:
    """Run the base application loop: open the camera and show its feed.

    Args:
        config: Application configuration values.

    Returns:
        Process exit code (0 on clean exit, non-zero on failure).
    """
    window_name = config.get("window_name", "NOVA - Camera Feed (press 'q' to quit)")

    try:
        camera = Camera(
            index=config.get("camera_index", 0),
            width=config.get("frame_width", 640),
            height=config.get("frame_height", 480),
            fps=config.get("fps", 30),
        )
    except CameraError as exc:
        print(f"[NOVA] Could not initialize camera: {exc}")
        return 1

    try:
        camera.open()
        print("[NOVA] Camera subsystem initialized successfully.")
        print("[NOVA] Displaying raw camera feed. Press 'q' to exit.")

        while True:
            frame = camera.read_frame()
            if frame is None:
                print("[NOVA] Failed to read frame from camera. Exiting.")
                break

            # NOTE: No hand landmarks or overlays are drawn yet.
            # This is intentional for Layer 1 (base architecture only).
            cv2.imshow(window_name, frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("[NOVA] Exit requested by user.")
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()

    return 0


def main() -> int:
    """Application entry point."""
    print("[NOVA] Smart Hand Gesturing - Base Architecture (Layer 1)")
    config = load_config()
    return run(config)


if __name__ == "__main__":
    sys.exit(main())
