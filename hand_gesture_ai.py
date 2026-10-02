"""Standalone, cross-platform hand gesture control desktop application.

Install dependencies with: python -m pip install -r requirements.txt
Run with: python hand_gesture_ai.py
"""
from __future__ import annotations

import json
import logging
import math
import platform
import queue
import threading
import time
from collections import deque
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

APP_NAME = "Hand Gesture AI"
GESTURES = ("Open Palm", "Fist", "Point", "Peace", "Three Fingers", "Four Fingers",
            "Thumbs Up", "Thumbs Down", "OK Sign", "Pinch", "Swipe Left",
            "Swipe Right", "Swipe Up", "Swipe Down")
MODIFIERS = {"ctrl": "CTRL", "alt": "ALT", "shift": "SHIFT", "cmd": "CMD", "win": "CMD"}
DEFAULTS = {
    "Open Palm": {"type": "keyboard", "keys": ["SPACE"]},
    "Fist": {"type": "keyboard", "keys": ["CMD" if platform.system() == "Darwin" else "CTRL", "S"]},
    "Point": {"type": "keyboard", "keys": ["F"]},
    "Peace": {"type": "keyboard", "keys": ["CTRL", "SHIFT", "P"]},
    "Three Fingers": {"type": "none"}, "Four Fingers": {"type": "none"},
    "Thumbs Up": {"type": "none"}, "Thumbs Down": {"type": "none"},
    "OK Sign": {"type": "none"}, "Pinch": {"type": "mouse", "button": "LEFT"},
    "Swipe Left": {"type": "keyboard", "keys": ["LEFT"]},
    "Swipe Right": {"type": "keyboard", "keys": ["RIGHT"]},
    "Swipe Up": {"type": "none"}, "Swipe Down": {"type": "none"},
}
CONFIG_DIR = Path.home() / ".hand-gesture-ai"
CONFIG_PATH = CONFIG_DIR / "config.json"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(APP_NAME)


def load_config(path: Path = CONFIG_PATH) -> tuple[dict, str | None]:
    """Load validated user settings, recovering cleanly from absent/bad files."""
    config = {"bindings": json.loads(json.dumps(DEFAULTS)), "camera": 0,
              "width": 640, "height": 480, "detection": .55, "tracking": .5,
              "stable_frames": 6, "cooldown": 1.0, "swipe_sensitivity": .16,
              "mirror": True, "landmarks": True, "show_fps": True}
    if not path.exists():
        return config, None
    try:
        incoming = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(incoming, dict):
            raise ValueError("The configuration root must be an object")
        for key in ("camera", "width", "height", "stable_frames"):
            if key in incoming and isinstance(incoming[key], int) and incoming[key] >= (0 if key == "camera" else 1):
                config[key] = incoming[key]
        for key in ("detection", "tracking", "cooldown", "swipe_sensitivity"):
            if key in incoming and isinstance(incoming[key], (int, float)) and math.isfinite(incoming[key]):
                config[key] = max(0.0, min(float(incoming[key]), 1.0 if key in ("detection", "tracking") else 10.0))
        if config["swipe_sensitivity"] <= 0:
            config["swipe_sensitivity"] = .16
        for key in ("mirror", "landmarks", "show_fps"):
            if key in incoming and isinstance(incoming[key], bool): config[key] = incoming[key]
        bindings = incoming.get("bindings", {})
        if not isinstance(bindings, dict):
            raise ValueError("Bindings must be an object")
        for name, action in bindings.items():
            if name in GESTURES and isinstance(action, dict) and action.get("type") in ("keyboard", "mouse", "none"):
                if action["type"] == "keyboard" and isinstance(action.get("keys"), list) and action["keys"]:
                    config["bindings"][name] = {"type": "keyboard", "keys": [str(k).upper() for k in action["keys"]]}
                elif action["type"] == "mouse" and action.get("button") in ("LEFT", "RIGHT", "MIDDLE", "SCROLL_UP", "SCROLL_DOWN"):
                    config["bindings"][name] = {"type": "mouse", "button": action["button"]}
                elif action["type"] == "none": config["bindings"][name] = {"type": "none"}
        return config, None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return config, f"Could not read settings; safe defaults are loaded. Details: {exc}"


