"""A node that does not read must not stall the broker; a fixed node stays registered.

Background (2026-10-15): no swarm node read its socket after registering, and
the broker wrote + drained every relay inline in the PUSHING node's handler.
One non-reading recipient therefore wedged the pusher's handler (its own
messages and heartbeats went unread) and every relay queued behind it, while
TerrorNode re-registered every few minutes.

These tests run a real PatternBroker on an ephemeral port with a throwaway
token and talk to it over loopback TCP.
"""

import asyncio
import contextlib
import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

os.environ["DVCE_BROKER_TOKEN"] = "test-token-not-a-secret"
os.environ.setdefault("DVCE_BROKER_TOKEN_LEGACY", "")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "swarm"))
sys.path.insert(0, str(ROOT / "src" / "node"))

import broker as B  # noqa: E402
import network as N  # noqa: E402
import swarm_node as SN  # noqa: E402
from config import NodeConfig  # noqa: E402

TOKEN = os.environ["DVCE_BROKER_TOKEN"]


async def _start_broker(tmp_path):
    b = B.PatternBroker(host="127.0.0.1", port=0)
    b._store_path = tmp_path / "store.json"
    b.pattern_pool = []
    b._scorer = None  # relay every pattern; scoring is not under test
    b._nats_connected = False  # start() sets this; set here for the pre-fix broker too
    server = await asyncio.start_server(b._handle_connection, "127.0.0.1", 0)
    return b, server, server.sockets[0].getsockname()[1]


@contextlib.asynccontextmanager
async def _serving(server):
    """Serve, then abort every client socket and stop listening, pass or fail.

    Not `async with server`: Server.wait_closed() waits for every connection,
    so a failed assertion that leaves a client open would hang the test run.
    Items in `clients` are StreamWriters or NodeNetworkClients.
    """
    clients = []
    try:
        yield clients
    finally:
        for c in clients:
            w = getattr(c, "writer", c)
            if w is not None:
                w.transport.abort()
        server.close()
        await asyncio.sleep(0.05)


async def _raw_register(port, node_id):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write((json.dumps({"type": "register", "node_id": node_id, "domain": "tech",
                              "token": TOKEN}) + "\n").encode())
    await writer.drain()
    ack = json.loads(await asyncio.wait_for(reader.readline(), 2))
    assert ack["type"] == "registered"
    return reader, writer


async def _send(writer, msg):
    writer.write((json.dumps(msg) + "\n").encode())
    await asyncio.wait_for(writer.drain(), 2)


def _batch(n=20, pad=2000):
    return [{"event_type": "sc_port_congestion", "pad": "x" * pad} for _ in range(n)]


def _wait_until(pred, timeout=5.0):
    async def go():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return True
            await asyncio.sleep(0.02)
        return pred()
    return go()


def test_non_reading_node_does_not_stall_pusher_or_other_nodes(tmp_path, monkeypatch):
    """The stall: before the fix the pusher's handler blocked in drain() on the
    stuck node, so its heartbeat below was never processed and `healthy`
    stopped receiving relays."""
    monkeypatch.setattr(B, "OUTBOUND_MAX_BYTES", 256 * 1024)

    async def go():
        b, server, port = await _start_broker(tmp_path)
        async with _serving(server) as clients:
            _stuck_r, stuck_w = await _raw_register(port, "stuck")          # never reads
            healthy_r, healthy_w = await _raw_register(port, "healthy")
            _pusher_r, pusher_w = await _raw_register(port, "pusher")
            clients.extend([stuck_w, healthy_w, pusher_w])
            got = {"patterns": 0}

            async def drain_healthy():
                while line := await healthy_r.readline():
                    msg = json.loads(line)
                    if msg.get("type") == "patterns":
                        got["patterns"] += len(msg["patterns"])
            reader_task = asyncio.create_task(drain_healthy())

            n_batches = 300                                    # ~12 MB of relays
            for i in range(1, n_batches + 1):
                await _send(pusher_w, {"type": "patterns", "patterns": _batch()})
                # Pace on the reading node only, so it never falls behind; if
                # the pusher's handler stalled, this wait would time out.
                assert await _wait_until(lambda: got["patterns"] >= i * 20, 3), \
                    f"relays stopped after {got['patterns']} patterns"

            # The pusher's next heartbeat and the stuck node's heartbeat are
            # both processed promptly.
            b.nodes["pusher"].last_heartbeat = 0.0
            b.nodes["stuck"].last_heartbeat = 0.0
            await _send(pusher_w, {"type": "heartbeat", "node_id": "pusher"})
            await _send(stuck_w, {"type": "heartbeat", "node_id": "stuck"})
            assert await _wait_until(lambda: b.nodes["pusher"].last_heartbeat > 0, 3), \
                "pusher's handler is stalled behind the non-reading node"
            assert await _wait_until(lambda: b.nodes["stuck"].last_heartbeat > 0, 3)

            # Every relay reached the reading node.
            expected = n_batches * 20
            assert await _wait_until(lambda: got["patterns"] == expected, 10), got

            status = {n["node_id"]: n for n in b._get_status()["nodes"]}
            assert status["stuck"]["messages_dropped"] > 0
            assert status["stuck"]["patterns_dropped"] > 0
            assert status["healthy"]["messages_dropped"] == 0
            assert status["healthy"]["patterns_sent"] == expected
            assert set(b.nodes) == {"stuck", "healthy", "pusher"}

            reader_task.cancel()
    asyncio.run(go())


