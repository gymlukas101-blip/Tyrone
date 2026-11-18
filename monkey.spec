# PyInstaller build spec:  pyinstaller monkey.spec --noconfirm
# Produces dist/Monkey/Monkey.exe (one-folder build: faster startup than one-file).
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [
    ("ui/dist", "ui/dist"),
    ("wakeword", "wakeword"),
    ("assets", "assets"),
    ("monkey/brain/persona.md", "monkey/brain"),
]
for pkg in ("openwakeword", "faster_whisper", "webview", "anthropic", "certifi", "_sounddevice_data"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

binaries = []
for pkg in ("ctranslate2", "onnxruntime", "_sounddevice_data", "sherpa_onnx", "sentencepiece"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

hiddenimports = (
    collect_submodules("webview")
    + collect_submodules("keyring.backends")
    + collect_submodules("googleapiclient")
    + collect_submodules("garminconnect")
    + [
        "pyttsx3.drivers", "pyttsx3.drivers.sapi5", "comtypes.client",
        "win32com", "win32com.client", "pythoncom", "pywintypes",
        "pystray._win32", "google_auth_oauthlib.flow",
    ]
)

a = Analysis(
    ["run_monkey.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Monkey",
    icon="assets/monkey.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Monkey")
