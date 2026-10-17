#!/usr/bin/env python3
"""Find (and with --apply, redact) secrets and client watch data in a Cid store.

Run by the owner AFTER rotating the credentials it finds; redacting a live
secret does not un-leak it. By default it only reports. Output names the file,
the memory id, the field, the rule (or watch id) and at most the first 4
characters of the match, never the value.

    python scripts/cid_scrub.py                       # ~/.cid/memories.json and its .bak-* copies
    python scripts/cid_scrub.py --store /path/memories.json --extra /backup/cid-memories.json
    python scripts/cid_scrub.py --apply               # rewrite each file, matches -> [REDACTED:<rule>]

Watch terms (supplier names, labels, part numbers) are read from
DVCE_WATCH_DIR or ~/.dvce/watches; --no-watch-terms skips them.
Exit status: 0 nothing found, 1 findings reported (or redacted), 2 error.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cid.redaction import find_secrets, find_watch_terms, load_watch_terms  # noqa: E402

FIELDS = ("content", "tags", "metadata")


def _default_files(store: Path) -> List[Path]:
    files = [store] if store.exists() else []
    files += sorted(store.parent.glob(store.name + ".bak*"))
    return files


def _scan_string(text: str, terms: Dict[str, str]) -> List[Tuple[str, str, str]]:
    """[(rule_or_watch, prefix, matched_value)]"""
    out = [(h.rule, h.prefix, h.value) for h in find_secrets(text)]
    for term, wid in find_watch_terms(text, terms):
        out.append((f"watch:{wid}", term[:4], term))
    return out


def _redact(text: str, terms: Dict[str, str]) -> str:
    for h in sorted(find_secrets(text), key=lambda h: h.start, reverse=True):
        text = text[:h.start] + f"[REDACTED:{h.rule}]" + text[h.end:]
    for term, wid in find_watch_terms(text, terms):
        text = re.sub(r"(?<![0-9A-Za-z])" + re.escape(term) + r"(?![0-9A-Za-z])",
                      f"[REDACTED:watch:{wid}]", text, flags=re.I)
    return text


def _walk(value, terms, path, findings, apply):
    if isinstance(value, str):
        for rule, prefix, _ in _scan_string(value, terms):
            findings.append((path, rule, prefix))
        return _redact(value, terms) if apply else value
    if isinstance(value, list):
        return [_walk(v, terms, path, findings, apply) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v, terms, path, findings, apply) for k, v in value.items()}
    return value


def scrub_file(path: Path, terms: Dict[str, str], apply: bool) -> List[Tuple[str, str, str, str]]:
    if not apply:
        return _scrub(path, terms, False)
    # Same lock MemoryStore._save takes, so a running Cid server cannot
    # interleave a write with the rewrite.
    with open(path.parent / "memories.json.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return _scrub(path, terms, True)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _scrub(path: Path, terms: Dict[str, str], apply: bool) -> List[Tuple[str, str, str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
    found: List[Tuple[str, str, str, str]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        mid = str(rec.get("id", "?"))
        for field in FIELDS:
            if field not in rec:
                continue
            hits: List[Tuple[str, str, str]] = []
            new = _walk(rec[field], terms, field, hits, apply)
            if apply:
                rec[field] = new
            found += [(mid, f, rule, prefix) for f, rule, prefix in hits]
    if apply and found:
        fd, tmp = tempfile.mkstemp(prefix=".scrub-", dir=path.parent)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", type=Path, default=Path.home() / ".cid" / "memories.json")
    ap.add_argument("--extra", type=Path, action="append", default=[],
                    help="another copy to scan (e.g. a backup); repeatable")
    ap.add_argument("--apply", action="store_true", help="rewrite the files with matches redacted")
    ap.add_argument("--no-watch-terms", action="store_true")
    args = ap.parse_args(argv)

    terms = {} if args.no_watch_terms else load_watch_terms()
    files = _default_files(args.store) + list(args.extra)
    if not files:
        print(f"no store at {args.store}", file=sys.stderr)
        return 2
    total = 0
    for path in files:
        try:
            found = scrub_file(path, terms, args.apply)
        except (OSError, ValueError) as e:
            print(f"{path}: cannot read ({type(e).__name__})", file=sys.stderr)
            return 2
        for mid, field, rule, prefix in found:
            print(f"{path}\tid={mid}\t{field}\t{rule}\t{prefix}…")
        total += len(found)
        print(f"{path}: {len(found)} finding(s){' redacted' if args.apply and found else ''}", file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
