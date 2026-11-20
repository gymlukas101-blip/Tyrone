"""Where does a UIA observe() spend its time? Prints per-property timings over the fixture's controls and a cProfile
summary of one UIADriver.observe(). Windows only (CI diagnostic)."""
from __future__ import annotations

import cProfile
import pstats
import tempfile
import time
from pathlib import Path


def main() -> int:
    from monkey.automation.computer.drivers.uia import UIADriver, _toggle_state, _value
    from monkey.automation.desktop import make_dpi_aware
    from tools.computer_bench.run_windows import Fixture

    make_dpi_aware()
    with tempfile.TemporaryDirectory() as d:
        fx = Fixture(Path(d))
        fx.start()
        try:
            drv = UIADriver(fx.hwnd())
            win = drv._wrapper(fx.hwnd())
            t = time.time()
            desc = win.descendants()
            print(f"descendants(): {len(desc)} in {time.time() - t:.2f}s", flush=True)
            probes = {
                "control_type": lambda w: w.element_info.control_type,
                "name": lambda w: w.element_info.name,
                "automation_id": lambda w: w.element_info.automation_id,
                "rectangle": lambda w: w.element_info.rectangle,
                "enabled": lambda w: w.element_info.enabled,
                "is_password": lambda w: getattr(w.element_info.element, "CurrentIsPassword", False),
                "toggle": _toggle_state,
                "value": _value,
            }
            for k, fn in probes.items():
                t = time.time()
                worst = (0.0, "")
                for w in desc:
                    t1 = time.time()
                    try:
                        fn(w)
                    except Exception:  # noqa: BLE001
                        pass
                    dt = time.time() - t1
                    if dt > worst[0]:
                        try:
                            worst = (dt, f"{w.element_info.control_type} {w.element_info.name!r}")
                        except Exception:  # noqa: BLE001
                            worst = (dt, "?")
                print(f"{k:14s} total {time.time() - t:7.2f}s  worst {worst[0]:6.2f}s {worst[1]}", flush=True)
            pr = cProfile.Profile()
            t = time.time()
            pr.enable()
            v = drv.observe()
            pr.disable()
            print(f"observe(): {len(v.elements)} elements in {time.time() - t:.2f}s", flush=True)
            pstats.Stats(pr).sort_stats("cumulative").print_stats(12)
            # The benchmark path, step by step, with a stack dump every 20 s if anything blocks.
            import faulthandler
            import sys

            from tools.computer_bench.run_windows import MonkeyBackend, bring_front

            faulthandler.dump_traceback_later(20, repeat=True, file=sys.stdout)
            steps = []
            b = MonkeyBackend(fx, physical=True)
            steps.append(("list_windows", lambda: b.list_windows()))
            steps.append(("bring_front", lambda: (bring_front(fx.hwnd()), time.sleep(0.3))))
            steps.append(("computer.observe", lambda: b.snapshot()))
            steps.append(("type Name", lambda: b.type("Name", "Ada")))
            steps.append(("click Greet", lambda: b.click("Greet")))
            for label, fn in steps:
                t = time.time()
                try:
                    fn()
                    res = "ok"
                except Exception as exc:  # noqa: BLE001
                    res = f"{type(exc).__name__}: {exc}"[:160]
                print(f"STEP {label:18s} {time.time() - t:7.2f}s {res}", flush=True)
            faulthandler.cancel_dump_traceback_later()
            print("LOG", fx.lines(), flush=True)
        finally:
            fx.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
