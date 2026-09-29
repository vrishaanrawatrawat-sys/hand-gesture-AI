# Hand Gesture AI for macOS

This is a separate macOS build of the original Hand Gesture AI project. The original source folder was not modified. Gesture recognition, the settings interface, shortcut recording, mouse actions, and camera preview remain in the app.

## Build on a Mac

Build on the Mac and CPU architecture where the app will be tested. PyInstaller does not cross-build a macOS application from Windows. The generated app is built for the Mac's active architecture (Apple silicon or Intel).

1. Install Python 3.12 for macOS, including Tcl/Tk support. The python.org macOS installer is recommended.
2. Open Terminal and change to this project folder.
3. Run `bash build-macos.sh`.
4. The app is created at `dist/Hand Gesture AI.app`; a compressed installer disk image is created at `dist/Hand-Gesture-AI-macOS.dmg`.

The first build installs the pinned packages in a project-local `.venv`. MediaPipe 0.10.21 supplies the `mp.solutions.hands` API used by this app and publishes universal2 macOS wheels for Python 3.12. The current MediaPipe 1.x API has different interfaces, so the Mac build deliberately uses the compatible 0.10 release.

## Run and grant permissions

Open the `.app` from Finder or drag it from the mounted disk image to Applications first. On first camera use, macOS asks for Camera permission. Allow **Hand Gesture AI** under **System Settings → Privacy & Security → Camera**.

Keyboard shortcuts and mouse actions are optional. To use them, enable **Hand Gesture AI** under **System Settings → Privacy & Security → Accessibility**. Shortcut recording listens for global keyboard input, so shortcut recording may also require **Privacy & Security → Input Monitoring**. Quit and reopen the app after changing either permission. Without input permissions the camera preview and gesture recognition still run, while sending shortcuts and mouse actions is unavailable.

If macOS blocks an app copied from another Mac because it is not notarized, use **Control-click → Open** once and confirm the prompt. For broad distribution outside a local test, sign the app with an Apple Developer ID and notarize it; those credentials are not included in this project.

## Notes

- The app accesses the camera only while its camera feature is running. Its purpose string is included in the app bundle's `Info.plist`.
- Settings are stored in `~/.hand-gesture-ai/config.json` and are kept separate from the app bundle.
- Build each CPU architecture on its matching Mac. This avoids relying on a universal build of every native dependency.
