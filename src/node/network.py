"""
Network client — handles connection between a swarm node and the broker.

This is the communication layer that each node uses to:
1. Register with the broker (one connection at a time)
2. Send heartbeats (and, if a caller asks, local patterns)
3. Drain everything the broker sends, continuously
4. Reconnect with backoff when the connection really drops

Why the reader matters (2026-10-15): the node used to stop reading its socket
after registering. The broker relays every pushed pattern to every node, so the
node's receive buffer filled, the broker's writes to it backed up, and the node
re-registered every few minutes. A reader task now runs for the whole life of
each connection and consumes every line the broker sends. Relayed patterns are
counted and discarded unless a callback was given; the node does no ML on them.
"""

import asyncio
import json
import logging
import os
import random
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# The broker relays pattern batches of up to 1000 x 16 KB on a single line.
STREAM_LIMIT = 32 * 1024 * 1024
REGISTER_TIMEOUT = 30.0     # seconds to wait for the broker's ack
SEND_TIMEOUT = 30.0         # a heartbeat that cannot be written in this long means a dead link
CLOSE_TIMEOUT = 5.0
BACKOFF_INITIAL = 5.0
BACKOFF_MAX = 300.0
STABLE_AFTER = 60.0         # a connection that lived this long resets the backoff


class RegistrationRejected(RuntimeError):
    """The broker refused to register this node (bad token or not authenticated)."""