def save_config(config: dict, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def finger_states(points: list[tuple[float, float, float]]) -> list[bool]:
    """Return extended states for index, middle, ring and little fingers."""
    # Compare tip-to-wrist and PIP-to-wrist distances, normalized by palm size.
    wrist = points[0]
    result = []
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        result.append(math.dist(points[tip][:2], wrist[:2]) > math.dist(points[pip][:2], wrist[:2]) * 1.12)
    return result


def classify_gesture(points: list[tuple[float, float, float]]) -> tuple[str, float]:
    """Classify a MediaPipe 21-point hand using normalized landmark geometry."""
    if len(points) != 21: return "Unknown", 0.0
    fingers = finger_states(points)
    thumb_extended = math.dist(points[4][:2], points[0][:2]) > math.dist(points[3][:2], points[0][:2]) * 1.08
    count = sum(fingers)
    pinch_dist = math.dist(points[4][:2], points[8][:2])
    palm = max(math.dist(points[0][:2], points[9][:2]), .001)
    if pinch_dist < palm * .32:
        # OK requires a ring formed by thumb/index while other fingers extend.
        return ("OK Sign" if sum(fingers[1:]) >= 2 else "Pinch"), .87
    if count == 4 and thumb_extended: return "Open Palm", .91
    if count == 0 and not thumb_extended: return "Fist", .88
    if count == 1 and fingers[0]: return "Point", .86
    if count == 2 and fingers[:2] == [True, True]: return "Peace", .88
    if count == 3 and all(fingers[:3]): return "Three Fingers", .84
    if count == 4: return "Four Fingers", .82
    # Thumb direction is measured against the palm axis, independent of image size.
    if thumb_extended and count == 0:
        dy = points[4][1] - points[2][1]
        if abs(dy) > palm * .15:
            return ("Thumbs Up" if dy < 0 else "Thumbs Down"), .78
    return "Unknown", .35


class SwipeDetector:
    def __init__(self, sensitivity: float = .16, window: float = .42):
        self.sensitivity, self.window = sensitivity, window
        self.samples: deque = deque()

    def update(self, center: tuple[float, float], now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        self.samples.append((now, center))
        while self.samples and now - self.samples[0][0] > self.window: self.samples.popleft()
        if len(self.samples) < 3: return None
        start, end = self.samples[0][1], center
        dx, dy = end[0] - start[0], end[1] - start[1]
        if max(abs(dx), abs(dy)) < self.sensitivity: return None
        self.samples.clear()
        return "Swipe " + ("Right" if dx > 0 else "Left") if abs(dx) > abs(dy) else "Swipe " + ("Down" if dy > 0 else "Up")


class InputController:
    """Restricted keyboard/mouse actions with guaranteed key release."""
    def __init__(self):
        from pynput.keyboard import Controller as KeyboardController, Key
        from pynput.mouse import Controller as MouseController, Button
        self.keyboard, self.mouse = KeyboardController(), MouseController()
        self.Key, self.Button = Key, Button

    def execute(self, action: dict) -> None:
        kind = action.get("type")
        if kind == "keyboard":
            keys = action.get("keys", [])
            pressed = []
            try:
                for name in keys:
                    key = self._key(name); self.keyboard.press(key); pressed.append(key)
                time.sleep(.045)
            finally:
                for key in reversed(pressed):
                    try: self.keyboard.release(key)
                    except Exception: log.exception("Could not release simulated key")
        elif kind == "mouse":
            button = action.get("button")
            mapping = {"LEFT": self.Button.left, "RIGHT": self.Button.right, "MIDDLE": self.Button.middle}
            if button in mapping: self.mouse.click(mapping[button])
            elif button == "SCROLL_UP": self.mouse.scroll(0, 2)
            elif button == "SCROLL_DOWN": self.mouse.scroll(0, -2)

    def _key(self, name: str):
        normalized = name.upper()
        special = {"CTRL": self.Key.ctrl, "ALT": self.Key.alt, "SHIFT": self.Key.shift,
                   "CMD": self.Key.cmd, "SPACE": self.Key.space, "ENTER": self.Key.enter,
                   "TAB": self.Key.tab, "ESC": self.Key.esc, "BACKSPACE": self.Key.backspace,
                   "DELETE": self.Key.delete, "INSERT": self.Key.insert, "HOME": self.Key.home,
                   "END": self.Key.end, "PAGEUP": self.Key.page_up, "PAGEDOWN": self.Key.page_down,
                   "UP": self.Key.up, "DOWN": self.Key.down, "LEFT": self.Key.left, "RIGHT": self.Key.right}
        if normalized in special: return special[normalized]
        if normalized.startswith("F") and normalized[1:].isdigit(): return getattr(self.Key, normalized.lower())
        if len(normalized) == 1 and normalized.isalnum(): return normalized.lower()
        raise ValueError(f"Unsupported key: {name}")


class CameraWorker(threading.Thread):
    def __init__(self, config: dict, events: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.config, self.events, self.stop_event = config, events, stop_event

    def run(self):
        cap = None
        try:
            import cv2
            import mediapipe as mp
            if not hasattr(mp, "solutions"):
                raise RuntimeError("Incompatible MediaPipe. Install requirements.txt using Python 3.9–3.12.")
            cap = cv2.VideoCapture(self.config["camera"])
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config["width"])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config["height"])
            if not cap.isOpened():
                self.events.put(("error", f"Camera {self.config['camera']} could not be opened. Check camera permissions or choose another camera.")); return
            self.events.put(("status", "Camera connected · MediaPipe ready"))
            hands_api = mp.solutions.hands
            with hands_api.Hands(static_image_mode=False, max_num_hands=1,
                    min_detection_confidence=self.config["detection"], min_tracking_confidence=self.config["tracking"]) as hands:
                swipe = SwipeDetector(self.config["swipe_sensitivity"])
                last = time.monotonic()
                while not self.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        self.events.put(("error", "Camera disconnected or stopped returning frames.")); break
                    if self.config["mirror"]: frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    result = hands.process(rgb)
                    gesture, confidence, hand_name = "No hand", 0.0, "—"
                    if not result.multi_hand_landmarks:
                        swipe.samples.clear()
                    if result.multi_hand_landmarks:
                        for ix, landmarks in enumerate(result.multi_hand_landmarks):
                            points = [(p.x, p.y, p.z) for p in landmarks.landmark]
                            hand_name = result.multi_handedness[ix].classification[0].label if result.multi_handedness else "Hand"
                            candidate, score = classify_gesture(points)
                            gesture, confidence = candidate, score
                            if self.config["landmarks"]: mp.solutions.drawing_utils.draw_landmarks(frame, landmarks, hands_api.HAND_CONNECTIONS)
                            motion = swipe.update((points[0][0], points[0][1]))
                            if motion: gesture, confidence = motion, .8
                    now = time.monotonic(); fps = 1 / max(now - last, .001); last = now
                    cv2.putText(frame, f"{gesture}  {confidence:.0%}", (15, 32), cv2.FONT_HERSHEY_SIMPLEX, .8, (60, 220, 120), 2)
                    if self.config["show_fps"]: cv2.putText(frame, f"{fps:.0f} FPS", (15, 62), cv2.FONT_HERSHEY_SIMPLEX, .6, (240, 240, 240), 2)
                    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
                    if ok and self.events.qsize() < 2: self.events.put(("frame", (jpg.tobytes(), gesture, confidence, hand_name, fps)))
        except Exception as exc:
            log.exception("Camera/tracking failure")
            self.events.put(("error", f"Camera or hand tracking failed: {exc}"))
        finally:
            if cap is not None: cap.release()
            self.events.put(("status", "Camera stopped"))


class GestureApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.font_family = tkfont.nametofont("TkDefaultFont").actual("family")
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(1320, max(760, screen_width - 72))
        height = min(840, max(620, screen_height - 100))
        self.minsize(min(760, max(620, screen_width - 32)), min(620, max(520, screen_height - 48)))
        x, y = max(0, (screen_width - width) // 2), max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.configure(bg="#070707")
        self.config_data, warning = load_config()
        self.events, self.stop_event = queue.Queue(), threading.Event()
        self.worker = None; self.control_enabled = False; self.emergency = False
        self.stable_name, self.stable_count, self.last_action = None, 0, {}
        self.fired_gesture = None
        self.input = None; self.listener = None; self.recording = None; self.preview_image = None
        self.record_var = None
        self._style(); self._build(); self._start_listener(); self.after(40, self._poll)
        self.bind("<Configure>", self._queue_responsive_layout)
        self.after_idle(self._apply_responsive_layout)
        self.bind("<Escape>", lambda _event: self.emergency_stop())
        self.protocol("WM_DELETE_WINDOW", self.close)
        if warning: self.after(300, lambda: messagebox.showwarning("Settings recovered", warning))

    def _style(self):
        style = ttk.Style(self); style.theme_use("clam")
        style.configure("Treeview", background="#0b0b0b", fieldbackground="#0b0b0b", foreground="#ededed",
                        rowheight=42, borderwidth=0, relief="flat", font=(self.font_family, 10))
        style.configure("Treeview.Heading", background="#111111", foreground="#a8a8a8", relief="flat",
                        font=(self.font_family, 9, "bold"), padding=(12, 12))
        style.map("Treeview", background=[("selected", "#f2f2f2")], foreground=[("selected", "#080808")])
        style.map("Treeview.Heading", background=[("active", "#191919")])
        style.configure("Vertical.TScrollbar", background="#171717", troughcolor="#080808", bordercolor="#080808",
                         arrowcolor="#d0d0d0", relief="flat")

    def _build(self):
        self.status = tk.StringVar(value="Stopped · Press Start")
        shell = tk.Frame(self, bg="#070707"); shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(1, weight=1); shell.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(shell, bg="#0b0b0b", width=236, highlightthickness=1, highlightbackground="#242424")
        sidebar.grid(row=0, column=0, sticky="ns"); sidebar.grid_propagate(False)
        self.sidebar = sidebar
        brand = tk.Frame(sidebar, bg="#0b0b0b"); brand.pack(fill="x", padx=22, pady=(28, 38))
        self.brand = brand
        tk.Label(brand, text="N", font=(self.font_family, 18, "bold"), fg="#080808", bg="#f2f2f2", width=2, height=1).pack(side="left")
        brand_text = tk.Frame(brand, bg="#0b0b0b"); brand_text.pack(side="left", padx=11)
        self.brand_text = brand_text
        tk.Label(brand_text, text="NOVA", font=(self.font_family, 14, "bold"), fg="#f5f5f5", bg="#0b0b0b").pack(anchor="w")
        tk.Label(brand_text, text="GESTURE CONTROL", font=(self.font_family, 8, "bold"), fg="#777777", bg="#0b0b0b").pack(anchor="w", pady=(2, 0))
        self.workspace_label = tk.Label(sidebar, text="WORKSPACE", font=(self.font_family, 8, "bold"), fg="#666666", bg="#0b0b0b")
        self.workspace_label.pack(anchor="w", padx=23, pady=(0, 10))
        self.nav_buttons = {}
        self.nav_titles = {}
        for key, index, title in (("home", "01", "Live control"), ("keys", "02", "Gesture actions"), ("settings", "03", "Settings")):
            button = tk.Button(sidebar, text=f"{index}     {title}", command=lambda page=key: self._show_page(page),
                               font=(self.font_family, 10, "bold"), anchor="w", padx=16, pady=13, bd=0,
                               relief="flat", cursor="hand2", bg="#0b0b0b", fg="#a9a9a9",
                               activebackground="#f1f1f1", activeforeground="#090909", highlightthickness=0)
            button.pack(fill="x", padx=12, pady=3); self.nav_buttons[key] = button; self.nav_titles[key] = (index, title)
            button.bind("<Enter>", lambda _event, page=key: self._nav_hover(page, True))
            button.bind("<Leave>", lambda _event, page=key: self._nav_hover(page, False))
            button.bind("<FocusIn>", lambda _event, widget=button: widget.configure(highlightthickness=1, highlightbackground="#ffffff"))
            button.bind("<FocusOut>", lambda _event, widget=button: widget.configure(highlightthickness=0))
        footer = tk.Frame(sidebar, bg="#0b0b0b"); footer.pack(side="bottom", fill="x", padx=22, pady=22)
        tk.Frame(footer, bg="#353535", height=1).pack(fill="x", pady=(0, 15))
        self.local_status = tk.Label(footer, text="●  LOCAL SESSION", font=(self.font_family, 8, "bold"), fg="#d8d8d8", bg="#0b0b0b")
        self.local_status.pack(anchor="w")
        self.local_hint = tk.Label(footer, text="Actions stay off until enabled", font=(self.font_family, 8), fg="#737373", bg="#0b0b0b")
        self.local_hint.pack(anchor="w", padx=(14, 0), pady=(5, 0))

        content = tk.Frame(shell, bg="#070707"); content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1); content.grid_rowconfigure(1, weight=1)
        header = tk.Frame(content, bg="#070707"); header.grid(row=0, column=0, sticky="ew", padx=34, pady=(28, 20))
        title_box = tk.Frame(header, bg="#070707"); title_box.pack(side="left")
        self.section_title = tk.Label(title_box, text="LIVE CONTROL", font=(self.font_family, 19, "bold"), fg="#f4f4f4", bg="#070707")
        self.section_title.pack(anchor="w")
        self.section_subtitle = tk.Label(title_box, text="Camera preview and action status", font=(self.font_family, 9), fg="#868686", bg="#070707")
        self.section_subtitle.pack(anchor="w", pady=(5, 0))
        status_box = tk.Frame(header, bg="#111111", highlightthickness=1, highlightbackground="#292929")
        status_box.pack(side="right", pady=3)
        tk.Label(status_box, text="●", font=(self.font_family, 10), fg="#d8d8d8", bg="#111111").pack(side="left", padx=(11, 5), pady=9)
        tk.Label(status_box, textvariable=self.status, font=(self.font_family, 9), fg="#dedede", bg="#111111").pack(side="left", padx=(0, 12), pady=9)
        self.page_host = tk.Frame(content, bg="#070707"); self.page_host.grid(row=1, column=0, sticky="nsew", padx=34, pady=(0, 28))
        self.page_host.grid_columnconfigure(0, weight=1); self.page_host.grid_rowconfigure(0, weight=1)
        self.home = tk.Frame(self.page_host, bg="#070707")
        self.keys_tab = tk.Frame(self.page_host, bg="#070707")
        self.settings_tab = tk.Frame(self.page_host, bg="#070707")
        self.pages = {"home": self.home, "keys": self.keys_tab, "settings": self.settings_tab}
        for page in self.pages.values(): page.grid(row=0, column=0, sticky="nsew")
        self._build_home(); self._build_keys(); self._build_settings()
        self._show_page("home")

    def _nav_hover(self, page, entered):
        button = self.nav_buttons.get(page)
        if button is None or page == getattr(self, "active_page", None): return
        button.configure(bg="#191919" if entered else "#0b0b0b", fg="#ffffff" if entered else "#a9a9a9")

    def _queue_responsive_layout(self, event):
        if event.widget is not self: return
        pending = getattr(self, "_resize_job", None)
        if pending is not None:
            try: self.after_cancel(pending)
            except tk.TclError: pass
        self._resize_job = self.after(80, self._apply_responsive_layout)

    def _apply_responsive_layout(self):
        if not hasattr(self, "sidebar"): return
        compact = self.winfo_width() < 1080
        self.sidebar.configure(width=76 if compact else 236)
        self.sidebar.grid_propagate(False)
        if compact:
            self.brand.pack_configure(anchor="center", padx=0)
            self.brand_text.pack_forget(); self.workspace_label.pack_forget()
            for page, button in self.nav_buttons.items():
                button.configure(text=self.nav_titles[page][0], anchor="center", padx=4)
            self.local_status.configure(text="●"); self.local_hint.pack_forget()
        else:
            self.brand.pack_configure(anchor="w", padx=22)
            if not self.brand_text.winfo_manager(): self.brand_text.pack(side="left", padx=11)
            if not self.workspace_label.winfo_manager():
                self.workspace_label.pack(anchor="w", padx=23, pady=(0, 10), before=next(iter(self.nav_buttons.values())))
            for page, button in self.nav_buttons.items():
                index, title = self.nav_titles[page]
                button.configure(text=f"{index}     {title}", anchor="w", padx=16)
            self.local_status.configure(text="●  LOCAL SESSION")
            if not self.local_hint.winfo_manager(): self.local_hint.pack(anchor="w", padx=(14, 0), pady=(5, 0))
        narrow_actions = self.winfo_width() < 930
        self.start_button.configure(text="START" if narrow_actions else "START CAMERA")
        self._update_control_button_label(narrow_actions)
        if hasattr(self, "camera_card"):
            if narrow_actions:
                self.camera_card.grid_configure(row=0, column=0, columnspan=2, padx=0)
                self.recognition_card.grid_configure(row=1, column=0, columnspan=2, padx=0)
                self.visual_card.grid_configure(row=2, column=0, columnspan=2)
            else:
                self.camera_card.grid_configure(row=0, column=0, columnspan=1, padx=(0, 9))
                self.recognition_card.grid_configure(row=0, column=1, columnspan=1, padx=(9, 0))
                self.visual_card.grid_configure(row=1, column=0, columnspan=2)
        if hasattr(self, "tree"):
            if narrow_actions:
                self.tree.column("#0", width=190, minwidth=140)
                self.tree.column("action", width=230, minwidth=150)
            else:
                self.tree.column("#0", width=260, minwidth=190)
                self.tree.column("action", width=340, minwidth=200)
        if hasattr(self, "key_action_bar") and getattr(self, "_key_actions_compact", None) != narrow_actions:
            previous_layout = getattr(self, "_key_actions_compact", None)
            self._key_actions_compact = narrow_actions
            for button in self.key_action_buttons:
                if previous_layout is True: button.grid_forget()
                else: button.pack_forget()
            if narrow_actions:
                for column in range(3): self.key_action_bar.grid_columnconfigure(column, weight=1, uniform="keyactions")
                for index, button in enumerate(self.key_action_buttons):
                    button.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 8), pady=3)
            else:
                for column in range(3): self.key_action_bar.grid_columnconfigure(column, weight=0, uniform="")
                for button in self.key_action_buttons: button.pack(side="left", padx=(0, 8))

    def _update_control_button_label(self, compact=False):
        if not hasattr(self, "control_button"): return
        if compact:
            self.control_button.configure(text="ACTIONS ON" if self.control_enabled else "ACTIONS OFF")
        else:
            self.control_button.configure(text="DISABLE ACTIONS" if self.control_enabled else "ENABLE ACTIONS")

    def _show_page(self, page):
        titles = {"home": ("LIVE CONTROL", "Camera preview and action status"),
                  "keys": ("GESTURE ACTIONS", "Map gestures to shortcuts and mouse actions"),
                  "settings": ("SETTINGS", "Tune the camera and recognition experience")}
        self.pages[page].tkraise()
        self.active_page = page
        title, subtitle = titles[page]
        self.section_title.configure(text=title); self.section_subtitle.configure(text=subtitle)
        for key, button in self.nav_buttons.items():
            selected = key == page
            button.configure(bg="#f1f1f1" if selected else "#0b0b0b", fg="#080808" if selected else "#a9a9a9")

    def _build_home(self):
        self.home.grid_columnconfigure(0, weight=1); self.home.grid_rowconfigure(0, weight=1)
        left = tk.Frame(self.home, bg="#070707"); left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        left.grid_columnconfigure(0, weight=1); left.grid_rowconfigure(0, weight=1)
        right = tk.Frame(self.home, bg="#0d0d0d", width=270, highlightthickness=1, highlightbackground="#292929")
        right.grid(row=0, column=1, sticky="ns"); right.grid_propagate(False)
        preview_card = tk.Frame(left, bg="#0c0c0c", highlightthickness=1, highlightbackground="#292929")
        preview_card.grid(row=0, column=0, sticky="nsew"); preview_card.grid_columnconfigure(0, weight=1); preview_card.grid_rowconfigure(1, weight=1)
        preview_head = tk.Frame(preview_card, bg="#0c0c0c"); preview_head.grid(row=0, column=0, sticky="ew", padx=18, pady=15)
        tk.Label(preview_head, text="LIVE PREVIEW", font=(self.font_family, 9, "bold"), fg="#f0f0f0", bg="#0c0c0c").pack(side="left")
        tk.Label(preview_head, text="CAMERA  /  LOCAL", font=(self.font_family, 8, "bold"), fg="#777777", bg="#0c0c0c").pack(side="right")
        self.preview = tk.Label(preview_card, text="CAMERA OFFLINE\n\nStart the camera to begin your session", bg="#050505", fg="#8b8b8b", font=(self.font_family, 11), justify="center")
        self.preview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        buttons = tk.Frame(left, bg="#070707"); buttons.grid(row=1, column=0, sticky="ew", pady=(15, 0))
        self.start_button = self._button(buttons, "START CAMERA", self.start_camera, "#ffffff"); self.start_button.pack(side="left", padx=(0, 9))
        self.stop_button = self._button(buttons, "STOP", self.stop_camera, "#252525"); self.stop_button.pack(side="left", padx=2)
        self.control_var = tk.BooleanVar(value=False)
        self.control_button = self._button(buttons, "ENABLE ACTIONS", self.toggle_control, "#ffffff"); self.control_button.pack(side="right")
        tk.Label(right, text="SESSION OVERVIEW", fg="#7d7d7d", bg="#0d0d0d", font=(self.font_family, 8, "bold")).pack(anchor="w", padx=19, pady=(20, 18))
        tk.Frame(right, bg="#292929", height=1).pack(fill="x", padx=19)
        tk.Label(right, text="CURRENT GESTURE", fg="#777777", bg="#0d0d0d", font=(self.font_family, 8, "bold")).pack(anchor="w", padx=19, pady=(19, 7))
        self.gesture_text = tk.StringVar(value="—"); self.hand_text = tk.StringVar(value="Hand: —"); self.conf_text = tk.StringVar(value="Confidence: —"); self.fps_text = tk.StringVar(value="FPS: —")
        tk.Label(right, textvariable=self.gesture_text, fg="#f4f4f4", bg="#0d0d0d", font=(self.font_family, 20, "bold"), wraplength=220, justify="left").pack(anchor="w", padx=19, pady=(0, 13))
        for var in (self.hand_text, self.conf_text, self.fps_text):
            tk.Label(right, textvariable=var, fg="#b0b0b0", bg="#0d0d0d", font=(self.font_family, 10), justify="left").pack(anchor="w", padx=19, pady=6)
        tk.Frame(right, bg="#292929", height=1).pack(fill="x", padx=19, pady=(18, 17))
        tk.Label(right, text="ACTION SAFETY", fg="#f0f0f0", bg="#0d0d0d", font=(self.font_family, 9, "bold")).pack(anchor="w", padx=19)
        tk.Label(right, text="Press Escape at any time to disable gesture-triggered actions.", fg="#969696", bg="#0d0d0d", wraplength=220, justify="left", font=(self.font_family, 9)).pack(anchor="w", padx=19, pady=(8, 13))
        self._button(right, "STOP ACTIONS NOW", self.emergency_stop, "#252525").pack(fill="x", padx=19, pady=(3, 17))

    def _build_keys(self):
        self.keys_tab.grid_columnconfigure(0, weight=1); self.keys_tab.grid_rowconfigure(1, weight=1)
        intro = tk.Frame(self.keys_tab, bg="#070707"); intro.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        tk.Label(intro, text="GESTURE MAPPINGS", font=(self.font_family, 9, "bold"), fg="#eeeeee", bg="#070707").pack(anchor="w")
        tk.Label(intro, text="Select a gesture to record a shortcut, choose a mouse action, or clear its assignment.", font=(self.font_family, 9), fg="#858585", bg="#070707").pack(anchor="w", pady=(5, 0))
        table = tk.Frame(self.keys_tab, bg="#0b0b0b", highlightthickness=1, highlightbackground="#292929")
        table.grid(row=1, column=0, sticky="nsew"); table.grid_columnconfigure(0, weight=1); table.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("action",), show="headings", height=15, selectmode="browse")
        self.tree.heading("action", text="CURRENT ACTION"); self.tree.column("action", width=340, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=1)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", lambda _e: self.edit_binding())
        bar = tk.Frame(self.keys_tab, bg="#070707"); bar.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.key_action_bar = bar; self.key_action_buttons = []
        for title, fn in (("Record / Edit", self.edit_binding), ("Clear", self.clear_binding), ("Save", self.save), ("Reset Defaults", self.reset_defaults), ("Import", self.import_config), ("Export", self.export_config)):
            button = self._button(bar, title, fn, "#252525"); button.pack(side="left", padx=(0, 8)); self.key_action_buttons.append(button)
        self._refresh_tree()

    def _build_settings(self):
        self.settings_tab.grid_columnconfigure(0, weight=1)
        intro = tk.Frame(self.settings_tab, bg="#070707"); intro.pack(fill="x", pady=(0, 14))
        tk.Label(intro, text="APPLICATION PREFERENCES", font=(self.font_family, 9, "bold"), fg="#eeeeee", bg="#070707").pack(anchor="w")
        tk.Label(intro, text="Changes are stored locally and applied to the next camera session.", font=(self.font_family, 9), fg="#858585", bg="#070707").pack(anchor="w", pady=(5, 0))
        form_shell = tk.Frame(self.settings_tab, bg="#070707"); form_shell.pack(fill="both", expand=True)
        form_shell.grid_rowconfigure(0, weight=1); form_shell.grid_columnconfigure(0, weight=1)
        self.settings_canvas = tk.Canvas(form_shell, bg="#070707", highlightthickness=0, bd=0)
        self.settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_scrollbar = ttk.Scrollbar(form_shell, orient="vertical", command=self.settings_canvas.yview, style="Vertical.TScrollbar")
        settings_scrollbar.grid(row=0, column=1, sticky="ns")
        self.settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
        form = tk.Frame(self.settings_canvas, bg="#070707")
        self.settings_form_window = self.settings_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all")))
        self.settings_canvas.bind("<Configure>", lambda event: self.settings_canvas.itemconfigure(self.settings_form_window, width=event.width))
        self.bind_all("<MouseWheel>", self._settings_mousewheel, add="+")
        form.grid_columnconfigure(0, weight=1); form.grid_columnconfigure(1, weight=1)
        self.setting_vars = {}
        camera_card = tk.Frame(form, bg="#0d0d0d", highlightthickness=1, highlightbackground="#292929")
        self.camera_card = camera_card
        camera_card.grid(row=0, column=0, sticky="nsew", padx=(0, 9), pady=(0, 12))
        recognition_card = tk.Frame(form, bg="#0d0d0d", highlightthickness=1, highlightbackground="#292929")
        self.recognition_card = recognition_card
        recognition_card.grid(row=0, column=1, sticky="nsew", padx=(9, 0), pady=(0, 12))
        visual_card = tk.Frame(form, bg="#0d0d0d", highlightthickness=1, highlightbackground="#292929")
        self.visual_card = visual_card
        visual_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        def card_heading(card, title, subtitle):
            tk.Label(card, text=title, font=(self.font_family, 10, "bold"), fg="#f0f0f0", bg="#0d0d0d").pack(anchor="w", padx=18, pady=(16, 4))
            tk.Label(card, text=subtitle, font=(self.font_family, 8), fg="#808080", bg="#0d0d0d").pack(anchor="w", padx=18, pady=(0, 11))

        def entry_row(card, key, label, kind):
            row = tk.Frame(card, bg="#0d0d0d"); row.pack(fill="x", padx=18, pady=6)
            tk.Label(row, text=label, fg="#c9c9c9", bg="#0d0d0d", font=(self.font_family, 9), anchor="w").pack(side="left", fill="x", expand=True)
            var = tk.StringVar(value=str(self.config_data[key])); self.setting_vars[key] = (var, kind)
            tk.Entry(row, textvariable=var, bg="#080808", fg="#f2f2f2", insertbackground="#ffffff", relief="flat",
                     highlightthickness=1, highlightbackground="#333333", highlightcolor="#eeeeee", width=12,
                     font=(self.font_family, 9), justify="center").pack(side="right", ipady=6)

        card_heading(camera_card, "CAMERA", "Capture device and frame dimensions")
        for key, label, kind in (("camera", "Camera index", "int"), ("width", "Preview width", "int"), ("height", "Preview height", "int")):
            entry_row(camera_card, key, label, kind)
        card_heading(recognition_card, "RECOGNITION", "Stability, sensitivity and cooldown")
        for key, label, kind in (("detection", "Detection confidence (0–1)", "float"), ("tracking", "Tracking confidence (0–1)", "float"),
                                 ("stable_frames", "Stable frames", "int"), ("cooldown", "Cooldown seconds", "float"),
                                 ("swipe_sensitivity", "Swipe sensitivity", "float")):
            entry_row(recognition_card, key, label, kind)
        card_heading(visual_card, "PREVIEW", "Display preferences")
        switches = tk.Frame(visual_card, bg="#0d0d0d"); switches.pack(fill="x", padx=18, pady=(0, 15))
        for key, label in (("mirror", "Mirror camera"), ("landmarks", "Show landmarks"), ("show_fps", "Show FPS")):
            var = tk.BooleanVar(value=self.config_data[key]); self.setting_vars[key] = (var, "bool")
            tk.Checkbutton(switches, text=label, variable=var, bg="#0d0d0d", fg="#d5d5d5", selectcolor="#080808",
                           activebackground="#0d0d0d", activeforeground="#ffffff", font=(self.font_family, 9),
                           highlightthickness=0, bd=0).pack(side="left", padx=(0, 25))
        actions = tk.Frame(self.settings_tab, bg="#070707"); actions.pack(fill="x", pady=(4, 0))
        self._button(actions, "SAVE SETTINGS", self.save_settings, "#ffffff").pack(side="left")
        tk.Label(actions, text=f"Stored locally  ·  {CONFIG_PATH}", bg="#070707", fg="#696969", font=(self.font_family, 8), wraplength=520).pack(side="left", padx=16)

    def _settings_mousewheel(self, event):
        if getattr(self, "active_page", None) != "settings": return
        delta = -1 if event.delta > 0 else 1
        amount = max(1, abs(event.delta) // 120)
        self.settings_canvas.yview_scroll(delta * amount, "units")
        return "break"

    def _button(self, parent, text, command, color):
        primary = text in ("START CAMERA", "ENABLE ACTIONS", "SAVE SETTINGS", "Save", "Record Shortcut", "Save Shortcut")
        button = tk.Button(parent, text=text, command=command, bg="#f0f0f0" if primary else "#111111",
                           fg="#080808" if primary else "#dedede", activebackground="#cfcfcf" if primary else "#292929",
                           activeforeground="#080808" if primary else "#ffffff", relief="flat", bd=0,
                           highlightthickness=1, highlightbackground="#414141" if not primary else "#f0f0f0",
                           highlightcolor="#ffffff", padx=15, pady=10, cursor="hand2",
                           font=(self.font_family, 9, "bold"), takefocus=True)
        normal = ("#f0f0f0", "#080808") if primary else ("#111111", "#dedede")
        hover = ("#d5d5d5", "#080808") if primary else ("#252525", "#ffffff")
        button.configure(disabledforeground="#737373")
        button.bind("<Enter>", lambda _event: button.configure(bg=hover[0], fg=hover[1]) if button.cget("state") != "disabled" else None)
        button.bind("<Leave>", lambda _event: button.configure(bg=normal[0], fg=normal[1]) if button.cget("state") != "disabled" else None)
        button.bind("<FocusIn>", lambda _event: button.configure(highlightbackground="#ffffff", highlightthickness=1))
        button.bind("<FocusOut>", lambda _event: button.configure(highlightbackground="#414141" if not primary else "#f0f0f0", highlightthickness=1))
        return button

    def _refresh_tree(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        for name in GESTURES:
            self.tree.insert("", "end", iid=name, values=(self._format_action(self.config_data["bindings"].get(name, {"type":"none"})),), text=name)
        self.tree.configure(show="tree headings"); self.tree.heading("#0", text="GESTURE")
        if self.winfo_width() < 930:
            self.tree.column("#0", width=190, minwidth=140); self.tree.column("action", width=230, minwidth=150)
        else:
            self.tree.column("#0", width=260, minwidth=190); self.tree.column("action", width=340, minwidth=200)

    @staticmethod
    def _format_action(action):
        if action.get("type") == "keyboard": return GestureApp._display_keys(action.get("keys", []))
        if action.get("type") == "mouse": return action.get("button", "").replace("_", " ").title()
        return "No action"

    @staticmethod
    def _display_keys(keys):
        if platform.system() == "Darwin":
            mac_symbols = {"CMD": "⌘", "CTRL": "⌃", "ALT": "⌥", "SHIFT": "⇧"}
            return " + ".join(mac_symbols.get(str(key).upper(), str(key).upper()) for key in keys)
        return " + ".join(str(key).upper() for key in keys)

    def _start_listener(self):
        try:
            from pynput import keyboard
            self.listener = keyboard.Listener(on_press=self._key_press, on_release=self._key_release)
            self.listener.start()
        except Exception as exc:
            log.warning("Global keyboard listener unavailable: %s", exc)

    def _key_press(self, key):
        if key == getattr(__import__('pynput').keyboard.Key, 'esc'):
            self.events.put(("emergency", None))
        if self.recording is None: return
        name = self._normalize_key(key)
        if name:
            self.recording.add(name)
            self.events.put(("record_update", None))

    def _key_release(self, _key):
        if self.recording is not None:
            self.events.put(("record_finish", None))

    @staticmethod
    def _normalize_key(key):
        try:
            from pynput.keyboard import Key
            mapping = {Key.ctrl: "CTRL", Key.ctrl_l: "CTRL", Key.ctrl_r: "CTRL", Key.alt: "ALT", Key.alt_l: "ALT", Key.alt_r: "ALT",
                       Key.shift: "SHIFT", Key.shift_l: "SHIFT", Key.shift_r: "SHIFT", Key.cmd: "CMD", Key.cmd_l: "CMD", Key.cmd_r: "CMD",
                       Key.space: "SPACE", Key.enter: "ENTER", Key.tab: "TAB", Key.esc: "ESC", Key.backspace: "BACKSPACE", Key.delete: "DELETE",
                       Key.insert: "INSERT", Key.home: "HOME", Key.end: "END", Key.page_up: "PAGEUP", Key.page_down: "PAGEDOWN",
                       Key.up: "UP", Key.down: "DOWN", Key.left: "LEFT", Key.right: "RIGHT"}
            if key in mapping: return mapping[key]
            if hasattr(key, "char") and key.char: return key.char.upper()
            if hasattr(key, "name") and key.name and key.name.startswith("f") and key.name[1:].isdigit(): return key.name.upper()
        except Exception: pass
        return None

    def edit_binding(self):
        selection = self.tree.selection()
        if not selection: messagebox.showinfo("Choose a gesture", "Select a gesture row first."); return
        name = selection[0]
        dialog = tk.Toplevel(self); dialog.title(f"Edit · {name}"); dialog.configure(bg="#080808"); dialog.transient(self); dialog.grab_set()
        dialog.geometry("480x370"); dialog.resizable(False, False)
        card = tk.Frame(dialog, bg="#101010", highlightthickness=1, highlightbackground="#303030")
        card.pack(fill="both", expand=True, padx=18, pady=18)
        tk.Label(card, text="GESTURE ACTION", fg="#777777", bg="#101010", font=(self.font_family, 8, "bold")).pack(anchor="w", padx=22, pady=(20, 6))
        tk.Label(card, text=name, fg="#f4f4f4", bg="#101010", font=(self.font_family, 17, "bold")).pack(anchor="w", padx=22)
        action = self.config_data["bindings"].get(name, {"type":"none"})
        current = tk.StringVar(value=self._format_action(action)); self.record_var = current
        current_box = tk.Frame(card, bg="#080808", highlightthickness=1, highlightbackground="#343434")
        current_box.pack(fill="x", padx=22, pady=(17, 10))
        tk.Label(current_box, textvariable=current, fg="#f0f0f0", bg="#080808", font=(self.font_family, 12, "bold")).pack(anchor="w", padx=13, pady=12)
        self.record_var = current
        tk.Label(card, text="Record a shortcut from your keyboard or assign a supported mouse action.", fg="#969696", bg="#101010", wraplength=390, justify="left", font=(self.font_family, 9)).pack(anchor="w", padx=22, pady=(0, 8))
        def record():
            self.recording = set(); current.set("Listening… press keys"); dialog.lift(); dialog.focus_force()
            dialog.bind("<Escape>", lambda _e: cancel_record())
        def cancel_record(): self.recording = None; current.set(self._format_action(action))
        def save_keys():
            keys = self.pending_keys
            if not keys: messagebox.showinfo("No shortcut", "No supported key was captured.", parent=dialog); return
            self.config_data["bindings"][name] = {"type":"keyboard", "keys":keys}; self._refresh_tree(); dialog.destroy()
        def set_mouse(button): self.config_data["bindings"][name] = {"type":"mouse", "button":button}; self._refresh_tree(); dialog.destroy()
        def set_none(): self.config_data["bindings"][name] = {"type":"none"}; self._refresh_tree(); dialog.destroy()
        self.pending_keys = []
        row = tk.Frame(card, bg="#101010"); row.pack(fill="x", padx=22, pady=(9, 12))
        self._button(row, "Record Shortcut", record, "#34445a").pack(side="left", padx=4)
        self._button(row, "Save Shortcut", save_keys, "#257c59").pack(side="left", padx=4)
        self._button(row, "Cancel Recording", cancel_record, "#394759").pack(side="left", padx=4)
        utility = tk.Frame(card, bg="#101010"); utility.pack(fill="x", padx=22, pady=(0, 16))
        self._button(utility, "Use Mouse Action…", lambda: self._mouse_picker(dialog, set_mouse), "#252525").pack(side="left", padx=(0, 8))
        self._button(utility, "Clear Action", set_none, "#252525").pack(side="left")
        dialog._rec_label = current

    def _update_record_label(self):
        # Active edit window owns the label; derive a stable modifier-first combination.
        if self.recording is not None:
            self.pending_keys = sorted(self.recording, key=lambda k: (k not in ("CTRL", "ALT", "SHIFT", "CMD"), k))
        if self.record_var is not None:
            self.record_var.set(self._display_keys(self.pending_keys) or ("Listening… press keys" if self.recording is not None else "No shortcut captured"))

    def _finish_recording(self):
        if self.recording is None: return
        # Wait briefly so the listener sees the full combination before presenting Save.
        keys = sorted(self.recording, key=lambda k: (k not in ("CTRL", "ALT", "SHIFT", "CMD"), k))
        self.recording = None; self.pending_keys = keys
        self._update_record_label()

    def _mouse_picker(self, parent, callback):
        picker = tk.Toplevel(parent); picker.title("Mouse action"); picker.configure(bg="#080808")
        picker.resizable(False, False)
        tk.Label(picker, text="SELECT MOUSE ACTION", bg="#080808", fg="#eeeeee", font=(self.font_family, 10, "bold")).pack(anchor="w", padx=18, pady=(18, 10))
        for key, label in (("LEFT", "Left Click"), ("RIGHT", "Right Click"), ("MIDDLE", "Middle Click"), ("SCROLL_UP", "Scroll Up"), ("SCROLL_DOWN", "Scroll Down")):
            self._button(picker, label, lambda k=key: (callback(k), picker.destroy()), "#252525").pack(fill="x", padx=18, pady=4)
        tk.Frame(picker, bg="#080808", height=12).pack()

    def clear_binding(self):
        sel = self.tree.selection()
        if sel: self.config_data["bindings"][sel[0]] = {"type":"none"}; self._refresh_tree()

    def save(self):
        try: save_config(self.config_data); self.status.set(f"Saved · {CONFIG_PATH}")
        except OSError as exc: messagebox.showerror("Save failed", str(exc))

    def reset_defaults(self):
        if messagebox.askyesno("Reset actions", "Restore example actions and settings defaults?"):
            self.config_data, _ = load_config(Path("__missing_defaults__.json")); self._refresh_tree(); self._write_settings_vars(); self.save()

    def _write_settings_vars(self):
        for key, (var, kind) in self.setting_vars.items(): var.set(self.config_data[key])

    def import_config(self):
        filename = filedialog.askopenfilename(filetypes=[("JSON configuration", "*.json")])
        if not filename: return
        imported, warning = load_config(Path(filename)); self.config_data = imported; self._refresh_tree(); self._write_settings_vars()
        if warning: messagebox.showwarning("Import recovered", warning)

    def export_config(self):
        filename = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON configuration", "*.json")])
        if filename:
            try: save_config(self.config_data, Path(filename)); messagebox.showinfo("Exported", "Configuration exported.")
            except OSError as exc: messagebox.showerror("Export failed", str(exc))

    def save_settings(self):
        try:
            updated = dict(self.config_data)
            for key, (var, kind) in self.setting_vars.items():
                updated[key] = var.get() if kind == "bool" else (int(var.get()) if kind == "int" else float(var.get()))
            if any(not math.isfinite(updated[key]) for key in ("detection", "tracking", "cooldown", "swipe_sensitivity")):
                raise ValueError("Settings must be finite numbers.")
            if not 0 <= updated["detection"] <= 1 or not 0 <= updated["tracking"] <= 1:
                raise ValueError("Confidence values must be between 0 and 1.")
            if updated["stable_frames"] < 1 or updated["cooldown"] < 0 or updated["swipe_sensitivity"] <= 0:
                raise ValueError("Stable frames and swipe sensitivity must be positive; cooldown cannot be negative.")
            if updated["camera"] < 0 or min(updated["width"], updated["height"]) < 1:
                raise ValueError("Camera index must be nonnegative and dimensions must be positive.")
            save_config(updated)
            self.config_data = updated
            messagebox.showinfo("Settings saved", "Settings will apply next time the camera starts.")
        except (ValueError, tk.TclError, OSError) as exc: messagebox.showerror("Invalid setting", str(exc))

    def start_camera(self):
        if self.worker and self.worker.is_alive(): return
        try:
            from pynput.keyboard import Controller as _KC
            self.input = InputController()
        except Exception as exc:
            self.input = None
            self.status.set("Input permissions needed")
            messagebox.showwarning("Input control unavailable", self._permission_message(str(exc)))
        self.events = queue.Queue()
        self.stable_name, self.stable_count, self.fired_gesture = None, 0, None
        self.stop_event.clear(); self.worker = CameraWorker(dict(self.config_data), self.events, self.stop_event); self.worker.start(); self.status.set("Starting camera…")

    def stop_camera(self):
        self.emergency_stop()
        self.stop_event.set(); self.status.set("Stopping camera…"); self.preview.configure(image="", text="Camera stopped\n\nPress START to connect")

    def toggle_control(self):
        if self.emergency:
            self.emergency = False
        self.control_enabled = not self.control_enabled
        self.control_var.set(self.control_enabled)
        self.control_button.configure(text="DISABLE ACTIONS" if self.control_enabled else "ENABLE ACTIONS",
                                      bg="#f0f0f0", fg="#080808", highlightbackground="#f0f0f0")
        self._update_control_button_label(self.winfo_width() < 930)
        self.status.set("Gesture actions enabled" if self.control_enabled else "Gesture actions disabled")

    def emergency_stop(self):
        self.emergency = True; self.control_enabled = False; self.control_var.set(False)
        if hasattr(self, "control_button"):
            self.control_button.configure(text="ENABLE ACTIONS", bg="#f0f0f0", fg="#080808", highlightbackground="#f0f0f0")
            self._update_control_button_label(self.winfo_width() < 930)
        self.status.set("EMERGENCY STOP · Actions disabled")

    def _handle_gesture(self, name, confidence):
        if confidence < .65:
            self.stable_name = None; self.stable_count = 0; self.fired_gesture = None; return
        if name != self.stable_name:
            self.stable_name, self.stable_count = name, 1
            self.fired_gesture = None
        else: self.stable_count += 1
        is_swipe = name.startswith("Swipe ")
        if (self.stable_count < self.config_data["stable_frames"] and not is_swipe) or not self.control_enabled or self.emergency: return
        if self.fired_gesture == name: return
        action = self.config_data["bindings"].get(name, {"type":"none"})
        now = time.monotonic()
        if action.get("type") == "none" or now - self.last_action.get(name, 0) < self.config_data["cooldown"]: return
        if self.input is None:
            self.status.set("Input unavailable · check Accessibility permissions"); return
        self.last_action[name] = now; self.stable_count = 0; self.fired_gesture = name
        try: self.input.execute(action); log.info("Action for %s: %s", name, self._format_action(action))
        except Exception as exc:
            self.emergency_stop(); messagebox.showerror("Input action failed", self._permission_message(str(exc)))

    @staticmethod
    def _permission_message(detail):
        if platform.system() == "Darwin":
            return ("macOS may require permissions for keyboard and mouse control. Open System Settings → Privacy & Security → Accessibility and enable the terminal or Python used to run this app. Also allow camera access under Privacy & Security → Camera.\n\n" + detail)
        return "Keyboard or mouse control could not be initialized. Check that the pynput dependency is installed and that security software permits input control.\n\n" + detail

    def _poll(self):
        try:
            for _ in range(8):
                kind, data = self.events.get_nowait()
                if kind == "emergency": self.emergency_stop()
                elif kind == "record_update": self._update_record_label()
                elif kind == "record_finish": self._finish_recording()
                elif kind == "status": self.status.set(data)
                elif kind == "error": self.emergency_stop(); self.status.set("Camera error"); messagebox.showerror("Camera / tracking", data)
                elif kind == "frame":
                    if self.stop_event.is_set(): continue
                    blob, gesture, confidence, hand, fps = data
                    try:
                        from PIL import Image, ImageTk
                        import io
                        source = Image.open(io.BytesIO(blob)).convert("RGB")
                        available_width = max(64, self.preview.winfo_width() - 24)
                        available_height = max(64, self.preview.winfo_height() - 24)
                        scale = min(1.25, available_width / source.width, available_height / source.height)
                        dimensions = (max(1, int(source.width * scale)), max(1, int(source.height * scale)))
                        resampling = getattr(Image, "Resampling", Image).LANCZOS
                        if source.size != dimensions: source = source.resize(dimensions, resampling)
                        image = ImageTk.PhotoImage(source)
                        self.preview.configure(image=image, text=""); self.preview.image = image
                    except ImportError:
                        # Pillow is installed as an OpenCV dependency in most environments; fallback retains status.
                        self.preview.configure(text="Preview display requires Pillow (pip install pillow)")
                    self.gesture_text.set(gesture); self.hand_text.set(f"Hand: {hand}"); self.conf_text.set(f"Confidence: {confidence:.0%}"); self.fps_text.set(f"FPS: {fps:.0f}")
                    self._handle_gesture(gesture, confidence)
        except queue.Empty: pass
        self.after(40, self._poll)

    def close(self):
        self.emergency_stop(); self.stop_event.set()
        if self.listener: self.listener.stop()
        if self.worker: self.worker.join(timeout=2)
        self.destroy()


if __name__ == "__main__":
    try: GestureApp().mainloop()
    except Exception as error:
        log.exception("Application could not start")
        try: messagebox.showerror("Startup failed", f"{error}\n\nInstall dependencies with: python -m pip install -r requirements.txt")
        except Exception: print(f"{APP_NAME} startup failed: {error}")
