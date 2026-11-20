"""Where the time goes in Monkey's voice turns (from local traces; timings only, no speech).

    python -m tools.voice_report [TRACES_DIR]      # default: %APPDATA%\\Monkey\\traces
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from monkey.trace import load_traces, report


def main() -> None:
    default = Path(os.environ.get("APPDATA", str(Path.home()))) / "Monkey" / "traces"
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    print(report(load_traces(folder)))


if __name__ == "__main__":
    main()
