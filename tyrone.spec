# PyInstaller build spec:  pyinstaller tyrone.spec --noconfirm
# Produces dist/Tyrone/Tyrone.exe (one-folder build: faster startup than one-file).
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [
    ("ui/dist", "ui/dist"),
    ("wakeword", "wakeword"),
    ("assets", "assets"),
    ("tyrone/brain/persona.md", "tyrone/brain"),
]
for pkg in ("openwakeword", "faster_whisper", "webview", "anthropic", "certifi", "_sounddevice_data"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

binaries = []
for pkg in ("ctranslate2", "onnxruntime", "_sounddevice_data"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

hiddenimports = (
    collect_submodules("webview")
    + collect_submodules("keyring.backends")
    + collect_submodules("googleapiclient")
    + [
        "pyttsx3.drivers", "pyttsx3.drivers.sapi5", "comtypes.client",
        "win32com", "win32com.client", "pythoncom", "pywintypes",
        "pystray._win32", "google_auth_oauthlib.flow",
    ]
)

a = Analysis(
    ["run_tyrone.py"],
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
    name="Tyrone",
    icon="assets/tyrone.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Tyrone")
