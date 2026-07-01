"""Simulated Swarm Node — for scale testing.

Connects to the broker, sends synthetic patterns at a configurable rate,
receives patterns from other nodes, and logs statistics.

Env vars:
    NODE_ID: unique identifier for this node
    NODE_DOMAIN: domain this node specializes in (financial, weather, geo, cyber, grid)
    BROKER_HOST: broker hostname (default: localhost)
    BROKER_PORT: broker port (default: 9876)
    PATTERN_RATE: patterns to generate per 10 seconds (default: 5)
    TEST_DURATION: seconds to run before reporting stats (default: 120)
"""

import asyncio
import json
import os
import random
import time
import logging
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(os.environ.get("NODE_ID", "sim-node"))

# Config from env
NODE_ID = os.environ.get("NODE_ID", f"sim-node-{random.randint(1000,9999)}")
DOMAIN = os.environ.get("NODE_DOMAIN", "financial")
BROKER_HOST = os.environ.get("BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("BROKER_PORT", "9876"))
PATTERN_RATE = int(os.environ.get("PATTERN_RATE", "5"))
TEST_DURATION = int(os.environ.get("TEST_DURATION", "120"))

# Domain-specific event types for realistic pattern generation
DOMAIN_EVENTS = {
    "financial": [
        "market_surge_5min", "market_drop_1min", "treasury_rate_change",
        "crypto_surge_btc", "economic_event_us", "trade_volume_surge",
        "fed_announcement", "earnings_surprise", "ipo_pricing",
    ],
    "weather": [
        "extreme_heat_observed", "high_wind_observed", "heavy_precipitation",
        "pressure_drop_detected", "nws_alert_tornado_warning", "flood_warning",
        "winter_storm", "hurricane_advisory", "heat_dome",
    ],
    "geo": [
        "earthquake_M5.0", "earthquake_M6.2", "fema_disaster_dr",
        "volcanic_activity", "tsunami_warning", "landslide_detected",
        "drought_worsening", "wildfire_expanding",
    ],
    "cyber": [
        "cve_published_critical", "ransomware_campaign", "ddos_detected",
        "data_breach_reported", "zero_day_exploit", "phishing_surge",
        "infrastructure_compromise", "apt_campaign_detected",
    ],
    "grid": [
        "solar_flare_M5", "grid_carbon_intensity", "transformer_failure",
        "demand_spike", "frequency_deviation", "blackout_partial",
        "generation_shortfall", "interconnector_trip",
    ],
}

# Stats
stats = {
    "patterns_sent": 0,
    "patterns_received": 0,
    "bytes_sent": 0,
    "bytes_received": 0,
    "errors": 0,
    "reconnects": 0,
    "start_time": 0,
}


def generate_pattern() -> dict:
    """Generate a synthetic pattern that looks like a real swarm event."""
    event_types = DOMAIN_EVENTS.get(DOMAIN, DOMAIN_EVENTS["financial"])
    return {
        "event_type": random.choice(event_types),
        "timestamp": time.time(),
        "severity_score": round(random.uniform(0.1, 0.95), 3),
        "domain": DOMAIN,
        "source": NODE_ID,
        "confidence": round(random.uniform(0.3, 0.9), 2),
        "ttl": 7,  # days
        "metadata": {
            "synthetic": True,
            "test_node": NODE_ID,
        },
    }


async def run_node():
    """Main node loop — connect, send, receive."""
    stats["start_time"] = time.time()
    logger.info(f"Starting simulated node: {NODE_ID} (domain={DOMAIN})")
    logger.info(f"Broker: {BROKER_HOST}:{BROKER_PORT}")
    logger.info(f"Pattern rate: {PATTERN_RATE} per 10s")
    logger.info(f"Test duration: {TEST_DURATION}s")

    while True:
        try:
            reader, writer = await asyncio.open_connection(BROKER_HOST, BROKER_PORT)
            logger.info(f"Connected to broker")

            # Register
            register_msg = json.dumps({
                "type": "register",
                "node_id": NODE_ID,
                "domain": DOMAIN,
                "expertise_scores": {DOMAIN: round(random.uniform(0.6, 0.95), 2)},
            }) + "\n"
            writer.write(register_msg.encode())
            await writer.drain()

            # Read registration ack
            ack_data = await asyncio.wait_for(reader.readline(), timeout=5)
            if ack_data:
                ack = json.loads(ack_data.decode().strip())
                swarm_size = ack.get("swarm_size", 0)
                logger.info(f"Registered! Swarm size: {swarm_size}")

            # Run send + receive concurrently
            await asyncio.gather(
                _send_loop(writer),
                _receive_loop(reader),
                _heartbeat_loop(writer),
                _status_loop(),
            )

        except (ConnectionRefusedError, OSError) as e:
            stats["reconnects"] += 1
            logger.warning(f"Connection failed: {e}. Retrying in 3s...")
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            break
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Unexpected error: {e}. Retrying in 5s...")
            await asyncio.sleep(5)


async def _send_loop(writer: asyncio.StreamWriter):
    """Generate and send patterns at the configured rate."""
    while True:
        # Generate batch
        batch_size = max(1, PATTERN_RATE)
        patterns = [generate_pattern() for _ in range(batch_size)]

        msg = json.dumps({
            "type": "patterns",
            "source_node": NODE_ID,
            "patterns": patterns,
        }) + "\n"

        try:
            writer.write(msg.encode())
            await writer.drain()
            stats["patterns_sent"] += len(patterns)
            stats["bytes_sent"] += len(msg)
        except Exception:
            raise

        # Sleep to maintain rate (PATTERN_RATE per 10s)
        await asyncio.sleep(10)


async def _receive_loop(reader: asyncio.StreamReader):
    """Receive patterns from the broker."""
    while True:
        data = await reader.readline()
        if not data:
            raise ConnectionError("Broker disconnected")

        try:
            msg = json.loads(data.decode().strip())
            if msg.get("type") == "patterns":
                patterns = msg.get("patterns", [])
                stats["patterns_received"] += len(patterns)
                stats["bytes_received"] += len(data)

                # Log cross-domain patterns (the interesting ones)
                for p in patterns[:3]:
                    if p.get("domain") != DOMAIN:
                        logger.info(
                            f"  ← Cross-domain pattern: {p.get('event_type')} "
                            f"from {p.get('domain')} (sev={p.get('severity_score')})"
                        )
        except json.JSONDecodeError:
            pass


async def _heartbeat_loop(writer: asyncio.StreamWriter):
    """Send heartbeat every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        msg = json.dumps({
            "type": "heartbeat",
            "node_id": NODE_ID,
            "expertise_scores": {DOMAIN: round(random.uniform(0.6, 0.95), 2)},
        }) + "\n"
        writer.write(msg.encode())
        await writer.drain()


async def _status_loop():
    """Print stats periodically and exit after TEST_DURATION."""
    while True:
        await asyncio.sleep(15)
        elapsed = time.time() - stats["start_time"]
        logger.info(
            f"[{int(elapsed)}s] sent={stats['patterns_sent']} "
            f"recv={stats['patterns_received']} "
            f"errors={stats['errors']} reconnects={stats['reconnects']}"
        )

        if elapsed >= TEST_DURATION:
            logger.info("=" * 50)
            logger.info(f"TEST COMPLETE — {NODE_ID} ({DOMAIN})")
            logger.info(f"  Duration: {int(elapsed)}s")
            logger.info(f"  Patterns sent: {stats['patterns_sent']}")
            logger.info(f"  Patterns received: {stats['patterns_received']}")
            logger.info(f"  Bytes sent: {stats['bytes_sent']:,}")
            logger.info(f"  Bytes received: {stats['bytes_received']:,}")
            logger.info(f"  Errors: {stats['errors']}")
            logger.info(f"  Reconnects: {stats['reconnects']}")
            logger.info(f"  Rate: {stats['patterns_sent']/elapsed:.1f} patterns/s sent")
            logger.info("=" * 50)
            # Keep running (don't exit — let Docker manage lifecycle)
            # But slow down the rate after test period
            await asyncio.sleep(TEST_DURATION)


if __name__ == "__main__":
    asyncio.run(run_node())
