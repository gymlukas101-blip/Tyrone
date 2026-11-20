"""Every event still reads with the sound muted (tools/playtest/sound_off.py), in the real built UI."""
from __future__ import annotations

import pytest

from tests.test_m4_avatar import DIST


def test_every_moment_reads_without_sound():
    pytest.importorskip("playwright")
    from tools.automation_eval import browser_path

    if browser_path() is None or not DIST.is_file():
        pytest.skip("needs Chromium and a built UI (npm run build)")
    from tools.playtest.sound_off import report, run

    rows = run()
    assert all(r["reads"] for r in rows), report(rows)
