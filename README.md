# NOVA Smart Hand Gesturing

NOVA Smart Hand Gesturing is a project that will use a webcam to detect
and understand hand gestures, eventually converting them into computer
interactions (mouse, keyboard, and system control). This repository
currently contains only the **foundation** the rest of the project will
be built on.

## Current Project Status: Base / Layer 1

This is a **base architecture only** release. It intentionally does
**not** include:

- Gesture recognition or classification
- Hand landmark drawing
- Mouse, keyboard, or system control
- Voice recognition, AI models, or a GUI

The goal of Layer 1 is a clean, modular, and easily extendable
foundation — nothing more.

## Installation

1. Ensure you have **Python 3.12** installed.
2. Create and activate a virtual environment (recommended):

   ```bash
   python3.12 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Running the Project

```bash
python main.py
```

This will:

1. Load configuration from `config/settings.json`.
2. Initialize the camera subsystem.
3. Open a window showing the raw camera feed.
4. Let you exit safely by pressing `q`.

No hand landmarks or gesture overlays are drawn in this layer.

## Current Architecture

```text
NOVA-HandGestures/
│
├── main.py                  # Application entry point
├── requirements.txt         # Base dependencies
├── README.md
├── .gitignore
│
├── camera/
│   └── camera.py            # Reusable webcam abstraction
│
├── tracking/
│   └── hand_tracker.py      # Placeholder for future MediaPipe hand tracking
│
├── gestures/
│   ├── detector.py          # Placeholder for future feature detection
│   ├── classifier.py        # Placeholder for future gesture classification
│   └── gestures.py          # Placeholder gesture definitions
│
├── actions/
│   ├── mouse.py             # Placeholder for future mouse control
│   ├── keyboard.py          # Placeholder for future keyboard control
│   └── system.py            # Placeholder for future system control
│
├── config/
│   └── settings.json        # Camera index, resolution, FPS, etc.
│
└── tests/                   # Reserved for future unit tests
```

Each package is independent and has no hidden dependencies on the
others, so future layers can be built incrementally without reshaping
existing code.

## Future Layers (Not Yet Implemented)

- **Layer 2:** Real hand landmark tracking with MediaPipe, and drawing
  landmarks on the camera feed.
- **Layer 3:** Gesture feature detection and classification (e.g.
  thumbs-up, peace sign, pointing).
- **Layer 4:** Translating recognized gestures into real mouse and
  keyboard actions using PyAutoGUI.
- **Layer 5:** System-level actions such as volume, brightness, media,
  and window control.
- **Layer 6+:** Configuration UI, gesture customization, and further
  refinements.

This README will be updated as each layer is added.
