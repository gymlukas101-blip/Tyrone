"""Open a web link in the user's real browser, reliably, without going through webbrowser's global lookup.

Windows: os.startfile (the shell's default browser; the most reliable path inside a frozen pywebview app).
macOS: `open`; Linux: `xdg-open`. Last resort: the stdlib default controller. http(s) links only.
"""
from __future__ import annotations

import os
import subprocess
import sys


def launch_url(url: str) -> bool:
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            return subprocess.run(["open", url], check=False).returncode == 0
        if subprocess.run(["xdg-open", url], check=False, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            return True
    except (OSError, ValueError):
        pass
    try:
        import webbrowser

        return bool(webbrowser.get().open(url, new=2))
    except Exception:  # noqa: BLE001
        return False