class NodeNetworkClient:
    """Async TCP client for swarm node ↔ broker communication."""

    def __init__(
        self,
        node_id: str,
        domain: str,
        broker_host: str,
        broker_port: int = 9876,
        expertise_scores: Dict[str, float] = None,
        on_patterns_received: Optional[Callable] = None,
    ):
        self.node_id = node_id
        self.domain = domain
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.expertise_scores = expertise_scores or {}
        self.on_patterns_received = on_patterns_received

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.reconnect_interval = BACKOFF_INITIAL   # first retry delay; doubles to BACKOFF_MAX

        self._registered_at = 0.0
        self._connect_lock = asyncio.Lock()
        self._reader_task: Optional[asyncio.Task] = None
        self._lost = asyncio.Event()           # set when the current connection drops
        self._status_waiters: List[asyncio.Future] = []

        # Counters for the status line; nothing else reads them.
        self.stats = {
            "registrations": 0,
            "messages_received": 0,
            "patterns_relayed_to_us": 0,
            "last_message_at": 0.0,
        }

    # ─── CONNECTION ───

    async def connect(self) -> bool:
        """Connect and register, retrying with exponential backoff until it works.

        Serialised by a lock: a second caller waits for the first and then
        returns at once if the node is already connected, so a node can never
        hold two registrations from one process.
        """
        async with self._connect_lock:
            if self.connected:
                return True
            delay = self.reconnect_interval
            while True:
                try:
                    await self._open_and_register()
                    return True
                except RegistrationRejected as e:
                    logger.error(f"   Broker rejected registration: {e}")
                except (OSError, asyncio.TimeoutError, ConnectionError, ValueError) as e:
                    logger.warning(
                        f"   Cannot register with broker at {self.broker_host}:{self.broker_port} "
                        f"({e.__class__.__name__}: {e})"
                    )
                await self._close_transport()
                wait = delay * random.uniform(0.8, 1.2)
                logger.info(f"   Retrying in {wait:.0f}s")
                await asyncio.sleep(wait)
                delay = min(delay * 2, BACKOFF_MAX)

    async def reconnect(self) -> bool:
        """Drop the current connection (if any) and register again.

        A connection that died young counts as a failure: the next attempt
        waits and the backoff keeps growing, so a link that registers and then
        drops at once cannot turn into a tight re-registration loop.
        """
        await self.disconnect()
        lived = time.time() - self._registered_at if self._registered_at else None
        if lived is not None and lived < STABLE_AFTER:
            wait = self.reconnect_interval * random.uniform(0.8, 1.2)
            logger.warning(f"   Last connection lasted {lived:.0f}s; waiting {wait:.0f}s before re-registering")
            self.reconnect_interval = min(self.reconnect_interval * 2, BACKOFF_MAX)
            await asyncio.sleep(wait)
        else:
            self.reconnect_interval = BACKOFF_INITIAL
        return await self.connect()

    async def _open_and_register(self):
        # Never leave an older socket open behind a new one: the broker would
        # count it as a second registration and drop it as silent minutes later.
        await self._close_transport()
        self.reader, self.writer = await asyncio.open_connection(
            self.broker_host, self.broker_port, limit=STREAM_LIMIT
        )
        logger.info(f"🔗 Connected to broker at {self.broker_host}:{self.broker_port}")

        self.writer.write((json.dumps({
            "type": "register",
            "node_id": self.node_id,
            "domain": self.domain,
            "expertise_scores": self.expertise_scores,
            # No default: the previous fallback published the real token
            # in a public repo. An unset var should fail to authenticate
            # loudly rather than succeed on a known secret.
            "token": os.environ["DVCE_BROKER_TOKEN"],
        }) + "\n").encode())
        await asyncio.wait_for(self.writer.drain(), timeout=SEND_TIMEOUT)

        line = await asyncio.wait_for(self.reader.readline(), timeout=REGISTER_TIMEOUT)
        if not line:
            raise ConnectionError("broker closed the connection before acknowledging")
        ack = json.loads(line)
        if ack.get("type") == "rejected":
            raise RegistrationRejected(ack.get("reason", "no reason given"))
        if ack.get("type") != "registered":
            raise ConnectionError(f"unexpected reply to register: {ack.get('type')!r}")

        self.connected = True
        self._registered_at = time.time()
        self.stats["registrations"] += 1
        self._lost = asyncio.Event()
        self._reader_task = asyncio.create_task(self._read_loop(self.reader))
        logger.info(f"   Registered! Swarm size: {ack.get('swarm_size', 0)} nodes")

    async def disconnect(self):
        """Gracefully disconnect from the broker."""
        was_open = self.writer is not None
        await self._close_transport()
        if was_open:
            logger.info("   Disconnected from broker")

    async def _close_transport(self):
        task, self._reader_task = self._reader_task, None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        writer, self.writer, self.reader = self.writer, None, None
        self.connected = False
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=CLOSE_TIMEOUT)
            except asyncio.TimeoutError:
                writer.transport.abort()
            except (ConnectionError, OSError):
                pass

    def _mark_lost(self, reason: str):
        if self.connected:
            logger.warning(f"   Connection to broker lost: {reason}")
        self.connected = False
        self._lost.set()
        for fut in self._status_waiters:
            if not fut.done():
                fut.set_result(None)
        self._status_waiters.clear()

    async def wait_lost(self, timeout: float) -> bool:
        """Sleep up to `timeout` seconds; return early (True) if the link drops."""
        try:
            await asyncio.wait_for(self._lost.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ─── READER ───

    async def _read_loop(self, reader: asyncio.StreamReader):
        """Consume every line the broker sends for as long as the connection lives.

        Silence is normal (the broker only writes when it has something to
        relay), so there is no idle timeout here; liveness is the heartbeat's
        job. EOF or a socket error marks the connection lost.
        """
        try:
            while True:
                line = await reader.readline()
                if not line:
                    self._mark_lost("broker closed the connection")
                    return
                self.stats["messages_received"] += 1
                self.stats["last_message_at"] = time.time()
                try:
                    message = json.loads(line)
                except ValueError:
                    logger.debug("   Ignoring undecodable line from broker")
                    continue
                if isinstance(message, dict):
                    self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError, ValueError) as e:
            # ValueError: a line longer than STREAM_LIMIT; the stream is unusable.
            self._mark_lost(f"{e.__class__.__name__}: {e}")

    def _handle_message(self, message: dict):
        msg_type = message.get("type")
        if msg_type == "patterns":
            patterns = message.get("patterns") or []
            self.stats["patterns_relayed_to_us"] += len(patterns)
            if patterns and self.on_patterns_received:
                try:
                    self.on_patterns_received(patterns)
                except Exception as e:  # a bad callback must not kill the reader
                    logger.warning(f"   Pattern callback failed: {e}")
        elif msg_type == "broker_status":
            while self._status_waiters:
                fut = self._status_waiters.pop(0)
                if not fut.done():
                    fut.set_result(message)
                    break
        elif msg_type == "rejected":
            logger.error(f"   Broker rejected a message: {message.get('reason')}")
        # Anything else (route replies, future message types) is ignored.

    # ─── SENDING ───

    async def send_patterns(self, patterns: List[dict]):
        """Send local patterns to the broker for distribution."""
        if not self.connected:
            return
        await self._send({
            "type": "patterns",
            "source_node": self.node_id,
            "patterns": patterns,
        })
        logger.info(f"   📤 Sent {len(patterns)} patterns to broker")

    async def send_heartbeat(self) -> bool:
        """Send a heartbeat. Returns False (and marks the link lost) on failure."""
        if not self.connected:
            return False
        return await self._send({
            "type": "heartbeat",
            "node_id": self.node_id,
            "expertise_scores": self.expertise_scores,
            "timestamp": time.time(),
        })

    async def listen_for_patterns(self):
        """Kept for callers of the old API: the reader now starts on every connect."""
        if self._reader_task is not None:
            await asyncio.shield(self._reader_task)

    async def request_status(self, timeout: float = 10.0) -> Optional[dict]:
        """Ask the broker for its status; the reader task delivers the reply."""
        if not self.connected:
            return None
        fut = asyncio.get_running_loop().create_future()
        self._status_waiters.append(fut)
        if not await self._send({"type": "status"}):
            return None
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            if fut in self._status_waiters:
                self._status_waiters.remove(fut)
            return None

    async def _send(self, message: dict) -> bool:
        """Write one JSON line. Bounded, so a dead link surfaces as a failure."""
        if not self.writer:
            return False
        try:
            self.writer.write((json.dumps(message) + "\n").encode())
            await asyncio.wait_for(self.writer.drain(), timeout=SEND_TIMEOUT)
            return True
        except (asyncio.TimeoutError, ConnectionError, OSError, RuntimeError) as e:
            logger.error(f"   Send failed: {e.__class__.__name__}: {e}")
            self._mark_lost(f"send failed ({e.__class__.__name__})")
            return False
