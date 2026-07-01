"""Finnhub WebSocket Feed — Real-time market tick data.

Replaces daily REST polling with a persistent WebSocket connection to Finnhub.
Streams real-time trades for key symbols and converts significant moves into
swarm events that get fed to the broker immediately.

This gives the swarm sub-second awareness of market movements instead of
waiting for the next daily pull cycle.

Architecture:
    Finnhub WS → FinnhubRealtimeFeed → event detection → broker TCP/NATS

Symbols tracked:
    - SPY (S&P 500 ETF — overall market)
    - QQQ (Nasdaq 100 — tech sector)
    - USO (Oil ETF — energy/shipping)
    - GLD (Gold ETF — safe haven)
    - TLT (20yr Treasury — rates)
    - AAPL, TSLA, NVDA (mega caps)
    - BINANCE:BTCUSDT (crypto)

Event detection:
    - Price spike/drop >1% in 5min window → high severity
    - Price spike/drop >0.5% in 1min → medium severity
    - Volume surge (5x average) → trade_volume_surge event

Usage:
    # Run as standalone service:
    python -m src.ingestion.finnhub_ws
    
    # Or import:
    from src.ingestion.finnhub_ws import FinnhubRealtimeFeed
    feed = FinnhubRealtimeFeed(api_key="...")
    await feed.start()

Launchd/systemd: runs as a persistent background service alongside the broker.
"""

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
KEYS_FILE = BASE_DIR / ".keys.json"
EVENTS_DIR = BASE_DIR / "data" / "live_feeds" / "realtime"

# Symbols to subscribe
SYMBOLS = [
    "SPY", "QQQ", "USO", "GLD", "TLT",
    "AAPL", "TSLA", "NVDA", "AMZN",
    "BINANCE:BTCUSDT",
]

# How often to check for significant moves (seconds)
CHECK_INTERVAL = 5.0

# Thresholds for event generation
THRESHOLDS = {
    "spike_1min_pct": 0.5,    # >0.5% in 1 min
    "spike_5min_pct": 1.0,    # >1.0% in 5 min  
    "volume_surge_mult": 5.0,  # 5x normal volume in window
}


@dataclass
class TickWindow:
    """Sliding window of recent ticks for a symbol."""
    symbol: str
    prices: deque = field(default_factory=lambda: deque(maxlen=600))  # ~10min of ticks
    volumes: deque = field(default_factory=lambda: deque(maxlen=600))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=600))
    last_event_time: float = 0.0
    baseline_volume: float = 0.0  # Running average volume per tick
    
    def add_tick(self, price: float, volume: float, ts: float):
        self.prices.append(price)
        self.volumes.append(volume)
        self.timestamps.append(ts)
        # Update baseline volume (exponential moving average)
        if self.baseline_volume == 0:
            self.baseline_volume = volume
        else:
            self.baseline_volume = 0.99 * self.baseline_volume + 0.01 * volume

    @property
    def current_price(self) -> Optional[float]:
        return self.prices[-1] if self.prices else None

    def price_at(self, seconds_ago: float) -> Optional[float]:
        """Get price from approximately N seconds ago."""
        if not self.timestamps:
            return None
        target = time.time() - seconds_ago
        for i in range(len(self.timestamps) - 1, -1, -1):
            if self.timestamps[i] <= target:
                return self.prices[i]
        return self.prices[0] if self.prices else None

    def volume_in_window(self, seconds: float) -> float:
        """Total volume in the last N seconds."""
        cutoff = time.time() - seconds
        total = 0.0
        for i in range(len(self.timestamps) - 1, -1, -1):
            if self.timestamps[i] < cutoff:
                break
            total += self.volumes[i]
        return total

    def pct_change(self, seconds: float) -> Optional[float]:
        """Percentage price change over last N seconds."""
        current = self.current_price
        past = self.price_at(seconds)
        if current is None or past is None or past == 0:
            return None
        return ((current - past) / past) * 100


