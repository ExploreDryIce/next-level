"""
Cid Memory Store — persistent knowledge that survives across sessions.

Stores:
- Session history (what happened, when, what changed)
- Decisions (why we chose X over Y)
- Conventions (how things are done in each project)
- Failures (what broke and how we fixed it)
- Patterns (recurring solutions and workflows)
- Facts (credentials, paths, architecture notes)

All stored as JSON on disk at ~/.cid/
Queryable by category, project, recency, and semantic similarity.
"""

import fcntl
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict


# ─── Storage Path ─────────────────────────────────────────────────────────

CID_HOME = Path.home() / ".cid"
CID_HOME.mkdir(parents=True, exist_ok=True)


# ─── Memory Types ─────────────────────────────────────────────────────────

CATEGORIES = [
    "session",      # What happened in a work session
    "decision",     # Why we chose X over Y
    "convention",   # How things are done (code style, architecture patterns)
    "failure",      # What broke and how it was fixed
    "pattern",      # Recurring solutions/workflows
    "fact",         # Credentials, paths, architecture notes
    "context",      # Project state snapshots for handoff
]


@dataclass
class Memory:
    """A single unit of remembered knowledge."""
    id: str
    category: str
    project: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    created_at: float = 0.0
    accessed_at: float = 0.0
    access_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Memory":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ─── Memory Store ─────────────────────────────────────────────────────────


class CorruptMemoryStoreError(RuntimeError):
    """memories.json exists but cannot be parsed; saving would destroy it."""


