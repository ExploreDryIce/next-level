"""Overnight Training — Feed all pulled data to the swarm for learning.

This script:
1. Converts all overnight data into event sequences
2. Feeds them to the broker for pattern distribution
3. Trains/retrains the weather specialist with 72-city US data
4. Trains/retrains the financial specialist with full market data
5. Extracts cross-domain patterns
6. Pushes patterns to TerrorNode via broker (if online)

Run before bed. Wake up smarter.

Usage:
    /Users/webber/Desktop/dvce/.venv/bin/python scripts/overnight_train.py
"""

import json
import time
import logging
import sys
import socket
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
OVERNIGHT_DIR = DATA_DIR / "overnight_pull" / datetime.now().strftime("%Y-%m-%d")
WEATHER_DIR = OVERNIGHT_DIR / "weather_us_full"
CHECKPOINTS_DIR = BASE_DIR / "experiments" / "checkpoints"


def load_weather_sequences() -> List[List[Dict[str, Any]]]:
    """Convert 72-city weather data into training sequences."""
    sequences = []
    
    if not WEATHER_DIR.exists():
        logger.warning(f"No weather data at {WEATHER_DIR}")
        return sequences
    
    for city_file in WEATHER_DIR.glob("*.json"):
        if city_file.stem.startswith(("air_", "flood_", "nws_")):
            continue
            
        try:
            data = json.loads(city_file.read_text())
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            precip = hourly.get("precipitation", [])
            wind = hourly.get("windspeed_10m", [])
            codes = hourly.get("weathercode", [])
            
            city = city_file.stem
            seq = []
            
            for i in range(len(times)):
                temp = temps[i] if i < len(temps) else 20
                rain = precip[i] if i < len(precip) else 0
                wspd = wind[i] if i < len(wind) else 0
                code = codes[i] if i < len(codes) else 0
                
                # Convert to events based on thresholds
                if rain and rain > 10:
                    seq.append({"event_type": "heavy_rain", "timestamp": float(i), "severity_score": min(1.0, rain/30)})
                elif rain and rain > 2:
                    seq.append({"event_type": "moderate_rain", "timestamp": float(i), "severity_score": rain/20})
                
                if wspd and wspd > 50:
                    seq.append({"event_type": "high_wind", "timestamp": float(i), "severity_score": min(1.0, wspd/100)})
                
                if temp and temp > 38:
                    seq.append({"event_type": "extreme_heat", "timestamp": float(i), "severity_score": min(1.0, (temp-35)/10)})
                elif temp and temp < -10:
                    seq.append({"event_type": "extreme_cold", "timestamp": float(i), "severity_score": min(1.0, (-10-temp)/20)})
                
                # Weather codes: 95+ = thunderstorm, 71-77 = snow, 51-67 = drizzle/rain
                if code and code >= 95:
                    seq.append({"event_type": "thunderstorm", "timestamp": float(i), "severity_score": 0.8})
                elif code and 71 <= code <= 77:
                    seq.append({"event_type": "snow_event", "timestamp": float(i), "severity_score": 0.5})
            
            if seq:
                sequences.append(seq)
                
        except Exception as e:
            continue
    
    # Also load NWS alerts as sequences
    alerts_dir = WEATHER_DIR / "nws_alerts"
    if alerts_dir.exists():
        for alert_file in alerts_dir.glob("*.json"):
            try:
                data = json.loads(alert_file.read_text())
                features = data.get("features", [])
                seq = []
                for feature in features:
                    props = feature.get("properties", {})
                    event = props.get("event", "unknown")
                    severity = props.get("severity", "Unknown")
                    sev_map = {"Extreme": 1.0, "Severe": 0.8, "Moderate": 0.5, "Minor": 0.3}
                    seq.append({
                        "event_type": f"alert_{event.lower().replace(' ','_')}",
                        "timestamp": time.time(),
                        "severity_score": sev_map.get(severity, 0.4),
                    })
                if seq:
                    sequences.append(seq)
            except:
                continue
    
    return sequences


