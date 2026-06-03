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
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9876):
        self.host = host
        self.port = port
        self.nodes: Dict[str, ConnectedNode] = {}
        self.pattern_pool: List[dict] = []  # All patterns received
        self.max_pool_size = 10000
        self.server = None
        self.stats = {
            "total_patterns_relayed": 0,
            "total_connections": 0,
            "start_time": 0,
        }

    async def start(self):
        """Start the broker server."""
        self.stats["start_time"] = time.time()
        self.server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )

        addr = self.server.sockets[0].getsockname()
        logger.info(f"🌐 Pattern Broker running on {addr[0]}:{addr[1]}")
        logger.info(f"   Waiting for swarm nodes to connect...")

        async with self.server:
            await self.server.serve_forever()

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

                    # Trim pool if too large
                    if len(self.pattern_pool) > self.max_pool_size:
                        self.pattern_pool = self.pattern_pool[-self.max_pool_size:]

                    # Broadcast to other nodes
                    await self._broadcast_patterns(patterns, exclude_node=source_node)

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
