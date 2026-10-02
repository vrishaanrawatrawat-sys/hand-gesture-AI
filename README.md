# Hand Gesture AI

A Tkinter desktop app with OpenCV camera preview, MediaPipe hand landmarks,
14 geometry-based gesture labels, and configurable keyboard/mouse actions.
Run `hand_gesture_ai.py`; `Hand Gesture.spec` is only for packaging with PyInstaller.

## Run on this Mac

The project environment has been created using your Anaconda Python, which includes
Tkinter. Your Homebrew Python installations currently lack Tkinter.

```bash
cd /Users/akanksha/Documents/virshaan/hand-gesture-AI
source .venv/bin/activate
python hand_gesture_ai.py
```

In VS Code, select `hand-gesture-AI/.venv/bin/python` as the Python interpreter.

## Fresh installation

Use Python **3.9–3.12 with Tkinter**. Python 3.11 or 3.12 is recommended for a
new installation. This app uses the legacy MediaPipe Solutions API, so install
the pinned dependencies instead of upgrading MediaPipe independently.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python hand_gesture_ai.py
```

On Windows, activate using `.venv\Scripts\activate` instead.
Check Tkinter with `python -m tkinter`; a small window should open.
Do not install both opencv-python and opencv-contrib-python in this environment;
MediaPipe uses the latter, which provides `cv2`.

## Using the app

1. Click **START** and allow camera access. Keep one hand clearly visible in good
   lighting. The preview shows landmarks and the recognized gesture.
2. Review the gesture bindings before enabling actions. You can record a keyboard
   shortcut or choose a mouse action, then save your bindings.
3. Click **ENABLE ACTIONS**, focus the application you want to control, and hold
   a gesture for the configured stable-frame count. A held gesture fires once;
   change gesture or remove your hand to repeat it. Swipes fire immediately and
   obey the cooldown.
4. Press **Esc** to disable actions, or return to the app and disable actions.
   **STOP** stops the camera and disables actions as well.

Defaults include Open Palm → Space, Fist → Cmd+S on macOS (Ctrl+S elsewhere),
Point → F, Peace → Ctrl+Shift+P, Pinch → left click, and horizontal swipes → arrow
keys. Other gestures initially have no action. Mouse clicks happen at the current
cursor position; the app does not move the pointer with your hand.

macOS: in **System Settings → Privacy & Security**, allow **Camera** access for the
app launching Python (Terminal or your IDE). For simulated input, enable
**Accessibility**; global shortcut recording/Esc may also need **Input Monitoring**.
Restart the app after changing permissions. If global Esc is unavailable, the
in-app Escape binding and disable button still work while the app has focus.

If the camera fails, close other camera apps and try camera index 0 or 1 under
Settings. Save settings and restart the camera. Previewing works independently
of whether input control is available.

Settings are stored in `~/.hand-gesture-ai/config.json`. Import/export is available
in the UI. Recognition uses hand geometry heuristics, not a trained sign-language
classifier. Displayed confidence values are heuristic scores. One hand is tracked
at a time to prevent false swipes between different hands.

## Checks

```bash
python -m unittest discover -s tests -v
python -m pip check
```

A physical camera and macOS permissions are needed to verify real gestures and
keyboard/mouse actions interactively.
