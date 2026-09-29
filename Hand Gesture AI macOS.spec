# macOS app bundle for Hand Gesture AI. Build this spec on macOS with the
# dependencies in requirements-macos.txt installed in the active environment.
from PyInstaller.utils.hooks import collect_all, collect_submodules

mp_datas, mp_binaries, mp_hiddenimports = collect_all("mediapipe")
pynput_hiddenimports = collect_submodules("pynput")

a = Analysis(
    ["hand_gesture_ai.py"],
    pathex=[],
    binaries=mp_binaries,
    datas=mp_datas,
    hiddenimports=mp_hiddenimports + pynput_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Hand Gesture AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Hand Gesture AI",
)
app = BUNDLE(
    coll,
    name="Hand Gesture AI.app",
    icon=None,
    bundle_identifier="com.handgestureai.macos",
    version="1.0.0",
    info_plist={
        "NSPrincipalClass": "NSApplication",
        "NSCameraUsageDescription": "Hand Gesture AI uses the camera to recognize hand gestures on your device.",
    },
)
