"""
DVCE Command Center — System Intelligence Controller

The command center is the single control plane for the entire system.
It connects:
  - DVCE product (prediction API, Streamlit app)
  - Swarm network (broker, nodes, patterns)
  - Projects (next-level, dvce-engine, homelab)

When you work on ANY project, the intelligence layer benefits:
  - Working on DVCE → generates predictions → patterns extracted → swarm improves
  - Working on homelab → TerrorNode/Pi activity → node health tracked
  - Working on next-level → swarm experiments → feeds back into DVCE

Phase 1 (NOW): CLI control + status dashboard
Phase 2: REST API for programmatic control
Phase 3: Auto-orchestration (nodes self-manage)
"""

import asyncio
import json
import time
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent / "node"))
sys.path.insert(0, str(Path(__file__).parent.parent / "swarm"))


@dataclass
class SystemState:
    """Current state of the entire DVCE ecosystem."""
    broker_online: bool = False
    nodes: Dict[str, dict] = field(default_factory=dict)
    pattern_pool_size: int = 0
    total_predictions: int = 0
    total_patterns_relayed: int = 0
    uptime_seconds: int = 0
    dvce_api_online: bool = False


class CommandCenter:
    """
    Central control for the DVCE intelligence ecosystem.
    
    Capabilities:
    - Monitor all nodes (health, expertise, load)
    - Control pattern flow (start/stop/filter gossip)
    - Route queries manually or let the swarm decide
    - Trigger model retraining on any node
    - View cross-domain cascade alerts
    - Export system metrics
    """

    def __init__(self, broker_host: str = "127.0.0.1", broker_port: int = 9876):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.state = SystemState()

    async def get_status(self) -> SystemState:
        """Pull current system status from the broker."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.broker_host, self.broker_port),
                timeout=5.0
            )
            writer.write((json.dumps({"type": "status"}) + "\n").encode())
            await writer.drain()
            data = await asyncio.wait_for(reader.readline(), timeout=5.0)
            status = json.loads(data.decode().strip())
            writer.close()
            await writer.wait_closed()

            self.state.broker_online = True
            self.state.nodes = {n["node_id"]: n for n in status.get("nodes", [])}
            self.state.pattern_pool_size = status.get("pattern_pool_size", 0)
            self.state.total_patterns_relayed = status.get("total_patterns_relayed", 0)
            self.state.uptime_seconds = status.get("uptime_seconds", 0)

        except Exception:
            self.state.broker_online = False

        return self.state

    async def inject_patterns(self, patterns: List[dict], source: str = "command-center"):
        """Manually inject patterns into the swarm."""
        try:
            reader, writer = await asyncio.open_connection(self.broker_host, self.broker_port)
            # Register
            writer.write((json.dumps({
                "type": "register",
                "node_id": source,
                "domain": "control",
                "expertise_scores": {},
            }) + "\n").encode())
            await writer.drain()
            await asyncio.wait_for(reader.readline(), timeout=5.0)

            # Send patterns
            writer.write((json.dumps({
                "type": "patterns",
                "source_node": source,
                "patterns": patterns,
            }) + "\n").encode())
            await writer.drain()

            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def route_query(self, domain: str) -> Optional[dict]:
        """Route a prediction query to the best node."""
        try:
            reader, writer = await asyncio.open_connection(self.broker_host, self.broker_port)
            writer.write((json.dumps({
                "type": "register",
                "node_id": "command-center-router",
                "domain": "control",
                "expertise_scores": {},
            }) + "\n").encode())
            await writer.drain()
            await asyncio.wait_for(reader.readline(), timeout=5.0)

            writer.write((json.dumps({
                "type": "query",
                "domain": domain,
            }) + "\n").encode())
            await writer.drain()
            data = await asyncio.wait_for(reader.readline(), timeout=5.0)
            response = json.loads(data.decode().strip())

            writer.close()
            await writer.wait_closed()
            return response
        except Exception:
            return None

    def print_dashboard(self):
        """Print a terminal dashboard of system state."""
        s = self.state
        
        print()
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║  DVCE COMMAND CENTER — Intelligence Layer                    ║")
        print("╠══════════════════════════════════════════════════════════════╣")
        
        # Broker
        broker_status = "🟢 ONLINE" if s.broker_online else "🔴 OFFLINE"
        print(f"║  Broker: {broker_status:<20} Uptime: {s.uptime_seconds}s{' ' * 15}║")
        print(f"║  Pattern Pool: {s.pattern_pool_size:<10} Relayed: {s.total_patterns_relayed:<20}║")
        
        print("║                                                              ║")
        print("║  NODES                                                       ║")
        print("║  ────────────────────────────────────────────────────────    ║")
        
        if s.nodes:
            for node_id, node in s.nodes.items():
                domain = node.get("domain", "?")
                expertise = node.get("expertise", {})
                top_exp = max(expertise.values()) if expertise else 0
                hb_ago = node.get("last_heartbeat_ago", 0)
                status = "🟢" if hb_ago < 120 else "🟡" if hb_ago < 300 else "🔴"
                p_recv = node.get("patterns_received", 0)
                p_sent = node.get("patterns_sent", 0)
                
                print(f"║  {status} {node_id:<15} domain={domain:<10} "
                      f"exp={top_exp:.2f} recv={p_recv} sent={p_sent}  ║")
        else:
            print("║  No nodes connected                                          ║")
        
        print("║                                                              ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print()


# ============================================================================
# CLI INTERFACE
# ============================================================================

async def cli_main():
    """Command-line interface for the command center."""
    import argparse

    parser = argparse.ArgumentParser(description="DVCE Command Center")
    parser.add_argument("command", choices=["status", "watch", "inject", "route"],
                        help="Command to execute")
    parser.add_argument("--domain", type=str, help="Domain for routing")
    parser.add_argument("--host", default="127.0.0.1", help="Broker host")
    parser.add_argument("--port", type=int, default=9876, help="Broker port")
    args = parser.parse_args()

    cc = CommandCenter(broker_host=args.host, broker_port=args.port)

    if args.command == "status":
        await cc.get_status()
        cc.print_dashboard()

    elif args.command == "watch":
        # Continuous monitoring
        print("Watching swarm (Ctrl+C to stop)...\n")
        try:
            while True:
                await cc.get_status()
                # Clear screen and reprint
                print("\033[2J\033[H", end="")
                cc.print_dashboard()
                await asyncio.sleep(5)
        except KeyboardInterrupt:
            print("\nStopped watching.")

    elif args.command == "route":
        if not args.domain:
            print("Error: --domain required for routing")
            return
        result = await cc.route_query(args.domain)
        if result:
            print(f"Query for '{args.domain}' → routed to: {result.get('routed_to')}")
            print(f"  Expertise score: {result.get('expertise_score', 0):.2f}")
        else:
            print("Failed to route query (broker offline?)")

    elif args.command == "inject":
        # Quick test pattern injection
        test_patterns = [{
            "pattern_id": f"manual_{int(time.time())}",
            "sequence": ["test_event_a", "test_event_b", "test_event_c"],
            "confidence": 0.95,
            "source_domain": "control",
            "source_node": "command-center",
            "avg_time_delta": 60.0,
            "observation_count": 1,
            "timestamp": time.time(),
            "ttl": 1,
        }]
        success = await cc.inject_patterns(test_patterns)
        print(f"Pattern injection: {'✅ Success' if success else '❌ Failed'}")


if __name__ == "__main__":
    asyncio.run(cli_main())