class MemoryStore:
    """Persistent memory store backed by JSON files.
    
    Structure:
        ~/.cid/
        ├── memories.json          (all memories, indexed)
        ├── sessions/              (per-session logs)
        │   └── 2026-06-07_dvce.json
        └── projects/              (per-project state)
            ├── dvce.json
            └── next-level.json
    """

    def __init__(self):
        self._memories_path = CID_HOME / "memories.json"
        self._sessions_dir = CID_HOME / "sessions"
        self._projects_dir = CID_HOME / "projects"
        self._sessions_dir.mkdir(exist_ok=True)
        self._projects_dir.mkdir(exist_ok=True)
        self._memories: List[Memory] = []
        # Ids this process has created or changed, and ids it has removed.
        # _save() applies only these on top of the current file, so concurrent
        # stores in other processes do not overwrite each other.
        self._dirty: set[str] = set()
        self._deleted: set[str] = set()
        self._load()

    # ─── Core Operations ──────────────────────────────────────────

    def remember(
        self,
        content: str,
        category: str = "fact",
        project: str = "general",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Memory:
        """Store a new memory."""
        memory = Memory(
            id=str(uuid.uuid4())[:8],
            category=category,
            project=project,
            content=content,
            tags=tags or [],
            metadata=metadata or {},
            created_at=time.time(),
            accessed_at=time.time(),
            access_count=0,
        )
        self._memories.append(memory)
        self._dirty.add(memory.id)
        self._save()
        return memory

    def recall(
        self,
        query: str,
        category: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 10,
    ) -> List[Memory]:
        """Recall memories matching a query.
        
        Uses simple keyword matching + recency weighting.
        Future: semantic search via embeddings.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored = []
        for mem in self._memories:
            # Filter by category/project
            if category and mem.category != category:
                continue
            if project and mem.project != project:
                continue

            # Score by keyword overlap
            content_lower = mem.content.lower()
            tag_text = " ".join(mem.tags).lower()
            combined = content_lower + " " + tag_text

            word_matches = sum(1 for w in query_words if w in combined)
            if word_matches == 0 and query_lower not in combined:
                continue

            # Score: matches + recency bonus + access frequency
            recency = 1.0 / (1 + (time.time() - mem.created_at) / 86400)  # Decay over days
            score = word_matches * 2 + recency + (mem.access_count * 0.1)

            scored.append((score, mem))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Update access timestamps
        results = []
        for _, mem in scored[:limit]:
            mem.accessed_at = time.time()
            mem.access_count += 1
            results.append(mem)

        # Deliberately no _save() here. Persisting access counters on every
        # read turned lookups into full-file rewrites, which is what let one
        # client clobber another's memories just by reading. The counters ride
        # along with the next genuine write instead.
        for mem in results:
            self._dirty.add(mem.id)

        return results

    def get_conventions(self, project: str) -> List[Memory]:
        """Get all conventions for a project."""
        return [m for m in self._memories if m.category == "convention" and m.project == project]

    def get_recent_sessions(self, project: str, limit: int = 5) -> List[Memory]:
        """Get recent session summaries."""
        sessions = [m for m in self._memories if m.category == "session" and m.project == project]
        sessions.sort(key=lambda m: m.created_at, reverse=True)
        return sessions[:limit]

    def get_failures(self, project: Optional[str] = None) -> List[Memory]:
        """Get all failure memories."""
        failures = [m for m in self._memories if m.category == "failure"]
        if project:
            failures = [f for f in failures if f.project == project]
        return failures

    def start_session(self, project: str) -> Dict[str, Any]:
        """Start a new session — returns relevant context to prime the agent."""
        recent = self.get_recent_sessions(project, limit=3)
        conventions = self.get_conventions(project)
        failures = self.get_failures(project)

        return {
            "project": project,
            "recent_sessions": [m.content for m in recent],
            "conventions": [m.content for m in conventions],
            "recent_failures": [m.content for m in failures[-3:]],
            "total_memories": len(self._memories),
            "project_memories": len([m for m in self._memories if m.project == project]),
        }

    def end_session(self, project: str, summary: str, decisions: Optional[List[str]] = None):
        """End a session — save what happened."""
        self.remember(
            content=summary,
            category="session",
            project=project,
            metadata={"timestamp": time.time()},
        )

        if decisions:
            for decision in decisions:
                self.remember(
                    content=decision,
                    category="decision",
                    project=project,
                )

    def forget(self, memory_id: str) -> bool:
        """Remove a memory by ID."""
        before = len(self._memories)
        self._memories = [m for m in self._memories if m.id != memory_id]
        if len(self._memories) < before:
            self._deleted.add(memory_id)
            self._dirty.discard(memory_id)
            self._save()
            return True
        return False

    def stats(self) -> Dict[str, Any]:
        """Get memory store statistics."""
        by_category = {}
        by_project = {}
        for m in self._memories:
            by_category[m.category] = by_category.get(m.category, 0) + 1
            by_project[m.project] = by_project.get(m.project, 0) + 1

        return {
            "total_memories": len(self._memories),
            "by_category": by_category,
            "by_project": by_project,
            "store_path": str(CID_HOME),
            "oldest": min((m.created_at for m in self._memories), default=0),
            "newest": max((m.created_at for m in self._memories), default=0),
        }

    # ─── Persistence ──────────────────────────────────────────────

    def _load(self):
        """Load memories from disk."""
        if self._memories_path.exists():
            try:
                data = json.loads(self._memories_path.read_text())
                self._memories = [Memory.from_dict(m) for m in data]
            except Exception:
                self._memories = []

    def _read_disk(self) -> Dict[str, dict]:
        """Current on-disk memories, keyed by id.

        A missing or empty file is an empty store. An unparseable file raises:
        treating it as empty (the old behaviour) meant the next save would
        replace every memory with only this process's unsaved records.
        """
        if not self._memories_path.exists():
            return {}
        text = self._memories_path.read_text()
        if not text.strip():
            return {}
        try:
            return {m["id"]: m for m in json.loads(text)}
        except (ValueError, KeyError, TypeError) as exc:
            raise CorruptMemoryStoreError(
                f"{self._memories_path} is not valid memory JSON ({exc}); refusing to overwrite it"
            ) from exc

    def _save(self):
        """Merge this process's changes into the store on disk.

        A store is a long-lived singleton, and several of them exist at once —
        Claude Code and Kiro each hold one over MCP, plus the cid-agent service.
        Writing self._memories wholesale meant whichever process saved last
        silently destroyed everything the others had added since they loaded,
        and it also resurrected content that had been edited on disk.

        So only the records this process actually touched are applied, on top of
        whatever is on disk right now. Everything else is left alone. The whole
        read-modify-write runs under an exclusive lock, and the result is put in
        place atomically, so a concurrent saver cannot observe a partial file.
        """
        # Lock a sibling file that is never replaced. Locking memories.json
        # itself did not serialise writers: os.replace swaps in a new inode, so
        # a writer that opened the path after the swap locked a different file
        # than one still holding the old inode, and both committed (2026-09-14
        # stress test: 34 of 240 concurrent remember() calls survived).
        lock_path = self._memories_path.with_name(self._memories_path.name + ".lock")
        with open(lock_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                merged = self._read_disk()

                for memory_id in self._deleted:
                    merged.pop(memory_id, None)

                by_id = {m.id: m for m in self._memories}
                for memory_id in self._dirty:
                    memory = by_id.get(memory_id)
                    if memory is not None:
                        merged[memory_id] = memory.to_dict()

                records = sorted(merged.values(), key=lambda m: m.get("created_at", 0))

                # Unique temp name per write: a shared ".json.tmp" let concurrent
                # writers clobber or delete each other's temp file.
                mode = (self._memories_path.stat().st_mode & 0o777) if self._memories_path.exists() else 0o600
                fd, tmp_name = tempfile.mkstemp(dir=self._memories_path.parent,
                                                prefix=".memories.", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                        tmp.write(json.dumps(records, indent=2))
                        tmp.flush()
                        os.fsync(tmp.fileno())
                    os.chmod(tmp_name, mode)
                    os.replace(tmp_name, self._memories_path)
                except BaseException:
                    if os.path.exists(tmp_name):
                        os.unlink(tmp_name)
                    raise
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        # Adopt the merged view so this process sees others' work too.
        self._memories = [Memory.from_dict(m) for m in records]
        self._dirty.clear()
        self._deleted.clear()


# ─── Singleton ────────────────────────────────────────────────────────────

_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    """Get or create the singleton MemoryStore."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
