"""
Discord Reporter — Sends swarm intelligence reports to Discord.

Uses a webhook to push:
- Periodic health checks
- Node online/offline alerts
- Cross-domain cascade notifications
- Daily intelligence summaries
- System events

Can run as a standalone scheduled job or be called from the command center.
"""

import asyncio
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from control import CommandCenter

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def send_discord_message(content: str = None, embeds: List[dict] = None):
    """Send a message to Discord via webhook."""
    import subprocess

    payload = {}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds

    data = json.dumps(payload)

    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "-X", "POST", "-H", "Content-Type: application/json",
             "-d", data, WEBHOOK_URL],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() == "204"
    except Exception as e:
        print(f"Discord send failed: {e}")
        return False


def build_status_embed(state) -> dict:
    """Build a Discord embed from system state."""
    broker_status = "🟢 Online" if state.broker_online else "🔴 Offline"
    uptime_hours = state.uptime_seconds / 3600

    # Node list
    node_lines = []
    for node_id, node in state.nodes.items():
        domain = node.get("domain", "?")
        hb_ago = node.get("last_heartbeat_ago", 999)
        status = "🟢" if hb_ago < 120 else "🟡" if hb_ago < 300 else "🔴"
        p_sent = node.get("patterns_sent", 0)
        p_recv = node.get("patterns_received", 0)
        node_lines.append(f"{status} **{node_id}** — {domain} (sent={p_sent}, recv={p_recv})")

    if not node_lines:
        node_lines = ["No nodes connected"]

    return {
        "title": "🧠 DVCE Swarm — Status Report",
        "color": 0x00FF88 if state.broker_online else 0xFF4444,
        "fields": [
            {"name": "Broker", "value": broker_status, "inline": True},
            {"name": "Uptime", "value": f"{uptime_hours:.1f}h", "inline": True},
            {"name": "Pattern Pool", "value": str(state.pattern_pool_size), "inline": True},
            {"name": "Patterns Relayed", "value": str(state.total_patterns_relayed), "inline": True},
            {"name": "Nodes", "value": "\n".join(node_lines), "inline": False},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "DVCE Intelligence Layer"},
    }


def build_cascade_embed(pattern: dict) -> dict:
    """Build an alert embed for a cross-domain cascade."""
    sequence = " → ".join(pattern.get("sequence", []))
    confidence = pattern.get("confidence", 0)
    source = pattern.get("source_node", "unknown")

    return {
        "title": "⚠️ Cross-Domain Cascade Detected",
        "color": 0xFF8800,
        "description": f"A multi-domain event cascade was detected by the swarm.",
        "fields": [
            {"name": "Cascade", "value": f"`{sequence}`", "inline": False},
            {"name": "Confidence", "value": f"{confidence:.0%}", "inline": True},
            {"name": "Source", "value": source, "inline": True},
            {"name": "Domain", "value": pattern.get("source_domain", "?"), "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "DVCE Early Warning System"},
    }


def build_node_event_embed(node_id: str, event: str, details: str = "") -> dict:
    """Build an embed for node online/offline events."""
    color = 0x00FF88 if event == "online" else 0xFF4444
    emoji = "🟢" if event == "online" else "🔴"

    return {
        "title": f"{emoji} Node {event.title()}: {node_id}",
        "color": color,
        "description": details or f"Node **{node_id}** is now {event}.",
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "DVCE Swarm Network"},
    }


# ============================================================================
# REPORT COMMANDS
# ============================================================================

async def send_status_report():
    """Send a full status report to Discord."""
    cc = CommandCenter()
    state = await cc.get_status()
    embed = build_status_embed(state)
    success = send_discord_message(embeds=[embed])
    return success


async def send_cascade_alert(pattern: dict):
    """Send a cascade alert to Discord."""
    embed = build_cascade_embed(pattern)
    return send_discord_message(embeds=[embed])


async def send_node_event(node_id: str, event: str, details: str = ""):
    """Send a node online/offline notification."""
    embed = build_node_event_embed(node_id, event, details)
    return send_discord_message(embeds=[embed])


async def send_daily_summary():
    """Send a daily intelligence summary."""
    cc = CommandCenter()
    state = await cc.get_status()

    nodes_online = sum(1 for n in state.nodes.values() if n.get("last_heartbeat_ago", 999) < 300)
    total_nodes = len(state.nodes)

    embed = {
        "title": "📊 DVCE Daily Intelligence Summary",
        "color": 0x5865F2,
        "fields": [
            {"name": "Nodes Active", "value": f"{nodes_online}/{total_nodes}", "inline": True},
            {"name": "Patterns in Pool", "value": str(state.pattern_pool_size), "inline": True},
            {"name": "Total Relayed", "value": str(state.total_patterns_relayed), "inline": True},
            {"name": "Broker Uptime", "value": f"{state.uptime_seconds/3600:.1f} hours", "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "Daily report from DVCE Intelligence Layer"},
    }

    return send_discord_message(embeds=[embed])


# ============================================================================
# CLI
# ============================================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="DVCE Discord Reporter")
    parser.add_argument("command", choices=["status", "daily", "test", "cascade"],
                        help="Report to send")
    args = parser.parse_args()

    if args.command == "status":
        success = await send_status_report()
        print(f"Status report: {'✅ Sent' if success else '❌ Failed'}")

    elif args.command == "daily":
        success = await send_daily_summary()
        print(f"Daily summary: {'✅ Sent' if success else '❌ Failed'}")

    elif args.command == "test":
        success = send_discord_message(
            embeds=[{
                "title": "🧪 DVCE Swarm — Connection Test",
                "color": 0x5865F2,
                "description": "Discord webhook is working. The intelligence layer can now send you reports.",
                "fields": [
                    {"name": "Source", "value": "Command Center", "inline": True},
                    {"name": "Time", "value": datetime.now().strftime("%H:%M:%S"), "inline": True},
                ],
                "footer": {"text": "DVCE Intelligence Layer"},
            }]
        )
        print(f"Test message: {'✅ Sent' if success else '❌ Failed'}")

    elif args.command == "cascade":
        # Demo cascade alert
        success = await send_cascade_alert({
            "sequence": ["weather_hurricane", "weather_flooding", "weather_power_outage", "cyber_service_outage"],
            "confidence": 0.72,
            "source_node": "swarm-emergence",
            "source_domain": "cross_domain",
        })
        print(f"Cascade alert: {'✅ Sent' if success else '❌ Failed'}")


if __name__ == "__main__":
    asyncio.run(main())
