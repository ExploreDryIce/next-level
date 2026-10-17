"""Write-time hygiene for Cid memories (DVCE security review 2026-10-16, H2/M5).

Cid content is handed to every agent session (and so to the LLM provider) and
is copied to backups. Two kinds of text must never be stored in it:

1. Secret-shaped strings: connection strings with a password, provider API
   keys and tokens, private keys, JWTs, `password=...` assignments. The
   patterns follow gitleaks' default rules for the providers this project
   uses (gitleaks' own config is TOML for a Go binary, so the regexes are
   restated here, not imported).
2. Anything from a client's watch: supplier names, the watch label, the
   destination, and part numbers from the rows. These are read at write time
   from the DVCE watch directory (`DVCE_WATCH_DIR`, default `~/.dvce/watches`),
   so a new client is covered as soon as their watch exists.

`check_memory_text()` raises `MemoryRejected` with a message that names the
rule or the watch, never the matched value. `find_secrets()` is shared with
`scripts/cid_scrub.py`, which reports (and with --apply redacts) entries that
were stored before this filter existed.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

ENV_WATCH_DIR = "DVCE_WATCH_DIR"
DEFAULT_WATCH_DIR = Path("~/.dvce/watches")

# Shortest watch term that is matched. Shorter strings ("AG", "Inc") would
# refuse ordinary prose.
MIN_TERM_LEN = 4

# (rule id, pattern). Ordered roughly most to least specific.
SECRET_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # scheme://user:password@host — postgres, mysql, redis, amqp, mongodb, http(s) ...
    ("url-with-password", re.compile(
        r"\b[a-z][a-z0-9+.\-]{1,20}://[^\s:/@'\"]{1,64}:[^\s@/'\"]{3,128}@[^\s/'\"]+", re.I)),
    ("neon-password", re.compile(r"\bnpg_[A-Za-z0-9]{8,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{60,}")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20}\b")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("slack-webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_\-]{20,}")),
    ("discord-webhook", re.compile(r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]{20,}")),
    ("telegram-bot-token", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{30,40}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}T3BlbkFJ[A-Za-z0-9_\-]{20,}|\bsk-[A-Za-z0-9]{48}\b")),
    ("groq-key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe-key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{34,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    # KEY=value / "password": "value" with a long, token-like value.
    ("generic-assignment", re.compile(
        r"(?i)\b[A-Z0-9_]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd)[A-Z0-9_]*\b"
        r"[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9/+_\-.]{16,})")),
]


class MemoryRejected(ValueError):
    """Raised when a memory would store a secret or client watch data."""


@dataclass(frozen=True)
class Hit:
    rule: str
    start: int
    end: int
    value: str

    @property
    def prefix(self) -> str:
        return self.value[:4]


def find_secrets(text: str) -> List[Hit]:
    hits: List[Hit] = []
    for rule, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text or ""):
            if rule == "generic-assignment":
                start, end = m.span(1)
                value = m.group(1)
                if not _looks_random(value):
                    continue
            else:
                start, end = m.span()
                value = m.group(0)
            if any(h.start <= start < h.end for h in hits):
                continue
            hits.append(Hit(rule, start, end, value))
    return sorted(hits, key=lambda h: h.start)


def _looks_random(value: str) -> bool:
    """A generic `token=...` value counts only if it mixes letters and digits,
    so `password=see_secrets_env_file` style prose is not refused."""
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value)


# ─── Client watch terms ───────────────────────────────────────────────────

_TERM_FIELDS_ROW = ("supplier", "part_number", "mpn", "sku")
_TERM_FIELDS_WATCH = ("label", "destination")


def watch_dir() -> Path:
    return Path(os.environ.get(ENV_WATCH_DIR) or DEFAULT_WATCH_DIR).expanduser()


def load_watch_terms(directory: Optional[Path] = None) -> Dict[str, str]:
    """{lower-cased term: watch_id} for every client-identifying string."""
    directory = watch_dir() if directory is None else Path(directory)
    terms: Dict[str, str] = {}
    if not directory.is_dir():
        return terms
    for path in sorted(directory.glob("*.json")):
        try:
            watch = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(watch, dict):
            continue
        wid = str(watch.get("watch_id") or path.stem)
        values = [watch.get(f) for f in _TERM_FIELDS_WATCH]
        for row in watch.get("rows") or []:
            if isinstance(row, dict):
                values.extend(row.get(f) for f in _TERM_FIELDS_ROW)
        for v in values:
            if isinstance(v, str) and len(v.strip()) >= MIN_TERM_LEN:
                terms.setdefault(v.strip().lower(), wid)
    return terms


def find_watch_terms(text: str, terms: Dict[str, str]) -> List[Tuple[str, str]]:
    """[(term, watch_id)] for every watch term that appears as a whole word."""
    low = (text or "").lower()
    out = []
    for term, wid in terms.items():
        idx = low.find(term)
        while idx != -1:
            before = low[idx - 1] if idx > 0 else " "
            after = low[idx + len(term)] if idx + len(term) < len(low) else " "
            if not before.isalnum() and not after.isalnum():
                out.append((term, wid))
                break
            idx = low.find(term, idx + 1)
    return out


# ─── Write-time check ─────────────────────────────────────────────────────


def _strings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _strings(v)


def check_memory_text(*parts, terms: Optional[Dict[str, str]] = None) -> None:
    """Raise MemoryRejected if any part (content, tags, metadata) holds a
    secret-shaped string or a term from a client's watch."""
    texts: Iterable[str] = [s for p in parts for s in _strings(p)]
    texts = list(texts)
    rules = sorted({h.rule for t in texts for h in find_secrets(t)})
    if rules:
        raise MemoryRejected(
            "Cid refused this memory: it contains a secret-shaped string "
            f"(rule: {', '.join(rules)}). Never store credentials in Cid; refer to "
            "where the secret lives (e.g. 'SNAPSHOT_DB_URL in ~/.dvce/secrets.env') instead."
        )
    terms = load_watch_terms() if terms is None else terms
    if terms:
        watches = sorted({wid for t in texts for _, wid in find_watch_terms(t, terms)})
        if watches:
            raise MemoryRejected(
                "Cid refused this memory: it contains a supplier name, label or part "
                f"number from client watch(es) {', '.join(watches)}. Client watch data stays in "
                "~/.dvce/watches; refer to the watch by its id instead."
            )