class FinnhubRealtimeFeed:
    """Persistent WebSocket connection to Finnhub for real-time market data.
    
    Detects significant price moves and volume surges, converts them to
    swarm events, and optionally pushes to the pattern broker.
    """

    WS_URL = "wss://ws.finnhub.io?token={key}"

    def __init__(
        self,
        api_key: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        broker_host: str = "127.0.0.1",
        broker_port: int = 9876,
    ):
        self.api_key = api_key or self._load_key()
        self.symbols = symbols or SYMBOLS
        self.on_event = on_event
        self.broker_host = broker_host
        self.broker_port = broker_port

        # Tick windows per symbol
        self.windows: Dict[str, TickWindow] = {s: TickWindow(symbol=s) for s in self.symbols}

        # Stats
        self.stats = {
            "ticks_received": 0,
            "events_generated": 0,
            "reconnects": 0,
            "start_time": 0,
            "last_tick_time": 0,
        }

        # Event buffer for batch sending to broker
        self._event_buffer: List[Dict[str, Any]] = []
        self._running = False

    def _load_key(self) -> str:
        """Load Finnhub API key from .keys.json."""
        if KEYS_FILE.exists():
            keys = json.loads(KEYS_FILE.read_text())
            return keys.get("finnhub", "")
        return ""

    async def start(self):
        """Start the WebSocket feed with auto-reconnect."""
        if not self.api_key:
            logger.error("No Finnhub API key available. Cannot start WebSocket feed.")
            return

        self._running = True
        self.stats["start_time"] = time.time()

        # Start event detection loop
        asyncio.create_task(self._detection_loop())
        # Start broker flush loop
        asyncio.create_task(self._broker_flush_loop())

        # WebSocket connection with auto-reconnect
        while self._running:
            try:
                await self._connect_and_stream()
            except Exception as e:
                logger.warning(f"WebSocket error: {e}. Reconnecting in 5s...")
                self.stats["reconnects"] += 1
                await asyncio.sleep(5)

    async def stop(self):
        """Stop the feed."""
        self._running = False

    async def _connect_and_stream(self):
        """Connect to Finnhub WS and stream ticks."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Run: pip install websockets")
            self._running = False
            return

        url = self.WS_URL.format(key=self.api_key)
        logger.info(f"Connecting to Finnhub WebSocket...")

        async with websockets.connect(url, ping_interval=30) as ws:
            # Subscribe to all symbols
            for symbol in self.symbols:
                sub_msg = json.dumps({"type": "subscribe", "symbol": symbol})
                await ws.send(sub_msg)
                logger.info(f"  Subscribed: {symbol}")

            logger.info(f"✅ Finnhub WebSocket connected. Streaming {len(self.symbols)} symbols.")

            # Receive loop
            async for message in ws:
                if not self._running:
                    break

                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "trade":
                        trades = data.get("data", [])
                        for trade in trades:
                            symbol = trade.get("s", "")
                            price = trade.get("p", 0)
                            volume = trade.get("v", 0)
                            ts = trade.get("t", 0) / 1000  # ms → s

                            if symbol in self.windows:
                                self.windows[symbol].add_tick(price, volume, ts)
                                self.stats["ticks_received"] += 1
                                self.stats["last_tick_time"] = time.time()

                    elif msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong"}))

                except json.JSONDecodeError:
                    continue

    async def _detection_loop(self):
        """Periodically check tick windows for significant events."""
        while self._running:
            await asyncio.sleep(CHECK_INTERVAL)

            now = time.time()
            for symbol, window in self.windows.items():
                if not window.prices:
                    continue

                # Check 1-minute move
                pct_1m = window.pct_change(60)
                if pct_1m is not None and abs(pct_1m) >= THRESHOLDS["spike_1min_pct"]:
                    # Don't fire events more than once per 60s per symbol
                    if now - window.last_event_time > 60:
                        direction = "surge" if pct_1m > 0 else "drop"
                        severity = min(1.0, abs(pct_1m) / 3.0)
                        self._emit_event({
                            "event_type": f"market_{direction}_1min",
                            "timestamp": now,
                            "severity_score": round(severity, 3),
                            "domain": "financial",
                            "source": "finnhub_realtime",
                            "metadata": {
                                "symbol": symbol,
                                "pct_change_1min": round(pct_1m, 3),
                                "price": window.current_price,
                                "window": "1min",
                            },
                        })
                        window.last_event_time = now

                # Check 5-minute move
                pct_5m = window.pct_change(300)
                if pct_5m is not None and abs(pct_5m) >= THRESHOLDS["spike_5min_pct"]:
                    if now - window.last_event_time > 60:
                        direction = "surge" if pct_5m > 0 else "drop"
                        severity = min(1.0, abs(pct_5m) / 5.0)
                        self._emit_event({
                            "event_type": f"market_{direction}_5min",
                            "timestamp": now,
                            "severity_score": round(severity, 3),
                            "domain": "financial",
                            "source": "finnhub_realtime",
                            "metadata": {
                                "symbol": symbol,
                                "pct_change_5min": round(pct_5m, 3),
                                "price": window.current_price,
                                "window": "5min",
                            },
                        })
                        window.last_event_time = now

                # Check volume surge
                if window.baseline_volume > 0:
                    recent_vol = window.volume_in_window(60)
                    expected_vol = window.baseline_volume * 60  # Expected in 1 min
                    if expected_vol > 0 and recent_vol / expected_vol > THRESHOLDS["volume_surge_mult"]:
                        if now - window.last_event_time > 120:
                            severity = min(1.0, (recent_vol / expected_vol) / 10.0)
                            self._emit_event({
                                "event_type": "trade_volume_surge",
                                "timestamp": now,
                                "severity_score": round(severity, 3),
                                "domain": "financial",
                                "source": "finnhub_realtime",
                                "metadata": {
                                    "symbol": symbol,
                                    "volume_multiplier": round(recent_vol / expected_vol, 1),
                                    "price": window.current_price,
                                },
                            })
                            window.last_event_time = now

    def _emit_event(self, event: Dict[str, Any]):
        """Emit a detected market event."""
        self._event_buffer.append(event)
        self.stats["events_generated"] += 1
        logger.info(
            f"⚡ EVENT: {event['event_type']} | {event['metadata'].get('symbol', '?')} | "
            f"severity={event['severity_score']}"
        )

        # Save to disk for offline analysis
        EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        events_file = EVENTS_DIR / "finnhub_realtime_events.jsonl"
        with open(events_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        # Callback if registered
        if self.on_event:
            self.on_event(event)

    async def _broker_flush_loop(self):
        """Send buffered events to the swarm broker every 10 seconds."""
        while self._running:
            await asyncio.sleep(10)
            if not self._event_buffer:
                continue

            events_to_send = self._event_buffer[:]
            self._event_buffer.clear()

            try:
                reader, writer = await asyncio.open_connection(
                    self.broker_host, self.broker_port
                )
                msg = json.dumps({
                    "type": "patterns",
                    "source_node": "finnhub_realtime",
                    "patterns": events_to_send,
                }) + "\n"
                writer.write(msg.encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                logger.debug(f"Flushed {len(events_to_send)} events to broker")
            except (ConnectionRefusedError, OSError) as e:
                logger.debug(f"Broker not reachable for flush: {e}")
                # Events already saved to disk, so not lost

    def get_status(self) -> Dict[str, Any]:
        """Get current feed status."""
        uptime = time.time() - self.stats["start_time"] if self.stats["start_time"] else 0
        return {
            "running": self._running,
            "uptime_seconds": int(uptime),
            "ticks_received": self.stats["ticks_received"],
            "events_generated": self.stats["events_generated"],
            "reconnects": self.stats["reconnects"],
            "symbols_active": sum(1 for w in self.windows.values() if w.prices),
            "symbols_subscribed": len(self.symbols),
            "last_tick_ago": (
                round(time.time() - self.stats["last_tick_time"], 1)
                if self.stats["last_tick_time"] else None
            ),
        }


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info("=" * 60)
    logger.info("FINNHUB REALTIME WEBSOCKET FEED")
    logger.info("=" * 60)

    feed = FinnhubRealtimeFeed()

    if not feed.api_key:
        logger.error("No Finnhub API key found in .keys.json")
        return

    logger.info(f"Symbols: {', '.join(feed.symbols)}")
    logger.info(f"Thresholds: {THRESHOLDS}")
    logger.info(f"Broker: {feed.broker_host}:{feed.broker_port}")
    logger.info("")

    try:
        asyncio.run(feed.start())
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
