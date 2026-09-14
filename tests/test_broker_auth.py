"""Broker message auth + pattern validation (2026-09-14 audit).

Runs a real PatternBroker on an ephemeral port with a throwaway token and
talks to it over TCP, the way nodes do.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

os.environ["DVCE_BROKER_TOKEN"] = "test-token-not-a-secret"
os.environ.setdefault("DVCE_BROKER_TOKEN_LEGACY", "")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "swarm"))

import broker as B  # noqa: E402


async def _start(tmp_path):
    b = B.PatternBroker(host="127.0.0.1", port=0)
    b._store_path = tmp_path / "store.json"
    b.pattern_pool = []
    server = await asyncio.start_server(b._handle_connection, "127.0.0.1", 0)
    return b, server, server.sockets[0].getsockname()[1]


async def _exchange(port, messages, expect_replies):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    replies = []
    for m in messages:
        writer.write((json.dumps(m) + "\n").encode())
        await writer.drain()
    for _ in range(expect_replies):
        line = await asyncio.wait_for(reader.readline(), timeout=2)
        replies.append(json.loads(line) if line else None)
    writer.close()
    return replies


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_unauthenticated_patterns_are_rejected_and_not_stored(tmp_path):
    async def go():
        b, server, port = await _start(tmp_path)
        async with server:
            replies = await _exchange(port, [{"type": "patterns", "source_node": "x",
                                              "patterns": [{"event_type": "fn_rate_hike"}]}], 1)
        return b, replies
    b, replies = _run(go())
    assert replies[0] == {"type": "rejected", "reason": "not authenticated"}
    assert b.pattern_pool == []


def test_loopback_status_allowed_without_registering(tmp_path):
    async def go():
        b, server, port = await _start(tmp_path)
        async with server:
            return await _exchange(port, [{"type": "status"}], 1)
    assert _run(go())[0]["type"] == "broker_status"


def test_heartbeat_cannot_hijack_a_registered_node(tmp_path):
    async def go():
        b, server, port = await _start(tmp_path)
        async with server:
            r1, w1 = await asyncio.open_connection("127.0.0.1", port)
            w1.write((json.dumps({"type": "register", "node_id": "rondo", "domain": "logistics",
                                  "token": "test-token-not-a-secret"}) + "\n").encode())
            await w1.drain()
            await r1.readline()
            original_writer = b.nodes["rondo"].writer
            replies = await _exchange(port, [{"type": "heartbeat", "node_id": "rondo"}], 1)
            hijacked = b.nodes["rondo"].writer is not original_writer
            w1.close()
            return replies, hijacked
    replies, hijacked = _run(go())
    assert replies[0]["type"] == "rejected"
    assert not hijacked


def test_authenticated_patterns_are_validated(tmp_path):
    good = {"event_type": "fn_rate_hike", "severity_score": 0.5}
    bad = [{"event_type": "DROP TABLE; --"}, "not-a-dict", {"sequence": ["ok_type", 5]},
           {"blob": "x" * (B.MAX_PATTERN_BYTES + 1)}]

    async def go():
        b, server, port = await _start(tmp_path)
        async with server:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            for m in ({"type": "register", "node_id": "finnhub-realtime", "domain": "financial",
                       "token": "test-token-not-a-secret"},
                      {"type": "patterns", "source_node": "spoofed-name", "patterns": [good] + bad}):
                w.write((json.dumps(m) + "\n").encode())
                await w.drain()
            ack = json.loads(await r.readline())
            await asyncio.sleep(0.2)
            w.close()
            return b, ack
    b, ack = _run(go())
    assert ack["type"] == "registered"
    assert [p["event_type"] for p in b.pattern_pool] == ["fn_rate_hike"]


def test_register_with_wrong_token_rejected(tmp_path):
    async def go():
        b, server, port = await _start(tmp_path)
        async with server:
            return await _exchange(port, [{"type": "register", "node_id": "evil", "domain": "x",
                                           "token": "wrong"}], 1)
    assert _run(go())[0] == {"type": "rejected", "reason": "invalid token"}