def load_financial_sequences() -> List[List[Dict[str, Any]]]:
    """Convert financial data into training sequences."""
    sequences = []
    feeds_dir = DATA_DIR / "live_feeds"
    
    # Finnhub economic calendar → event sequences
    econ_file = feeds_dir / "finnhub_economic_calendar.json"
    if econ_file.exists():
        try:
            data = json.loads(econ_file.read_text())
            calendar = data.get("economicCalendar", [])
            
            # Group by country for sequences
            by_country: Dict[str, list] = {}
            for item in calendar:
                country = item.get("country", "US")
                by_country.setdefault(country, []).append(item)
            
            for country, events in by_country.items():
                seq = []
                for e in events[:50]:
                    impact = e.get("impact", "low")
                    sev = {"high": 0.8, "medium": 0.5, "low": 0.2}.get(impact, 0.3)
                    seq.append({
                        "event_type": f"economic_{e.get('event','unknown')[:30].lower().replace(' ','_')}",
                        "timestamp": time.time(),
                        "severity_score": sev,
                    })
                if len(seq) >= 3:
                    sequences.append(seq)
        except:
            pass
    
    # Market news headlines → sentiment sequences
    for news_file in feeds_dir.glob("finnhub_*_news.json"):
        try:
            data = json.loads(news_file.read_text())
            if isinstance(data, list):
                seq = []
                for article in data[:30]:
                    headline = article.get("headline", "").lower()
                    # Simple sentiment scoring
                    sev = 0.3
                    if any(w in headline for w in ["crash", "plunge", "crisis", "default", "collapse"]):
                        sev = 0.9
                    elif any(w in headline for w in ["surge", "rally", "boom", "record"]):
                        sev = 0.7
                    elif any(w in headline for w in ["fed", "rate", "inflation", "gdp"]):
                        sev = 0.6
                    
                    seq.append({
                        "event_type": f"market_news",
                        "timestamp": float(article.get("datetime", time.time())),
                        "severity_score": sev,
                    })
                if len(seq) >= 5:
                    sequences.append(seq)
        except:
            continue
    
    # FRED macro data → trend sequences
    for fred_file in feeds_dir.glob("fred_*.json"):
        try:
            data = json.loads(fred_file.read_text())
            observations = data.get("observations", [])
            seq = []
            prev_val = None
            for obs in observations[:30]:
                val = obs.get("value", ".")
                if val == ".":
                    continue
                val = float(val)
                if prev_val is not None:
                    change = (val - prev_val) / max(abs(prev_val), 0.01)
                    if abs(change) > 0.01:  # 1%+ change
                        direction = "increase" if change > 0 else "decrease"
                        seq.append({
                            "event_type": f"macro_{fred_file.stem.replace('fred_','')}_{direction}",
                            "timestamp": time.time(),
                            "severity_score": min(1.0, abs(change) * 5),
                        })
                prev_val = val
            if len(seq) >= 3:
                sequences.append(seq)
        except:
            continue
    
    return sequences


