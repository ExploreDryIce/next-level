"""
Network client — handles connection between a swarm node and the broker.

This is the communication layer that each node uses to:
1. Register with the broker
2. Send local patterns
3. Receive foreign patterns
4. Send heartbeats
5. Route prediction queries
"""

import asyncio
import json
import logging
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


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
        self.reconnect_interval = 5

    async def connect(self):
        """Connect to the broker and register."""
        while True:
            try:
                self.reader, self.writer = await asyncio.open_connection(
                    self.broker_host, self.broker_port
                )
                self.connected = True
                logger.info(f"🔗 Connected to broker at {self.broker_host}:{self.broker_port}")

                # Register
                await self._send({
                    "type": "register",
                    "node_id": self.node_id,
                    "domain": self.domain,
                    "expertise_scores": self.expertise_scores,
                })

                # Wait for ack
                response = await self._receive()
                if response and response.get("type") == "registered":
                    swarm_size = response.get("swarm_size", 0)
                    logger.info(f"   Registered! Swarm size: {swarm_size} nodes")

                return True

            except (ConnectionRefusedError, OSError) as e:
                logger.warning(
                    f"   Cannot reach broker at {self.broker_host}:{self.broker_port} "
                    f"— retrying in {self.reconnect_interval}s..."
                )
                await asyncio.sleep(self.reconnect_interval)

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

    async def send_heartbeat(self):
        """Send a heartbeat with current expertise scores."""
        if not self.connected:
            return

        await self._send({
            "type": "heartbeat",
            "node_id": self.node_id,
            "expertise_scores": self.expertise_scores,
            "timestamp": time.time(),
        })

    async def listen_for_patterns(self):
        """Listen for incoming patterns from the broker."""
        while self.connected:
            try:
                message = await self._receive()
                if message is None:
                    # Connection lost
                    self.connected = False
                    logger.warning("   Connection to broker lost")
                    break

                if message.get("type") == "patterns":
                    patterns = message.get("patterns", [])
                    if patterns and self.on_patterns_received:
                        self.on_patterns_received(patterns)

            except Exception as e:
                logger.error(f"   Listen error: {e}")
                await asyncio.sleep(1)

    async def request_status(self) -> Optional[dict]:
        """Request broker status."""
        await self._send({"type": "status"})
        return await self._receive()

    async def disconnect(self):
        """Gracefully disconnect from the broker."""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.connected = False
        logger.info("   Disconnected from broker")

    # ─── INTERNAL ───

    async def _send(self, message: dict):
        """Send a JSON message to the broker."""
        if not self.writer:
            return
        try:
            data = json.dumps(message) + "\n"
            self.writer.write(data.encode())
            await self.writer.drain()
        except Exception as e:
            logger.error(f"   Send failed: {e}")
            self.connected = False

    async def _receive(self) -> Optional[dict]:
        """Receive a JSON message from the broker."""
        if not self.reader:
            return None
        try:
            data = await asyncio.wait_for(self.reader.readline(), timeout=30.0)
            if not data:
                return None
            return json.loads(data.decode().strip())
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"   Receive failed: {e}")
            return None
