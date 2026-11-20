"""Updates must be able to replace the app folder: nothing Monkey started may outlive it."""
import subprocess
import sys
import time

import pytest

from monkey import lifecycle


def test_children_are_ended_on_exit():
    psutil = pytest.importorskip("psutil")
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert lifecycle.kill_children(grace=2) >= 1
        p.wait(5)
        assert not psutil.pid_exists(p.pid) or psutil.Process(p.pid).status() == psutil.STATUS_ZOMBIE
    finally:
        if p.poll() is None:
            p.kill()


def test_release_for_exit_shuts_automation_down_first():
    calls = []

    class A:
        class automation:
            @staticmethod
            def shutdown():
                calls.append("automation")
    lifecycle.release_for_exit(A(), timeout=2)
    assert calls == ["automation"]


def test_leftovers_only_inside_the_app_folder(tmp_path):
    psutil = pytest.importorskip("psutil")
    # a copy of python inside a fake app folder plays an orphaned node.exe
    import shutil

    fake = tmp_path / "current"
    fake.mkdir()
    if sys.platform == "win32":
        src, args = r"C:\Windows\System32\PING.EXE", ["-n", "60", "127.0.0.1"]
        exe = fake / "node.exe"
    else:
        src, args = shutil.which("sleep"), ["60"]
        exe = fake / "node"
    shutil.copy(src, exe)
    exe.chmod(0o755)
    p = subprocess.Popen([str(exe), *args], stdout=subprocess.DEVNULL)
    outside = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        time.sleep(0.5)
        ended = lifecycle.kill_leftovers(fake)
        assert ended, "the process running from the app folder must be ended"
        p.wait(5)
        assert outside.poll() is None                                    # nothing outside the folder is touched
    finally:
        for q in (p, outside):
            if q.poll() is None:
                q.kill()


def test_update_that_did_not_install_is_reported_once(tmp_path):
    lifecycle.record_update_attempt(tmp_path, "0.3.66", "0.3.67")
    msg = lifecycle.check_update_attempt(tmp_path, "0.3.66")
    assert "0.3.67" in msg and "Restart & update" in msg
    assert lifecycle.check_update_attempt(tmp_path, "0.3.66") == ""      # said once
    lifecycle.record_update_attempt(tmp_path, "0.3.66", "0.3.67")
    assert lifecycle.check_update_attempt(tmp_path, "0.3.67") == ""      # it worked: nothing to say


def test_updater_cleans_up_before_applying():
    from monkey.updater import Updater

    order = []

    class M:
        def get_current_version(self):
            return "0.3.66"

        def apply_updates_and_restart(self, info):
            order.append("apply")
    u = Updater(lambda *a: None, manager_factory=M)
    u._pending, u.available_version = object(), "0.3.67"
    u.on_attempt = lambda f, t: order.append(f"attempt {f}->{t}")
    u.before_apply = lambda: order.append("cleanup")
    u.apply()
    assert order == ["attempt 0.3.66->0.3.67", "cleanup", "apply"]


def test_restart_helper_survives_the_exit_cleanup(tmp_path):
    """Regression (v0.3.68): the relaunch helper was a child, so release_for_exit killed it and Monkey never
    came back after "Restart" (e.g. after importing from another PC)."""
    pytest.importorskip("psutil")
    marker = tmp_path / "relaunched"
    helper = lifecycle.spawn_detached([sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ok')"], delay_s=1)
    lifecycle.release_for_exit(None, keep={helper.pid})
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.read_text() == "ok"
