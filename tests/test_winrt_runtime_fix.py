"""winrt-runtime's bundled msvcp140.dll crashed onnxruntime when it loaded first (CI run 93): the build drops it,
the spec filters it, and the toast backend loads onnxruntime before winrt."""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_drops_winrt_runtime_before_tests_and_pyinstaller():
    wf = (ROOT / ".github" / "workflows" / "build.yml").read_text()
    assert wf.count("python tools/drop_winrt_msvcp.py") == 2          # windows-test and the release build
    assert wf.index("python tools/drop_winrt_msvcp.py") < wf.index("pyinstaller monkey.spec")
    spec = (ROOT / "monkey.spec").read_text()
    assert "msvcp140" in spec and "a.binaries = [b for b in a.binaries" in spec


def test_drop_script_removes_only_the_runtime(tmp_path):
    pkg = tmp_path / "winrt"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "msvcp140.dll").write_bytes(b"x")
    (pkg / "_winrt.pyd").write_bytes(b"y")
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "drop_winrt_msvcp.py")], cwd=tmp_path,
                         env={"PYTHONPATH": str(tmp_path), "SYSTEMROOT": "", "PATH": ""}, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert not (pkg / "msvcp140.dll").exists() and (pkg / "_winrt.pyd").exists()


def test_toast_backend_loads_onnxruntime_before_winrt(monkeypatch):
    wt = importlib.import_module("monkey.notify.wintoast")
    order = []
    monkeypatch.setitem(sys.modules, "onnxruntime", None)                 # import -> ImportError, still tolerated
    monkeypatch.setattr(wt, "_runtime_order", lambda: order.append("onnxruntime"))

    class FakeToasts:
        class InteractableWindowsToaster:
            def __init__(self, *a, **k):
                order.append("winrt")
    monkeypatch.setitem(sys.modules, "windows_toasts", FakeToasts)
    monkeypatch.setattr(wt, "register_aumid", lambda *a, **k: None)
    b = wt.WinToastBackend()
    assert b.available and order == ["onnxruntime", "winrt"]
