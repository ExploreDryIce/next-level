"""
Swarm Node — the core runtime for a DVCE prediction node.

Each node:
1. Loads a specialized model for its domain
2. Runs predictions on incoming events
3. Extracts patterns from successful predictions
4. Shares patterns with peers via the message broker
5. Incorporates foreign patterns to improve over time
6. Advertises expertise scores for routing

This is the single script that runs on every machine in the swarm,
configured differently per hardware/role.
"""

import asyncio
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

import numpy as np
import torch

from config import NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# PATTERN DATA STRUCTURES
# ============================================================================

@dataclass
class Pattern:
    """A shareable prediction pattern extracted from a node's model."""
    pattern_id: str
    sequence: List[str]        # Abstract event type sequence
    confidence: float          # Model confidence [0, 1]
    source_domain: str         # Which domain produced this
    source_node: str           # Which node produced this
    avg_time_delta: float      # Average inter-event time
    observation_count: int     # Times observed locally
    timestamp: float           # When extracted (unix)
    ttl: int = 7               # Days until expiry

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Pattern":
        return cls(**data)

    def is_expired(self) -> bool:
        age_days = (time.time() - self.timestamp) / 86400
        return age_days > self.ttl


# ============================================================================
# SWARM NODE
# ============================================================================

class SwarmNode:
    """A single node in the DVCE prediction swarm."""

    def __init__(self, config: NodeConfig):
        self.config = config
        self.model = None
        self.tokenizer = None
        self.device = None
        self.local_patterns: List[Pattern] = []
        self.foreign_patterns: List[Pattern] = []
        self.expertise_scores: Dict[str, float] = {}
        self.running = False
        self.stats = {
            "predictions_made": 0,
            "patterns_extracted": 0,
            "patterns_shared": 0,
            "patterns_received": 0,
            "uptime_start": 0,
        }

    # ─── LIFECYCLE ───

    async def start(self):
        """Initialize and start the node."""
        logger.info(f"🚀 Starting node: {self.config.node_name}")
        logger.info(f"   Domain: {self.config.domain}")
        logger.info(f"   Model size: {self.config.model_size}")

        # Detect device
        self.device = self.config.detect_device()
        logger.info(f"   Device: {self.device}")

        # Load model
        self._load_model()

        # Load any cached patterns
        self._load_cached_patterns()

        # Connect to broker
        from network import NodeNetworkClient
        self.network = NodeNetworkClient(
            node_id=self.config.node_id,
            domain=self.config.domain,
            broker_host=self.config.broker_host,
            broker_port=self.config.broker_port,
            expertise_scores=self.expertise_scores,
            on_patterns_received=self.receive_patterns,
        )

        # Start main loop
        self.running = True
        self.stats["uptime_start"] = time.time()

        logger.info(f"✅ Node {self.config.node_id} online")
        logger.info(f"   Expertise: {self.expertise_scores}")

        # Connect to broker and run
        await asyncio.gather(
            self.network.connect(),
            self._main_loop(),
        )

    async def stop(self):
        """Gracefully shut down the node."""
        self.running = False
        self._save_cached_patterns()
        logger.info(f"🛑 Node {self.config.node_id} stopped")

    # ─── MODEL ───

    def _load_model(self):
        """Load the prediction model based on config."""
        import sys
        # Add local directory to path (for remote nodes with dvce copied locally)
        local_dir = str(Path(__file__).parent)
        if local_dir not in sys.path:
            sys.path.insert(0, local_dir)

        # Also try DVCE source if on Mac
        dvce_path = Path("/Users/webber/Desktop/dvce/src")
        if dvce_path.exists() and str(dvce_path) not in sys.path:
            sys.path.insert(0, str(dvce_path))

        from dvce.services.event_prediction.torch_model import (
            EventTransformerTorch, TorchModelConfig
        )
        from dvce.services.event_prediction.tokenizer import EventTokenizer

        # Model dimensions per size
        sizes = {
            "tiny":     {"d_model": 64,  "n_heads": 2, "n_layers": 2, "d_ff": 256,  "time_dim": 16},
            "standard": {"d_model": 128, "n_heads": 4, "n_layers": 4, "d_ff": 512,  "time_dim": 32},
            "large":    {"d_model": 256, "n_heads": 8, "n_layers": 4, "d_ff": 1024, "time_dim": 64},
        }
        s = sizes[self.config.model_size]

        # Load vocab
        vocab_path = self.config.vocab_path or str(
            Path(__file__).parent.parent.parent / "experiments/models/vocab.json"
        )

        self.tokenizer = EventTokenizer(context_dim=64, max_sequence_length=256)
        if Path(vocab_path).exists():
            import json as _json
            vocab_data = _json.loads(Path(vocab_path).read_text())
            # Handle both formats: flat dict or nested {"type_to_id": {...}}
            if "type_to_id" in vocab_data:
                type_to_id = vocab_data["type_to_id"]
            else:
                type_to_id = vocab_data
            for event_type in type_to_id:
                self.tokenizer.vocabulary.encode(event_type)
            self.tokenizer.vocabulary.freeze()
            logger.info(f"   Vocabulary: {self.tokenizer.vocabulary.size} types")

        # Build model
        config = TorchModelConfig(
            vocab_size=self.tokenizer.vocabulary.size,
            context_dim=64,
            d_model=s["d_model"],
            n_heads=s["n_heads"],
            n_layers=s["n_layers"],
            d_ff=s["d_ff"],
            dropout=0.1,
            max_seq_len=256,
            time_encoding_dim=s["time_dim"],
            learning_rate=3e-4,
        )

        self.model = EventTransformerTorch(config)

        # Load checkpoint if exists
        if self.config.model_path and Path(self.config.model_path).exists():
            checkpoint = torch.load(self.config.model_path, map_location=self.device)
            self.model.load_state_dict(checkpoint["model_state_dict"])
            logger.info(f"   Loaded checkpoint: {self.config.model_path}")

        self.model.to(self.device)
        self.model.eval()

        total_params = sum(p.numel() for p in self.model.parameters())
        logger.info(f"   Model: {total_params:,} params on {self.device}")

        # Load expertise scores
        if self.config.expertise_scores:
            self.expertise_scores = self.config.expertise_scores
        else:
            self.expertise_scores = {self.config.domain: 0.5}

    # ─── PREDICTION ───

    def predict(self, event_sequence: List[Dict[str, Any]], top_k: int = 5) -> List[Dict]:
        """Run prediction on an event sequence. Returns top-K next event predictions."""
        from dvce.services.event_prediction.torch_trainer import (
            EventSequenceTorchDataset, collate_fn
        )

        self.model.eval()
        try:
            item = EventSequenceTorchDataset([event_sequence], self.tokenizer, max_len=256)[0]
            batch = collate_fn([item])
            batch = {k: v.to(self.device) for k, v in batch.items()}

            predictions = self.model.predict_next(
                batch["token_ids"], batch["inter_event_times"],
                batch["severities"], batch["context_vectors"],
                batch["attention_mask"], top_k=top_k,
            )

            self.stats["predictions_made"] += 1
            return predictions

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return []

    # ─── PATTERN EXTRACTION ───

    def extract_patterns(self, sequences: List[List[Dict]]) -> List[Pattern]:
        """Extract shareable patterns from successful predictions."""
        from dvce.services.event_prediction.torch_trainer import (
            EventSequenceTorchDataset, collate_fn
        )
        import uuid

        patterns = []
        pattern_counts = {}

        self.model.eval()
        with torch.no_grad():
            for seq in sequences:
                if len(seq) < 4:
                    continue

                for pos in range(3, min(len(seq), 30)):
                    context = seq[:pos]
                    try:
                        item = EventSequenceTorchDataset([context], self.tokenizer, max_len=256)[0]
                        batch = collate_fn([item])
                        batch = {k: v.to(self.device) for k, v in batch.items()}

                        outputs = self.model(
                            batch["token_ids"], batch["inter_event_times"],
                            batch["severities"], batch["context_vectors"],
                            batch["attention_mask"],
                        )

                        last_pos = min(pos - 1, outputs["type_logits"].shape[1] - 1)
                        logits = outputs["type_logits"][0, last_pos, :]
                        probs = torch.softmax(logits, dim=-1)
                        top_prob, top_idx = probs.max(dim=-1)

                        if top_prob.item() >= self.config.pattern_confidence_threshold:
                            context_types = [e["event_type"] for e in context[-3:]]
                            predicted = self.tokenizer.vocabulary.decode(top_idx.item())
                            key = tuple(context_types + [predicted])

                            if key not in pattern_counts:
                                pattern_counts[key] = {"count": 0, "conf_sum": 0.0}
                            pattern_counts[key]["count"] += 1
                            pattern_counts[key]["conf_sum"] += top_prob.item()

                    except Exception:
                        continue

        # Convert to Pattern objects
        for seq_tuple, stats in pattern_counts.items():
            if stats["count"] >= 2:
                patterns.append(Pattern(
                    pattern_id=str(uuid.uuid4())[:8],
                    sequence=list(seq_tuple),
                    confidence=stats["conf_sum"] / stats["count"],
                    source_domain=self.config.domain,
                    source_node=self.config.node_id,
                    avg_time_delta=0.0,
                    observation_count=stats["count"],
                    timestamp=time.time(),
                ))

        patterns.sort(key=lambda p: p.confidence * p.observation_count, reverse=True)
        self.local_patterns = patterns[:self.config.max_patterns_per_gossip]
        self.stats["patterns_extracted"] = len(self.local_patterns)

        logger.info(f"   Extracted {len(self.local_patterns)} patterns")
        return self.local_patterns

    # ─── PATTERN SHARING (GOSSIP) ───

    def get_outgoing_patterns(self) -> List[dict]:
        """Get patterns to share with peers."""
        outgoing = [p.to_dict() for p in self.local_patterns if not p.is_expired()]
        self.stats["patterns_shared"] += len(outgoing)
        return outgoing[:self.config.max_patterns_per_gossip]

    def receive_patterns(self, patterns: List[dict]):
        """Receive and store patterns from a peer."""
        for p_dict in patterns:
            try:
                pattern = Pattern.from_dict(p_dict)
                if pattern.source_node != self.config.node_id and not pattern.is_expired():
                    self.foreign_patterns.append(pattern)
            except Exception as e:
                logger.warning(f"Invalid pattern received: {e}")

        self.stats["patterns_received"] += len(patterns)
        logger.info(f"   Received {len(patterns)} patterns from peer")

    # ─── PERSISTENCE ───

    def _load_cached_patterns(self):
        """Load previously saved patterns from disk."""
        pattern_dir = Path(self.config.pattern_dir)
        local_file = pattern_dir / "local_patterns.json"
        foreign_file = pattern_dir / "foreign_patterns.json"

        if local_file.exists():
            data = json.loads(local_file.read_text())
            self.local_patterns = [Pattern.from_dict(p) for p in data]
            logger.info(f"   Loaded {len(self.local_patterns)} cached local patterns")

        if foreign_file.exists():
            data = json.loads(foreign_file.read_text())
            self.foreign_patterns = [Pattern.from_dict(p) for p in data]
            logger.info(f"   Loaded {len(self.foreign_patterns)} cached foreign patterns")

    def _save_cached_patterns(self):
        """Save patterns to disk for persistence."""
        pattern_dir = Path(self.config.pattern_dir)
        pattern_dir.mkdir(parents=True, exist_ok=True)

        local_file = pattern_dir / "local_patterns.json"
        foreign_file = pattern_dir / "foreign_patterns.json"

        local_file.write_text(json.dumps([p.to_dict() for p in self.local_patterns], indent=2))
        foreign_file.write_text(json.dumps([p.to_dict() for p in self.foreign_patterns], indent=2))

    # ─── STATUS ───

    def get_status(self) -> dict:
        """Return node status for monitoring."""
        uptime = time.time() - self.stats["uptime_start"] if self.stats["uptime_start"] else 0
        return {
            "node_id": self.config.node_id,
            "node_name": self.config.node_name,
            "domain": self.config.domain,
            "device": self.device,
            "model_size": self.config.model_size,
            "expertise_scores": self.expertise_scores,
            "local_patterns": len(self.local_patterns),
            "foreign_patterns": len(self.foreign_patterns),
            "predictions_made": self.stats["predictions_made"],
            "patterns_shared": self.stats["patterns_shared"],
            "patterns_received": self.stats["patterns_received"],
            "uptime_seconds": int(uptime),
            "running": self.running,
        }

    # ─── MAIN LOOP ───

    async def _main_loop(self):
        """Main event loop — periodic pattern sharing and health checks."""
        gossip_interval = self.config.gossip_interval_seconds

        while self.running:
            try:
                # Periodic status log
                status = self.get_status()
                logger.info(
                    f"[{self.config.node_id}] "
                    f"predictions={status['predictions_made']} "
                    f"patterns_local={status['local_patterns']} "
                    f"patterns_foreign={status['foreign_patterns']} "
                    f"uptime={status['uptime_seconds']}s"
                )

                # Wait for next gossip round
                await asyncio.sleep(gossip_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(5)


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Start a swarm node based on command-line args or auto-detection."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="DVCE Swarm Node")
    parser.add_argument("--config", type=str, help="Path to node config JSON")
    parser.add_argument("--profile", type=str, choices=["mac", "terrornode", "towerseven", "mac_i5"],
                        help="Use a pre-configured profile")
    args = parser.parse_args()

    # Load config
    if args.config:
        config = NodeConfig.load(Path(args.config))
    elif args.profile == "mac":
        from config import mac_node_config
        config = mac_node_config()
    elif args.profile == "terrornode":
        from config import terrornode_config
        config = terrornode_config()
    elif args.profile == "towerseven":
        from config import towerseven_config
        config = towerseven_config()
    elif args.profile == "mac_i5":
        from config import mac_i5_config
        config = mac_i5_config()
    else:
        # Auto-detect based on platform
        system = platform.system()
        machine = platform.machine()
        if system == "Darwin" and machine == "arm64":
            from config import mac_node_config
            config = mac_node_config()
        elif system == "Windows":
            from config import terrornode_config
            config = terrornode_config()
        else:
            from config import towerseven_config
            config = towerseven_config()

    # Create and start node
    node = SwarmNode(config)
    asyncio.run(node.start())


if __name__ == "__main__":
    import platform
    main()
