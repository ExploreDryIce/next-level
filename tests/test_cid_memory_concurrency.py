"""Cid memory store under concurrent writers (2026-09-14 fix).

Before the fix, 6 processes x 40 remember() calls kept only 30-39 of 240
records and some workers crashed on a shared temp file.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

WORKER = """
import sys
sys.path.insert(0, {src!r})
from cid.memory import MemoryStore
store = MemoryStore()
for i in range({n}):
    store.remember(f"worker {{sys.argv[1]}} memory {{i}}", category="fact", project="stress")
"""


def _run_workers(home: Path, workers: int, per_worker: int):
    env = dict(os.environ, HOME=str(home))
    code = WORKER.format(src=str(SRC), n=per_worker)
    procs = [subprocess.Popen([sys.executable, "-c", code, str(w)], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for w in range(workers)]
    errors = [p.communicate()[1].decode() for p in procs if p.wait() != 0]
    return errors


def test_concurrent_writers_lose_nothing(tmp_path):
    errors = _run_workers(tmp_path, workers=6, per_worker=40)
    assert not errors, errors[0]
    records = json.loads((tmp_path / ".cid" / "memories.json").read_text())
    assert len(records) == 240
    assert len({r["id"] for r in records}) == 240
    assert not list((tmp_path / ".cid").glob(".memories.*.tmp"))


def test_corrupt_store_is_not_overwritten(tmp_path):
    cid = tmp_path / ".cid"
    cid.mkdir()
    (cid / "memories.json").write_text("{ this is not json")
    env = dict(os.environ, HOME=str(tmp_path))
    code = (f"import sys; sys.path.insert(0, {str(SRC)!r})\n"
            "from cid.memory import MemoryStore, CorruptMemoryStoreError\n"
            "s = MemoryStore()\n"
            "try:\n    s.remember('x')\nexcept CorruptMemoryStoreError:\n    print('refused')\n")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert "refused" in out.stdout, out.stderr
    assert (cid / "memories.json").read_text() == "{ this is not json"
