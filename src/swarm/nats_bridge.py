"""
NATS JetStream Bridge — production-grade pattern messaging.

Runs alongside the TCP broker during transition period.
Provides:
- Pattern persistence (7-day retention via JetStream)
- Automatic replay on reconnect (nodes get missed patterns)
- Pub/sub for cross-domain pattern distribution
- Subject-based routing (swarm.patterns.{domain})

Usage:
    bridge = NATSBridge()
    await bridge.connect()
    await bridge.publish_patterns(patterns, domain="financial")
    
    # Subscribe to all patterns
    await bridge.subscribe_patterns(callback)
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import nats
    from nats.js.api import StreamConfig, RetentionPolicy, ConsumerConfig, DeliverPolicy
    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False
    logger.info("nats-py not installed — NATS bridge disabled (pip install nats-py)")


class NATSBridge:
    """NATS JetStream bridge for the swarm pattern network."""

    STREAM_NAME = "DVCE_PATTERNS"
    SUBJECT_PATTERNS = "swarm.patterns.{domain}"
    SUBJECT_STATUS = "swarm.status.{node_id}"
    SUBJECT_QUERIES = "swarm.queries.{domain}"

    def __init__(
        self,
        nats_url: str = "nats://127.0.0.1:4222",
        node_id: str = "unknown",
    ):
        self.nats_url = nats_url
        self.node_id = node_id
        self._nc = None
        self._js = None
        self._connected = False
        self._subscriptions = []

    async def connect(self) -> bool:
        """Connect to NATS and set up JetStream."""
        if not NATS_AVAILABLE:
            logger.warning("NATS bridge: nats-py not available")
            return False

        try:
            self._nc = await nats.connect(self.nats_url)
            self._js = self._nc.jetstream()

            # Create or get the patterns stream
            try:
                await self._js.add_stream(
                    config=StreamConfig(
                        name=self.STREAM_NAME,
                        subjects=["swarm.patterns.>", "swarm.status.>"],
                        retention=RetentionPolicy.LIMITS,
                        max_age=7 * 24 * 3600 * 1_000_000_000,  # 7 days in nanoseconds
                        max_bytes=1_000_000_000,  # 1 GB max
                        storage="file",
                    )
                )
                logger.info("NATS: Created stream %s", self.STREAM_NAME)
            except Exception:
                # Stream already exists
                logger.info("NATS: Stream %s already exists", self.STREAM_NAME)

            self._connected = True
            logger.info("NATS: Connected to %s (JetStream enabled)", self.nats_url)
            return True

        except Exception as e:
            logger.warning("NATS: Connection failed: %s", e)
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnect from NATS."""
        if self._nc:
            await self._nc.close()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._nc and self._nc.is_connected

    # ─── Pattern Publishing ───────────────────────────────────────

    async def publish_patterns(self, patterns: List[dict], domain: str = "general"):
        """Publish patterns to JetStream for persistence and distribution."""
        if not self.is_connected:
            return 0

        subject = self.SUBJECT_PATTERNS.format(domain=domain)
        published = 0

        for pattern in patterns:
            try:
                payload = json.dumps({
                    "type": "pattern",
                    "source_node": self.node_id,
                    "domain": domain,
                    "pattern": pattern,
                    "published_at": time.time(),
                }).encode()

                await self._js.publish(subject, payload)
                published += 1
            except Exception as e:
                logger.warning("NATS: Failed to publish pattern: %s", e)

        if published > 0:
            logger.info("NATS: Published %d patterns to %s", published, subject)
        return published

    async def publish_status(self, status: dict):
        """Publish node status update."""
        if not self.is_connected:
            return

        subject = self.SUBJECT_STATUS.format(node_id=self.node_id)
        try:
            payload = json.dumps({
                "type": "status",
                "node_id": self.node_id,
                "status": status,
                "timestamp": time.time(),
            }).encode()
            await self._js.publish(subject, payload)
        except Exception as e:
            logger.debug("NATS: Status publish failed: %s", e)

    # ─── Pattern Subscription ────────────────────────────────────

    async def subscribe_patterns(
        self,
        callback: Callable[[List[dict]], None],
        domain_filter: str = "*",
        deliver_policy: str = "new",
    ):
        """Subscribe to patterns from all domains.
        
        Args:
            callback: Function called with list of pattern dicts
            domain_filter: "*" for all, or specific domain name
            deliver_policy: "new" for only new, "last" for last per subject,
                          "all" for full replay since stream creation
        """
        if not self.is_connected:
            return

        subject = self.SUBJECT_PATTERNS.format(domain=domain_filter)

        # Create a durable consumer for this node
        consumer_name = f"node_{self.node_id.replace('-', '_')}"

        policy_map = {
            "new": DeliverPolicy.NEW,
            "last": DeliverPolicy.LAST,
            "all": DeliverPolicy.ALL,
        }

        try:
            sub = await self._js.subscribe(
                subject,
                durable=consumer_name,
                config=ConsumerConfig(
                    deliver_policy=policy_map.get(deliver_policy, DeliverPolicy.NEW),
                    ack_wait=30,
                ),
            )
            self._subscriptions.append(sub)

            # Process messages in background
            asyncio.create_task(self._process_subscription(sub, callback))
            logger.info("NATS: Subscribed to %s (consumer=%s, policy=%s)",
                       subject, consumer_name, deliver_policy)

        except Exception as e:
            logger.warning("NATS: Subscribe failed: %s", e)

    async def _process_subscription(self, sub, callback):
        """Process incoming pattern messages."""
        batch = []
        last_flush = time.time()

        async for msg in sub.messages:
            try:
                data = json.loads(msg.data.decode())
                pattern = data.get("pattern")
                if pattern and data.get("source_node") != self.node_id:
                    batch.append(pattern)

                await msg.ack()

                # Flush batch every 5 patterns or 2 seconds
                if len(batch) >= 5 or (time.time() - last_flush) > 2:
                    if batch:
                        callback(batch)
                        batch = []
                        last_flush = time.time()

            except Exception as e:
                logger.debug("NATS: Message processing error: %s", e)

    # ─── Stream Info ─────────────────────────────────────────────

    async def get_stream_info(self) -> Dict[str, Any]:
        """Get stream statistics."""
        if not self.is_connected:
            return {"connected": False}

        try:
            info = await self._js.stream_info(self.STREAM_NAME)
            return {
                "connected": True,
                "stream": self.STREAM_NAME,
                "messages": info.state.messages,
                "bytes": info.state.bytes,
                "first_seq": info.state.first_seq,
                "last_seq": info.state.last_seq,
                "consumer_count": info.state.consumer_count,
            }
        except Exception as e:
            return {"connected": True, "error": str(e)}