def test_reaper_aborts_a_stale_node_with_unsent_data(tmp_path, monkeypatch):
    """close() on a socket whose peer stopped reading waits forever; the reaper aborts."""
    monkeypatch.setattr(B, "CLEANUP_INTERVAL", 0.05)
    monkeypatch.setattr(B, "NODE_STALE_AFTER", 0.3)

    async def go():
        b, server, port = await _start_broker(tmp_path)
        async with _serving(server) as clients:
            stuck_r, stuck_w = await _raw_register(port, "stuck")
            _p_r, pusher_w = await _raw_register(port, "pusher")
            clients.extend([stuck_w, pusher_w])
            for _ in range(100):
                await _send(pusher_w, {"type": "patterns", "patterns": _batch()})
            reaper = asyncio.create_task(b._periodic_cleanup())
            await _send(pusher_w, {"type": "heartbeat", "node_id": "pusher"})
            assert await _wait_until(lambda: "stuck" not in b.nodes, 3)
            # The broker side really closed: the stuck peer sees EOF / reset.
            closed = False
            try:
                while await asyncio.wait_for(stuck_r.read(1 << 20), 3):
                    pass
                closed = True
            except (ConnectionError, OSError):
                closed = True
            assert closed
            reaper.cancel()
    asyncio.run(go())


def _client(port, node_id="fixed-node"):
    return N.NodeNetworkClient(node_id=node_id, domain="tech", broker_host="127.0.0.1",
                               broker_port=port, expertise_scores={"tech": 0.5})


def test_fixed_node_stays_registered_under_sustained_broadcasts(tmp_path):
    async def go():
        b, server, port = await _start_broker(tmp_path)
        async with _serving(server) as clients:
            cfg = NodeConfig(node_id="fixed-node", node_name="t", domain="tech",
                             broker_host="127.0.0.1", broker_port=port)
            cfg.gossip_interval_seconds = 0.1
            node = SN.SwarmNode(cfg)
            node.network = _client(port)
            clients.append(node.network)
            node.running = True
            node.stats["uptime_start"] = time.time()
            await node.network.connect()
            loop_task = asyncio.create_task(node._main_loop())

            _p_r, pusher_w = await _raw_register(port, "pusher")
            clients.append(pusher_w)
            n_batches = 400                                    # ~16 MB relayed to the node
            for _ in range(n_batches):
                await _send(pusher_w, {"type": "patterns", "patterns": _batch()})
            expected = n_batches * 20
            assert await _wait_until(
                lambda: node.network.stats["patterns_relayed_to_us"] == expected, 10
            ), node.network.stats

            b.nodes["fixed-node"].last_heartbeat = 0.0
            assert await _wait_until(lambda: b.nodes["fixed-node"].last_heartbeat > 0, 3)
            assert node.network.connected
            assert node.network.stats["registrations"] == 1
            entry = b._get_status()["nodes"]
            fixed = next(n for n in entry if n["node_id"] == "fixed-node")
            assert fixed["messages_dropped"] == 0
            assert node.foreign_patterns == []          # drained, not stored

            node.running = False
            loop_task.cancel()
            await node.network.disconnect()
    asyncio.run(go())


def test_concurrent_connects_register_once(tmp_path):
    async def go():
        b, server, port = await _start_broker(tmp_path)
        async with _serving(server) as clients:
            c = _client(port)
            clients.append(c)
            await asyncio.gather(c.connect(), c.connect(), c.connect())
            assert c.stats["registrations"] == 1
            assert b.stats["total_connections"] == 1
            await c.disconnect()
    asyncio.run(go())


def test_node_reconnects_once_after_the_broker_drops_it(tmp_path):
    async def go():
        b, server, port = await _start_broker(tmp_path)
        async with _serving(server) as clients:
            c = _client(port)
            clients.append(c)
            c.reconnect_interval = 0.05
            await c.connect()
            b.nodes["fixed-node"].writer.transport.abort()       # broker-side drop
            assert await _wait_until(lambda: not c.connected, 3)
            assert await c.wait_lost(0.01)
            await c.reconnect()
            assert c.connected and c.stats["registrations"] == 2
            assert await c.send_heartbeat()
            status = await c.request_status()
            assert status["type"] == "broker_status"
            assert [n["node_id"] for n in status["nodes"]] == ["fixed-node"]
            await c.disconnect()
    asyncio.run(go())


def test_rejected_registration_backs_off_and_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("DVCE_BROKER_TOKEN", "wrong-token")
    monkeypatch.setattr(B, "_send_sms_alert", lambda msg: None)

    async def go():
        b, server, port = await _start_broker(tmp_path)
        async with _serving(server) as clients:
            c = _client(port)
            clients.append(c)
            c.reconnect_interval = 0.05
            task = asyncio.create_task(c.connect())
            assert await _wait_until(lambda: b.stats["total_connections"] >= 2, 3)
            assert not c.connected and b.nodes == {}
            task.cancel()
            await c.disconnect()
    asyncio.run(go())


def test_log_file_is_rotated(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        log = tmp_path / "logs" / "swarm_node.log"
        SN.setup_logging(str(log))
        added = [h for h in root.handlers if h not in before]
        rotating = [h for h in added if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(rotating) == 1
        assert rotating[0].maxBytes == SN.LOG_MAX_BYTES and rotating[0].backupCount == SN.LOG_BACKUPS
        logging.getLogger("swarm_node").info("hello from the node")
        rotating[0].flush()
        assert "hello from the node" in log.read_text()
        streams = [h for h in added if type(h) is logging.StreamHandler]
        assert [h.level for h in streams] == [logging.WARNING]   # service stderr stays quiet
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()


def test_heartbeat_interval_stays_below_the_broker_stale_limit():
    cfg = NodeConfig(node_id="t7", node_name="t", domain="grid")
    cfg.gossip_interval_seconds = 300          # TowerSeven's profile
    assert SN.SwarmNode(cfg).heartbeat_interval() <= B.NODE_STALE_AFTER / 4
