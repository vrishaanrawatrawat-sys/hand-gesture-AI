import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from hand_gesture_ai import GestureApp, SwipeDetector, load_config


class CoreTests(unittest.TestCase):
    def test_invalid_bindings_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'bindings': []}))
            config, warning = load_config(path)
            self.assertIsNotNone(warning)
            self.assertIn('Fist', config['bindings'])

    def test_invalid_dimensions_keep_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'width': 0, 'stable_frames': 0}))
            config, _ = load_config(path)
            self.assertEqual(config['width'], 640)
            self.assertEqual(config['stable_frames'], 6)

    def test_swipe_with_zero_timestamp(self):
        swipe = SwipeDetector()
        self.assertIsNone(swipe.update((0, 0), 0))
        self.assertIsNone(swipe.update((.1, 0), .1))
        self.assertEqual(swipe.update((.2, 0), .2), 'Swipe Right')
        self.assertIsNone(swipe.update((.21, 0), .3))

    def test_held_gesture_fires_once_and_rearms(self):
        calls = []
        config, _ = load_config(Path('/nonexistent/config.json'))
        config['cooldown'] = 0
        app = SimpleNamespace(config_data=config, stable_name=None, stable_count=0,
                              fired_gesture=None, control_enabled=True, emergency=False,
                              last_action={}, input=SimpleNamespace(execute=calls.append),
                              _format_action=GestureApp._format_action)
        for _ in range(20):
            GestureApp._handle_gesture(app, 'Open Palm', .9)
        self.assertEqual(len(calls), 1)
        GestureApp._handle_gesture(app, 'No hand', 0)
        for _ in range(6):
            GestureApp._handle_gesture(app, 'Open Palm', .9)
        self.assertEqual(len(calls), 2)
        app.control_enabled = False
        GestureApp._handle_gesture(app, 'Swipe Left', .8)
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
