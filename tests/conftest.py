import pytest

from monkey import keys


@pytest.fixture(autouse=True)
def _isolated_keys(tmp_path, monkeypatch):
    """Never touch the developer's real saved keys or Windows Credential Manager in tests."""
    keys.use_store(tmp_path / "secrets.dat")
    monkeypatch.setattr(keys, "_keyring", lambda: None)
    yield
    keys.use_store(None)
