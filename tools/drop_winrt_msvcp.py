"""Remove the msvcp140.dll that the winrt-runtime wheel ships inside its package folder (Windows CI, before tests and
PyInstaller).

Why: Windows keeps the first msvcp140.dll a process loads. winrt's copy is older than what onnxruntime (wake word,
voice activity, speech-to-text) needs, so importing winrt (Windows notifications) before onnxruntime made onnxruntime
crash with an access violation - first seen as PyInstaller dying while analysing onnxruntime (CI run 93). Without
that copy, winrt's module uses the system's (newer, backward-compatible) runtime, and the release bundle carries only
that one. monkey.spec also filters it out, and the exe selftest checks it's gone.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys


def main() -> int:
    spec = importlib.util.find_spec("winrt")
    if spec is None:
        print("winrt not installed: nothing to do")
        return 0
    removed = []
    for d in spec.submodule_search_locations or []:
        for p in pathlib.Path(d).glob("msvcp140*.dll"):
            p.unlink()
            removed.append(str(p))
    print("removed:", removed or "nothing (already gone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
