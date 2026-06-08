"""
Pattern Broker — the gossip layer connecting all swarm nodes.

In Phase 2 (hub & spoke), this runs on the coordinator (Mac) and 
relays patterns between nodes. In Phase 3+, this becomes NATS JetStream.

For now: a simple async TCP server that:
1. Accepts connections from nodes
2. Receives patterns from any node  
3. Broadcasts relevant patterns to other nodes
4. Tracks node health (heartbeats)
5. Maintains the expertise routing table

Protocol: JSON over TCP (simple, debuggable, upgradeable to NATS later)
"""

import asyncio
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ConnectedNode:
    """Tracks a connected swarm node."""
    node_id: str
    domain: str
    expertise_scores: Dict[str, float]
    writer: asyncio.StreamWriter
    last_heartbeat: float = 0.0
    patterns_received: int = 0
    patterns_sent: int = 0


class PatternBroker:
    """
    Central pattern relay for the swarm (Phase 2 architecture).
    
    Runs on the coordinator node (Mac). All other nodes connect to this.
    Receives patterns, decides relevance, forwards to interested nodes.
    Persists patterns to disk so intelligence survives restarts.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9876):
        self.host = host
        self.port = port
        self.nodes: Dict[str, ConnectedNode] = {}
        self.pattern_pool: List[dict] = []
        self.max_pool_size = 50000
        self.server = None
        self.stats = {
            "total_patterns_relayed": 0,
            "total_connections": 0,
            "start_time": 0,
        }

        # Persistence
        self._store_path = Path.home() / ".dvce" / "swarm" / "pattern_store.json"
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._dirty = False  # Patterns modified since last save
        self._load_pattern_store()

    async def start(self):
        """Start the broker server."""
        self.stats["start_time"] = time.time()

        # Start NATS bridge (runs alongside TCP for backward compat)
        await self._start_nats_bridge()

        self.server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )

        addr = self.server.sockets[0].getsockname()
        logger.info(f"🌐 Pattern Broker running on {addr[0]}:{addr[1]}")
        logger.info(f"   Pattern store: {self._store_path} ({len(self.pattern_pool)} patterns loaded)")
        logger.info(f"   NATS bridge: {'connected' if self._nats_connected else 'unavailable (TCP only)'}")
        logger.info(f"   Waiting for swarm nodes to connect...")

        # Start periodic tasks
        asyncio.create_task(self._periodic_save())
        asyncio.create_task(self._periodic_cleanup())

        async with self.server:
            await self.server.serve_forever()

    async def _start_nats_bridge(self):
        """Initialize NATS JetStream bridge if available."""
        self._nats_connected = False
        try:
            from nats_bridge import NATSBridge
            self._nats = NATSBridge(node_id="broker")
            self._nats_connected = await self._nats.connect()
        except Exception as e:
            logger.info(f"   NATS bridge not available: {e}")
            self._nats = None

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a new node connection."""
        addr = writer.get_extra_info("peername")
        logger.info(f"📡 New connection from {addr}")
        self.stats["total_connections"] += 1

        node_info = None

        try:
            while True:
                # Read message (newline-delimited JSON)
                data = await reader.readline()
                if not data:
                    break

                message = json.loads(data.decode().strip())
                msg_type = message.get("type")

                if msg_type == "register":
                    # Node registering itself
                    node_info = ConnectedNode(
                        node_id=message["node_id"],
                        domain=message["domain"],
                        expertise_scores=message.get("expertise_scores", {}),
                        writer=writer,
                        last_heartbeat=time.time(),
                    )
                    self.nodes[node_info.node_id] = node_info
                    logger.info(
                        f"   ✅ Registered: {node_info.node_id} "
                        f"(domain={node_info.domain}, expertise={node_info.expertise_scores})"
                    )

                    # Send acknowledgment + current swarm status
                    ack = {
                        "type": "registered",
                        "swarm_size": len(self.nodes),
                        "nodes": [
                            {"node_id": n.node_id, "domain": n.domain}
                            for n in self.nodes.values()
                        ],
                    }
                    writer.write((json.dumps(ack) + "\n").encode())
                    await writer.drain()

                elif msg_type == "patterns":
                    # Node sharing patterns
                    patterns = message.get("patterns", [])
                    source_node = message.get("source_node", "unknown")

                    logger.info(f"   📨 Received {len(patterns)} patterns from {source_node}")

                    # Store in pool
                    for p in patterns:
                        p["received_at"] = time.time()
                        self.pattern_pool.append(p)
                    self._dirty = True

                    # Trim pool if too large
                    if len(self.pattern_pool) > self.max_pool_size:
                        self.pattern_pool = self.pattern_pool[-self.max_pool_size:]

                    # Broadcast to other nodes (TCP)
                    await self._broadcast_patterns(patterns, exclude_node=source_node)

                    # Also publish to NATS JetStream for persistence + replay
                    if self._nats_connected and self._nats:
                        domain = node_info.domain if node_info else "general"
                        asyncio.create_task(self._nats.publish_patterns(patterns, domain=domain))

                    if node_info:
                        node_info.patterns_received += len(patterns)

                elif msg_type == "heartbeat":
                    if node_info:
                        node_info.last_heartbeat = time.time()
                        node_info.expertise_scores = message.get("expertise_scores", node_info.expertise_scores)

                elif msg_type == "query":
                    # Route a prediction query to the best node
                    query_domain = message.get("domain", "")
                    response = await self._route_query(message, query_domain)
                    writer.write((json.dumps(response) + "\n").encode())
                    await writer.drain()

                elif msg_type == "status":
                    # Return broker status
                    status = self._get_status()
                    writer.write((json.dumps(status) + "\n").encode())
                    await writer.drain()

        except (asyncio.IncompleteReadError, ConnectionResetError, json.JSONDecodeError) as e:
            logger.info(f"   Connection closed: {addr} ({e.__class__.__name__})")
        finally:
            if node_info and node_info.node_id in self.nodes:
                del self.nodes[node_info.node_id]
                logger.info(f"   ❌ Node disconnected: {node_info.node_id}")
            writer.close()

    async def _broadcast_patterns(self, patterns: List[dict], exclude_node: str):
        """Send patterns to all connected nodes except the source."""
        message = json.dumps({
            "type": "patterns",
            "patterns": patterns,
            "source": "broker",
        }) + "\n"

        for node_id, node in list(self.nodes.items()):
            if node_id == exclude_node:
                continue
            try:
                node.writer.write(message.encode())
                await node.writer.drain()
                node.patterns_sent += len(patterns)
                self.stats["total_patterns_relayed"] += len(patterns)
            except Exception as e:
                logger.warning(f"   Failed to send to {node_id}: {e}")

    async def _route_query(self, query: dict, domain: str) -> dict:
        """Route a prediction query to the best-suited node."""
        best_node = None
        best_score = 0.0

        for node in self.nodes.values():
            score = node.expertise_scores.get(domain, 0.0)
            if score > best_score:
                best_score = score
                best_node = node

        if best_node:
            return {
                "type": "route",
                "routed_to": best_node.node_id,
                "expertise_score": best_score,
                "domain": domain,
            }
        else:
            return {
                "type": "route",
                "routed_to": None,
                "error": f"No node with expertise in '{domain}'",
            }

    def _get_status(self) -> dict:
        """Get broker status."""
        uptime = time.time() - self.stats["start_time"]
        return {
            "type": "broker_status",
            "uptime_seconds": int(uptime),
            "connected_nodes": len(self.nodes),
            "pattern_pool_size": len(self.pattern_pool),
            "total_patterns_relayed": self.stats["total_patterns_relayed"],
            "pattern_store_path": str(self._store_path),
            "nodes": [
                {
                    "node_id": n.node_id,
                    "domain": n.domain,
                    "expertise": n.expertise_scores,
                    "patterns_received": n.patterns_received,
                    "patterns_sent": n.patterns_sent,
                    "last_heartbeat_ago": int(time.time() - n.last_heartbeat),
                }
                for n in self.nodes.values()
            ],
        }

    # ─── PERSISTENCE ───

    def _load_pattern_store(self):
        """Load persisted patterns from disk on startup."""
        if self._store_path.exists():
            try:
                data = json.loads(self._store_path.read_text())
                # Filter expired patterns
                now = time.time()
                self.pattern_pool = [
                    p for p in data
                    if (now - p.get("timestamp", 0)) / 86400 <= p.get("ttl", 7)
                ]
                logger.info(f"   Loaded {len(self.pattern_pool)} patterns from store (filtered {len(data) - len(self.pattern_pool)} expired)")
            except Exception as e:
                logger.warning(f"   Failed to load pattern store: {e}")
                self.pattern_pool = []

    def _save_pattern_store(self):
        """Save current pattern pool to disk."""
        try:
            self._store_path.write_text(json.dumps(self.pattern_pool, indent=None))
            self._dirty = False
            logger.debug(f"   Saved {len(self.pattern_pool)} patterns to store")
        except Exception as e:
            logger.error(f"   Failed to save pattern store: {e}")

    async def _periodic_save(self):
        """Save pattern store every 30 seconds if dirty."""
        while True:
            await asyncio.sleep(30)
            if self._dirty:
                self._save_pattern_store()

    async def _periodic_cleanup(self):
        """Remove expired patterns every hour."""
        while True:
            await asyncio.sleep(3600)  # 1 hour
            now = time.time()
            before = len(self.pattern_pool)
            self.pattern_pool = [
                p for p in self.pattern_pool
                if (now - p.get("timestamp", 0)) / 86400 <= p.get("ttl", 7)
            ]
            removed = before - len(self.pattern_pool)
            if removed > 0:
                logger.info(f"   🧹 Cleanup: removed {removed} expired patterns")
                self._dirty = True


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    import argparse
    parser = argparse.ArgumentParser(description="DVCE Pattern Broker")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=9876, help="Bind port")
    args = parser.parse_args()

    broker = PatternBroker(host=args.host, port=args.port)
    asyncio.run(broker.start())


if __name__ == "__main__":
    main()