def train_model(sequences: List[List[Dict]], domain: str, vocab: Dict[str, int], 
                epochs: int = 30, model_dim: int = 128):
    """Train a domain specialist model on event sequences."""
    
    if not sequences:
        logger.warning(f"No sequences for {domain}, skipping")
        return None
    
    logger.info(f"Training {domain} specialist: {len(sequences)} sequences, {len(vocab)} vocab, {epochs} epochs")
    
    # Import model architecture from DVCE
    sys.path.insert(0, "/Users/webber/Desktop/dvce/src")
    from dvce.services.event_prediction.torch_model import EventTransformerTorch, TorchModelConfig
    
    config = TorchModelConfig(
        vocab_size=len(vocab),
        context_dim=32,
        d_model=model_dim,
        n_heads=4,
        n_layers=3,
        d_ff=model_dim * 4,
        dropout=0.1,
        max_seq_len=64,
        time_encoding_dim=24,
    )
    
    model = EventTransformerTorch(config)
    
    # Device selection
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")
    
    model = model.to(device)
    logger.info(f"  Device: {device}, Params: {sum(p.numel() for p in model.parameters()):,}")
    
    # Prepare data
    all_tokens = []
    all_times = []
    all_sevs = []
    
    for seq in sequences:
        tokens = []
        times = []
        sevs = []
        prev_ts = 0
        for event in seq[:64]:
            etype = event.get("event_type", "<UNK>")
            tid = vocab.get(etype, vocab.get("<UNK>", 0))
            tokens.append(tid)
            ts = float(event.get("timestamp", 0))
            times.append(ts - prev_ts)
            prev_ts = ts
            sevs.append(float(event.get("severity_score", 0.5)))
        
        if len(tokens) >= 3:
            all_tokens.append(tokens)
            all_times.append(times)
            all_sevs.append(sevs)
    
    if not all_tokens:
        logger.warning(f"  No valid sequences after tokenization")
        return None
    
    n_samples = len(all_tokens)
    logger.info(f"  Valid samples: {n_samples}")
    
    # Train
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    batch_size = min(64, n_samples)
    best_loss = float("inf")
    
    start = time.time()
    
    for epoch in range(epochs):
        model.train()
        epoch_loss = 0
        n_batches = 0
        indices = np.random.permutation(n_samples)
        
        for batch_start in range(0, min(n_samples, 5000), batch_size):
            batch_idx = indices[batch_start:batch_start + batch_size]
            max_len = max(len(all_tokens[i]) for i in batch_idx)
            
            token_batch = torch.zeros(len(batch_idx), max_len, dtype=torch.long)
            time_batch = torch.zeros(len(batch_idx), max_len)
            sev_batch = torch.zeros(len(batch_idx), max_len)
            ctx_batch = torch.zeros(len(batch_idx), max_len, config.context_dim)
            mask_batch = torch.zeros(len(batch_idx), max_len)
            
            for bi, si in enumerate(batch_idx):
                sl = len(all_tokens[si])
                token_batch[bi, :sl] = torch.tensor(all_tokens[si])
                time_batch[bi, :sl] = torch.tensor(all_times[si])
                sev_batch[bi, :sl] = torch.tensor(all_sevs[si])
                mask_batch[bi, :sl] = 1.0
            
            token_batch = token_batch.to(device)
            time_batch = time_batch.to(device)
            sev_batch = sev_batch.to(device)
            ctx_batch = ctx_batch.to(device)
            mask_batch = mask_batch.to(device)
            
            outputs = model(token_batch, time_batch, sev_batch, ctx_batch, mask_batch)
            logits = outputs["type_logits"][:, :-1, :]
            targets = token_batch[:, 1:]
            target_mask = mask_batch[:, 1:]
            
            loss = torch.nn.functional.cross_entropy(
                logits.reshape(-1, len(vocab)), targets.reshape(-1), reduction="none"
            )
            loss = (loss * target_mask.reshape(-1)).sum() / target_mask.sum()
            
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            epoch_loss += loss.item()
            n_batches += 1
        
        scheduler.step()
        avg_loss = epoch_loss / max(n_batches, 1)
        if avg_loss < best_loss:
            best_loss = avg_loss
        
        if (epoch + 1) % 10 == 0:
            logger.info(f"  Epoch {epoch+1}/{epochs} | Loss: {avg_loss:.4f} | Best: {best_loss:.4f}")
    
    elapsed = time.time() - start
    logger.info(f"  Training complete: {elapsed:.0f}s, best loss: {best_loss:.4f}")
    
    # Save checkpoint
    ckpt_dir = CHECKPOINTS_DIR / f"{domain}_overnight"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    
    torch.save({
        "model_state_dict": model.state_dict(),
        "config": {
            "vocab_size": config.vocab_size,
            "context_dim": config.context_dim,
            "d_model": config.d_model,
            "n_heads": config.n_heads,
            "n_layers": config.n_layers,
            "d_ff": config.d_ff,
            "max_seq_len": config.max_seq_len,
            "time_encoding_dim": config.time_encoding_dim,
        },
        "best_loss": best_loss,
        "epochs": epochs,
        "samples": n_samples,
        "domain": domain,
        "trained_at": datetime.now().isoformat(),
    }, ckpt_dir / "best_model.pt")
    
    with open(ckpt_dir / "vocab.json", "w") as f:
        json.dump(vocab, f, indent=2)
    
    logger.info(f"  Saved: {ckpt_dir}")
    return best_loss


