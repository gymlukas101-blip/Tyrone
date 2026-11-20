import subprocess
import sys

import pytest

from monkey import keys
from monkey.secretstore import SecretStore


def test_round_trip_large_value(tmp_path):
    st = SecretStore(tmp_path / "s.dat")
    big = '{"refresh_token": "' + "r" * 5000 + '"}'  # bigger than Credential Manager's ~2.5 KB limit
    st.set("google_token", big)
    assert st.get("google_token") == big
    assert st.names() == ["google_token"]
    st.delete("google_token")
    assert st.get("google_token") is None


def test_survives_a_new_process(tmp_path):
    path = tmp_path / "s.dat"
    SecretStore(path).set("fish", "sk-fish-abc123")
    code = f"from monkey.secretstore import SecretStore; print(SecretStore({str(path)!r}).get('fish'))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "sk-fish-abc123"


def test_corrupt_or_foreign_file_reads_as_empty(tmp_path):
    path = tmp_path / "s.dat"
    path.write_text("not json", encoding="utf-8")
    assert SecretStore(path).get("fish") is None
    path.write_text('{"fish": "dpapi:AAAA"}' if sys.platform != "win32" else '{"fish": "plain:AAAA"}', encoding="utf-8")
    assert SecretStore(path).get("fish") is None
    SecretStore(path).set("fish", "new")  # and it can still be overwritten
    assert SecretStore(path).get("fish") == "new"


def test_no_temp_files_left(tmp_path):
    st = SecretStore(tmp_path / "s.dat")
    for i in range(5):
        st.set(f"k{i}", "v")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s.dat", "s.dat.bak"]   # no temp files; one backup


def test_keys_set_get_hint_status(monkeypatch):
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    keys.set("fish", "sk-fish-0123456789abcd4s0I")
    assert keys.get("fish") == "sk-fish-0123456789abcd4s0I"
    assert keys.status()["fish"] is True
    assert keys.hints()["fish"] == "4s0I"
    keys.delete("fish")
    assert keys.get("fish") is None


def test_env_overrides_saved(monkeypatch):
    keys.set("fish", "saved-key-value-xyz")
    monkeypatch.setenv("FISH_API_KEY", "env-key")
    assert keys.get("fish") == "env-key"
    assert keys.saved("fish") == "saved-key-value-xyz"


class FakeKeyring:
    def __init__(self, data):
        self.data = data
        self.deleted = []

    def get_password(self, service, name):
        return self.data.get((service, name))

    def delete_password(self, service, name):
        self.deleted.append((service, name))
        self.data.pop((service, name), None)


def test_migrates_from_old_credential_manager(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kr = FakeKeyring({("Tyrone", "anthropic"): "sk-ant-old-key-0000"})
    monkeypatch.setattr(keys, "_keyring", lambda: kr)
    assert keys.get("anthropic") == "sk-ant-old-key-0000"
    kr.data.clear()  # now only in the new store
    assert keys.store().get("anthropic") == "sk-ant-old-key-0000"
    assert keys.get("anthropic") == "sk-ant-old-key-0000"


def test_delete_does_not_resurrect_from_old_keychain(monkeypatch):
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    kr = FakeKeyring({("Monkey", "fish"): "sk-fish-old-0000"})
    monkeypatch.setattr(keys, "_keyring", lambda: kr)
    keys.delete("fish")
    assert ("Monkey", "fish") in kr.deleted
    assert keys.get("fish") is None


def test_set_failure_is_reported(monkeypatch):
    def boom(*a, **k):
        raise PermissionError("disk is read-only")

    monkeypatch.setattr(keys.store(), "set", boom)
    with pytest.raises(keys.KeySaveError, match="read-only"):
        keys.set("fish", "x")
