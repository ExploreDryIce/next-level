"""Cid refuses secrets and client watch data at write time; the scrub script
finds (and redacts) entries stored before the filter existed."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cid import memory as cid_memory  # noqa: E402
from cid.redaction import MemoryRejected, check_memory_text, find_secrets, load_watch_terms  # noqa: E402

# Built at runtime so the source never holds a full secret-shaped literal.
FAKE_PG = "postgresql://dvce_api:" + "Zq8" + "vY2kLmN4pQ" + "@100.99.1.1:5432/dvce"
FAKE_TG = "8712345678:" + "AA" + "Fq3kZ9xYvW2mN8pL4tR6sB1cD7eH0jKuQ5"
FAKE_GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


@pytest.fixture
def watch_dir(tmp_path, monkeypatch):
    d = tmp_path / "watches"
    d.mkdir()
    (d / "abcdef123456.json").write_text(json.dumps({
        "watch_id": "abcdef123456", "label": "Acme Optics pilot", "destination": "Plant 7",
        "rows": [{"component": "Lens", "supplier": "Kestrel Glassworks", "part_number": "KG-4471-A"}],
    }))
    monkeypatch.setenv("DVCE_WATCH_DIR", str(d))
    return d


@pytest.fixture
def store(tmp_path, monkeypatch, watch_dir):
    home = tmp_path / "cid"
    home.mkdir()
    monkeypatch.setattr(cid_memory, "CID_HOME", home)
    return cid_memory.MemoryStore()


@pytest.mark.parametrize("secret", [FAKE_PG, FAKE_TG, FAKE_GH, "GROQ_API_KEY=gsk_" + "x" * 30,
                                    "api_token: " + "Ab12Cd34" + "Ef56Gh78Ij90"])
def test_secret_shaped_content_is_refused(store, secret):
    with pytest.raises(MemoryRejected) as e:
        store.remember(f"Fixed the DB link, it is {secret}", category="fact", project="dvce")
    assert secret[-12:] not in str(e.value)  # the message never echoes the value
    assert not any(secret in m.content for m in store._memories)


def test_watch_terms_are_refused_case_insensitively(store):
    for text in ("kestrel glassworks shipped late", "Watch 'Acme Optics pilot' recorded",
                 "part KG-4471-A on hold"):
        with pytest.raises(MemoryRejected, match="abcdef123456"):
            store.remember(text, category="session", project="dvce")
    assert store._memories == []


def test_tags_and_metadata_are_checked(store):
    with pytest.raises(MemoryRejected):
        store.remember("ok", tags=["Kestrel Glassworks"])
    with pytest.raises(MemoryRejected):
        store.remember("ok", metadata={"db": FAKE_PG})


def test_session_end_is_all_or_nothing(store):
    with pytest.raises(MemoryRejected):
        store.end_session("dvce", "Shipped share links", decisions=[f"use {FAKE_GH}"])
    assert store._memories == []


def test_ordinary_memories_still_store(store):
    for text in ("Rotated the password; it lives in ~/.dvce/secrets.env as SNAPSHOT_DB_URL",
                 "watch abcdef123456 got a share link", "Lens supply ok; postgres on 5432",
                 "password=see_secrets_env_file"):
        store.remember(text, category="fact", project="dvce")
    assert len(store._memories) == 4


def test_short_and_partial_terms_do_not_match(watch_dir):
    terms = load_watch_terms(watch_dir)
    check_memory_text("Kestrels nest in glass towers", terms=terms)  # no whole-word match
    assert "lens" not in terms  # component names are not client-identifying


def test_find_secrets_reports_prefix_only():
    hits = find_secrets(f"a {FAKE_TG} b")
    assert [h.rule for h in hits] == ["telegram-bot-token"] and hits[0].prefix == "8712"


def test_scrub_script_reports_then_redacts(tmp_path, watch_dir):
    cid_home = tmp_path / "cidhome"
    cid_home.mkdir()
    records = [
        {"id": "aaaa1111", "category": "fact", "project": "dvce", "content": f"db {FAKE_PG}", "tags": []},
        {"id": "bbbb2222", "category": "session", "project": "dvce",
         "content": "Kestrel Glassworks delay logged", "tags": [], "metadata": {}},
        {"id": "cccc3333", "category": "fact", "project": "dvce", "content": "clean", "tags": []},
    ]
    store_file = cid_home / "memories.json"
    store_file.write_text(json.dumps(records))
    (cid_home / "memories.json.bak-old").write_text(json.dumps(records[:1]))
    script = [sys.executable, str(ROOT / "scripts" / "cid_scrub.py"), "--store", str(store_file)]
    env = {"DVCE_WATCH_DIR": str(watch_dir), "PATH": "/usr/bin:/bin"}

    dry = subprocess.run(script, capture_output=True, text=True, env=env)
    assert dry.returncode == 1
    assert "id=aaaa1111" in dry.stdout and "id=bbbb2222" in dry.stdout and "cccc3333" not in dry.stdout
    assert "memories.json.bak-old" in dry.stdout
    assert "Zq8vY2kLmN4pQ" not in dry.stdout and "Glassworks" not in dry.stdout
    assert json.loads(store_file.read_text()) == records  # dry run changes nothing

    applied = subprocess.run(script + ["--apply"], capture_output=True, text=True, env=env)
    assert applied.returncode == 1
    after = json.loads(store_file.read_text())
    assert "[REDACTED:url-with-password]" in after[0]["content"]
    assert "Kestrel" not in after[1]["content"] and after[2]["content"] == "clean"
    assert (store_file.stat().st_mode & 0o777) == 0o600
    again = subprocess.run(script, capture_output=True, text=True, env=env)
    assert again.returncode == 0, again.stdout