def push_to_broker(events: List[Dict], broker_host: str = "127.0.0.1", broker_port: int = 9876):
    """Push events to the swarm broker for pattern distribution."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((broker_host, broker_port))
        
        # Register
        msg = json.dumps({
            "type": "register",
            "node_id": "overnight-trainer",
            "domain": "all",
            "expertise_scores": {"weather": 0.5, "financial": 0.5, "geo": 0.5},
        }) + "\n"
        sock.sendall(msg.encode())
        sock.recv(4096)
        
        # Send patterns
        patterns = []
        for i in range(0, len(events) - 3, 3):
            window = events[i:i+4]
            if len(window) >= 3:
                pattern = {
                    "pattern_id": f"overnight_{int(time.time())}_{i}",
                    "sequence": [e["event_type"] for e in window],
                    "confidence": max(e.get("severity_score", 0.5) for e in window),
                    "source_domain": window[0].get("domain", "unknown"),
                    "source_node": "overnight-trainer",
                    "avg_time_delta": 3600,
                    "observation_count": 1,
                    "timestamp": time.time(),
                    "ttl": 7,
                }
                patterns.append(pattern)
        
        if patterns:
            msg = json.dumps({
                "type": "patterns",
                "source_node": "overnight-trainer",
                "patterns": patterns[:100],  # Cap at 100
            }) + "\n"
            sock.sendall(msg.encode())
            logger.info(f"  Pushed {min(len(patterns), 100)} patterns to broker")
        
        sock.close()
        return True
    except Exception as e:
        logger.warning(f"  Broker not reachable: {e}")
        return False


def main():
    logger.info("=" * 70)
    logger.info("🌙 OVERNIGHT TRAINING — ALL DOMAINS")
    logger.info("=" * 70)
    logger.info(f"Data dir: {OVERNIGHT_DIR}")
    logger.info(f"Device: {'CUDA' if torch.cuda.is_available() else 'MPS' if torch.backends.mps.is_available() else 'CPU'}")
    logger.info("")
    
    total_start = time.time()
    
    # === WEATHER SPECIALIST ===
    logger.info("━" * 50)
    logger.info("WEATHER SPECIALIST")
    logger.info("━" * 50)
    
    weather_seqs = load_weather_sequences()
    logger.info(f"Weather sequences: {len(weather_seqs)}")
    
    # Build weather vocab from data
    weather_vocab = {"<PAD>": 0, "<BOS>": 1, "<EOS>": 2, "<UNK>": 3}
    for seq in weather_seqs:
        for event in seq:
            etype = event.get("event_type", "<UNK>")
            if etype not in weather_vocab:
                weather_vocab[etype] = len(weather_vocab)
    
    logger.info(f"Weather vocab: {len(weather_vocab)} types")
    
    if weather_seqs:
        train_model(weather_seqs, "weather", weather_vocab, epochs=30, model_dim=128)
    
    # === FINANCIAL SPECIALIST ===
    logger.info("")
    logger.info("━" * 50)
    logger.info("FINANCIAL SPECIALIST")
    logger.info("━" * 50)
    
    financial_seqs = load_financial_sequences()
    logger.info(f"Financial sequences: {len(financial_seqs)}")
    
    # Build financial vocab
    financial_vocab = {"<PAD>": 0, "<BOS>": 1, "<EOS>": 2, "<UNK>": 3}
    for seq in financial_seqs:
        for event in seq:
            etype = event.get("event_type", "<UNK>")
            if etype not in financial_vocab:
                financial_vocab[etype] = len(financial_vocab)
    
    logger.info(f"Financial vocab: {len(financial_vocab)} types")
    
    if financial_seqs:
        train_model(financial_seqs, "financial", financial_vocab, epochs=30, model_dim=128)
    
    # === PUSH PATTERNS TO BROKER ===
    logger.info("")
    logger.info("━" * 50)
    logger.info("PATTERN DISTRIBUTION")
    logger.info("━" * 50)
    
    # Load event sequences and push to broker
    events_file = DATA_DIR / "event_sequences" / "all_events_combined.json"
    if events_file.exists():
        events = json.loads(events_file.read_text())
        logger.info(f"Events to distribute: {len(events)}")
        push_to_broker(events)
    
    # === SUMMARY ===
    elapsed = time.time() - total_start
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"🌙 OVERNIGHT TRAINING COMPLETE — {elapsed/60:.1f} minutes")
    logger.info("=" * 70)
    logger.info(f"  Weather sequences trained: {len(weather_seqs)}")
    logger.info(f"  Financial sequences trained: {len(financial_seqs)}")
    logger.info(f"  Checkpoints saved to: {CHECKPOINTS_DIR}")
    logger.info("")
    logger.info("  TerrorNode: pull from git and load new checkpoints")
    logger.info("  Next daily pull: 6:00 AM (launchd)")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
