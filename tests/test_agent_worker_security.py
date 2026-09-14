"""TerrorNode agent worker hardening (2026-09-14)."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "agent"))


def _load(monkeypatch, token="t0k", allow_shell=None):
    monkeypatch.setenv("DVCE_AGENT_TOKEN", token)
    if allow_shell is None:
        monkeypatch.delenv("DVCE_AGENT_ALLOW_SHELL", raising=False)
    else:
        monkeypatch.setenv("DVCE_AGENT_ALLOW_SHELL", allow_shell)
    import worker
    return importlib.reload(worker)


@pytest.mark.parametrize("bad", ["scripts/x.py; rm -rf /", "scripts/../../etc/passwd.py", "/abs/x.py",
                                 "scripts/x.py && curl evil", "scripts/$(id).py", "other/x.py"])
def test_script_injection_refused(monkeypatch, bad):
    w = _load(monkeypatch)
    with pytest.raises(ValueError):
        w._safe_script(bad)


def test_plain_script_allowed(monkeypatch):
    w = _load(monkeypatch)
    assert w._safe_script("scripts/overnight_train.py") == "scripts/overnight_train.py"


def test_bearer_auth(monkeypatch):
    w = _load(monkeypatch, token="secret-1")
    assert w._authorized("Bearer secret-1")
    assert not w._authorized("Bearer nope")
    assert not w._authorized("secret-1")
    assert not w._authorized("")


def test_no_token_means_nothing_authorized(monkeypatch):
    w = _load(monkeypatch, token="")
    assert not w._authorized("Bearer ")


def test_shell_disabled_by_default(monkeypatch):
    w = _load(monkeypatch)
    assert "disabled" in w.AgentWorker._do_shell(object.__new__(w.AgentWorker), {"command": "echo hi"})
