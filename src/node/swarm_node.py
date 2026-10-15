"""
Swarm Node — the runtime for one machine in the DVCE swarm.

What a node does TODAY (verified 2026-10-13, see docs/SWARM_QUERY_ROUTING.md):
1. Loads the trained checkpoint named in its config, or exits if that
   checkpoint is configured but unusable. A node with no checkpoint configured
   runs with NO model. It never runs on random weights.
2. Registers with the broker once and sends a heartbeat every
   min(gossip interval, HEARTBEAT_MAX_INTERVAL) seconds.
3. Reads its socket continuously (network.py reader task) so the broker's
   relays never back up; relayed patterns are counted and discarded.
4. Reconnects with exponential backoff when the connection really drops.

What it does NOT do yet, although the methods exist:
- Nothing calls predict(): the broker does not route queries to nodes.
- Nothing calls extract_patterns() or send_patterns(): a node shares nothing.
- Relayed patterns are not stored or used, so foreign_patterns stays empty.
- The expertise scores it advertises are configured constants (default 0.5),
  not measured accuracy.

This is the single script that runs on every machine in the swarm,
configured differently per hardware/role.
"""

import asyncio
import json
import os
import platform
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

import torch

from config import NodeConfig

logger = logging.getLogger(__name__)

# The broker drops a node after NODE_STALE_AFTER (300 s) without a heartbeat.
# TowerSeven's gossip interval is 300 s, so heartbeating on the gossip interval
# alone put it right on that edge; heartbeats are capped well below it.
HEARTBEAT_MAX_INTERVAL = 60

LOG_FILE_ENV = "DVCE_NODE_LOG_FILE"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUPS = 5

# Vocab used by pre-bundle checkpoints that ship without their own vocab.json.
LEGACY_VOCAB_PATH = Path(__file__).parent.parent.parent / "experiments/models/vocab.json"

# Dimensions for checkpoints that do not record their own architecture.
LEGACY_MODEL_SIZES = {
    "tiny":     {"d_model": 64,  "n_heads": 2, "n_layers": 2, "d_ff": 256,  "time_encoding_dim": 16},
    "standard": {"d_model": 128, "n_heads": 4, "n_layers": 4, "d_ff": 512,  "time_encoding_dim": 32},
    "large":    {"d_model": 256, "n_heads": 8, "n_layers": 4, "d_ff": 1024, "time_encoding_dim": 64},
}
_ARCH_KEYS = ("d_model", "n_heads", "n_layers", "d_ff", "time_encoding_dim")
_SPECIAL_TOKENS = ("<PAD>", "<BOS>", "<EOS>", "<UNK>")


class ModelNotLoadedError(RuntimeError):
    """The node has no trained model: none configured, or the configured one is unusable."""


def resolve_model_files(config: NodeConfig) -> Tuple[Optional[Path], Optional[Path]]:
    """Return the (checkpoint, vocab) paths the config asks for.

    (None, None) means no model is configured at all. Existence is not checked
    here — a configured-but-missing file must surface as an error, not as
    "no model configured".
    """
    explicit_vocab = Path(config.vocab_path).expanduser() if config.vocab_path else None
    if config.model_path:
        checkpoint = Path(config.model_path).expanduser()
        sibling = checkpoint.parent / "vocab.json"
        return checkpoint, explicit_vocab or (sibling if sibling.exists() else LEGACY_VOCAB_PATH)
    model_dir = getattr(config, "model_dir", None)
    if model_dir:
        bundle = Path(model_dir).expanduser()
        return bundle / "best_model.pt", explicit_vocab or bundle / "vocab.json"
    return None, None


def load_type_to_id(vocab_path: Path) -> Dict[str, int]:
    """Read a vocab.json (flat {type: id} or nested {"type_to_id": {...}}).

    The ids are the checkpoint's embedding rows, so they are taken exactly as
    saved rather than re-assigned in file order.
    """
    data = json.loads(vocab_path.read_text())
    raw = data["type_to_id"] if "type_to_id" in data else data
    type_to_id = {str(k): int(v) for k, v in raw.items()}
    if sorted(type_to_id.values()) != list(range(len(type_to_id))):
        raise ModelNotLoadedError(f"{vocab_path}: token ids are not a contiguous 0..N-1 range")
    missing = [t for t in _SPECIAL_TOKENS if t not in type_to_id]
    if missing:
        raise ModelNotLoadedError(f"{vocab_path}: special tokens missing: {missing}")
    return type_to_id


def architecture_for(saved_cfg: dict, model_size: str) -> Dict[str, int]:
    """Model dimensions: the checkpoint's own if it recorded them, else the size table.

    The production checkpoint (d_model=192, 6 heads, 6 layers) matches no entry
    in the size table, which is why nodes could not load it.
    """
    if all(k in saved_cfg for k in _ARCH_KEYS):
        return {k: int(saved_cfg[k]) for k in _ARCH_KEYS}
    return dict(LEGACY_MODEL_SIZES[model_size])


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
        # Truth about the model, reported in status. Stays loaded=False unless
        # trained weights were actually read from a checkpoint.
        self.model_info: Dict[str, Any] = {"loaded": False, "checkpoint": None}
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
            # No callback: relayed patterns are drained and counted, not kept.
            # Storing them would grow memory without bound and nothing uses them.
            on_patterns_received=None,
        )

        # Start main loop
        self.running = True
        self.stats["uptime_start"] = time.time()

        logger.info(f"✅ Node {self.config.node_id} online")
        logger.info(f"   Model: {self._model_label()}")
        logger.info(f"   Advertised expertise (configured, not measured): {self.expertise_scores}")
        logger.info(
            "   Role: heartbeat-only — no queries are routed to this node; it sends "
            "no patterns and discards the ones the broker relays"
        )

        # Register first, then heartbeat. Running both concurrently made the
        # main loop see "not connected" on its first pass and register a second
        # time, which the broker logs as a node_id collision at every start.
        # connect() is also serialised by a lock inside the client.
        await self.network.connect()
        try:
            await self._main_loop()
        finally:
            await self.network.disconnect()

    async def stop(self):
        """Gracefully shut down the node."""
        self.running = False
        self._save_cached_patterns()
        logger.info(f"🛑 Node {self.config.node_id} stopped")

    # ─── MODEL ───

    def _load_model(self):
        """Load the trained checkpoint named in the config.

        Raises ModelNotLoadedError if a checkpoint is configured but cannot be
        loaded exactly. If none is configured the node keeps model=None. There
        is no path that leaves a randomly initialised model in place.
        """
        # Expertise is advertised regardless of the model; it is a configured
        # constant, not a measurement.
        if self.config.expertise_scores:
            self.expertise_scores = self.config.expertise_scores
        else:
            self.expertise_scores = {self.config.domain: 0.5}

        checkpoint_path, vocab_path = resolve_model_files(self.config)
        if checkpoint_path is None:
            self.model = None
            self.tokenizer = None
            self.model_info = {"loaded": False, "checkpoint": None,
                               "reason": "no checkpoint configured"}
            logger.warning(
                "   NO MODEL: no checkpoint is configured for this node. It will "
                "register and heartbeat only; it cannot predict or extract patterns."
            )
            return

        if not checkpoint_path.exists():
            raise ModelNotLoadedError(
                f"Checkpoint not found: {checkpoint_path}. Refusing to start with "
                f"random weights. Restore the checkpoint, or point DVCE_NODE_MODEL_DIR "
                f"/ the node config at a directory holding best_model.pt + vocab.json."
            )
        if not vocab_path.exists():
            raise ModelNotLoadedError(
                f"Vocabulary not found: {vocab_path} (needed by {checkpoint_path})."
            )

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
        from dvce.services.event_prediction.tokenizer import EventTokenizer, EventVocabulary

        type_to_id = load_type_to_id(vocab_path)

        # Read the checkpoint first: its saved config decides the architecture
        # and whether the decoder's cross-attention is causally masked
        # (causal_memory). A checkpoint trained with the mask must run with it,
        # and one trained without must run without, or predictions silently change.
        checkpoint = torch.load(str(checkpoint_path), map_location=self.device)
        if not isinstance(checkpoint, dict) or "model_state_dict" not in checkpoint:
            raise ModelNotLoadedError(f"{checkpoint_path}: no model_state_dict in checkpoint")
        state_dict = checkpoint["model_state_dict"]
        saved_cfg = checkpoint.get("config") or {}

        embedding_rows = state_dict["event_embed.weight"].shape[0]
        if embedding_rows != len(type_to_id):
            raise ModelNotLoadedError(
                f"Vocabulary/checkpoint mismatch: {vocab_path} has {len(type_to_id)} "
                f"types but {checkpoint_path} was trained on {embedding_rows}."
            )

        context_dim = int(saved_cfg.get("context_dim", 64))
        max_seq_len = int(saved_cfg.get("max_seq_len", 256))

        vocabulary = EventVocabulary()
        vocabulary._type_to_id = dict(type_to_id)
        vocabulary._id_to_type = {v: k for k, v in type_to_id.items()}
        vocabulary.freeze()
        self.tokenizer = EventTokenizer(
            vocabulary=vocabulary, context_dim=context_dim, max_sequence_length=max_seq_len
        )
        logger.info(f"   Vocabulary: {vocabulary.size} types from {vocab_path}")

        # Build model
        config = TorchModelConfig(
            vocab_size=len(type_to_id),
            context_dim=context_dim,
            dropout=0.1,
            max_seq_len=max_seq_len,
            learning_rate=3e-4,
            **architecture_for(saved_cfg, self.config.model_size),
            # Only passed when on: a node whose bundled torch_model.py predates
            # the field must still load legacy checkpoints, but must fail
            # loudly (TypeError) rather than silently run a causal-trained
            # checkpoint without the mask.
            **({"causal_memory": True} if saved_cfg.get("causal_memory") else {}),
        )

        model = EventTransformerTorch(config)
        try:
            model.load_state_dict(state_dict)
        except RuntimeError as e:
            raise ModelNotLoadedError(
                f"{checkpoint_path} does not fit the model built for it "
                f"(d_model={config.d_model}, layers={config.n_layers}): {e}"
            ) from e

        model.to(self.device)
        model.eval()
        self.model = model

        total_params = sum(p.numel() for p in self.model.parameters())
        self.model_info = {
            "loaded": True,
            "checkpoint": str(checkpoint_path),
            "vocab_size": len(type_to_id),
            "params": total_params,
            "causal_memory": bool(saved_cfg.get("causal_memory")),
        }
        logger.info(f"   Loaded checkpoint: {checkpoint_path}")
        logger.info(f"   Model: {total_params:,} params on {self.device}")

    def _model_label(self) -> str:
        """One-line description of the model for logs."""
        if not self.model_info.get("loaded"):
            return "none"
        return (
            f"trained checkpoint {self.model_info['checkpoint']} "
            f"({self.model_info['vocab_size']} types, {self.model_info['params']:,} params)"
        )

    def _require_model(self):
        if self.model is None:
            raise ModelNotLoadedError(
                f"Node {self.config.node_id} has no model loaded "
                f"({self.model_info.get('reason', 'not started')})."
            )

    # ─── PREDICTION ───

    def predict(self, event_sequence: List[Dict[str, Any]], top_k: int = 5) -> List[Dict]:
        """Run prediction on an event sequence. Returns top-K next event predictions.

        Raises ModelNotLoadedError if the node has no trained model. Nothing in
        the swarm calls this yet (there is no query routing).
        """
        self._require_model()
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
            for p in predictions:
                p["event_type"] = self.tokenizer.vocabulary.decode(p["event_type_id"])

            self.stats["predictions_made"] += 1
            return predictions

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return []

    # ─── PATTERN EXTRACTION ───

    def extract_patterns(self, sequences: List[List[Dict]]) -> List[Pattern]:
        """Extract shareable patterns from the model's confident next-event calls.

        Raises ModelNotLoadedError if the node has no trained model. Nothing
        calls this yet, so a running node extracts no patterns.
        """
        self._require_model()
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
            "model_loaded": bool(self.model_info.get("loaded")),
            "model_checkpoint": self.model_info.get("checkpoint"),
            "model_vocab_size": self.model_info.get("vocab_size"),
            "role": "heartbeat-only",
            "expertise_scores": self.expertise_scores,
            "expertise_measured": False,
            "local_patterns": len(self.local_patterns),
            "foreign_patterns": len(self.foreign_patterns),
            "predictions_made": self.stats["predictions_made"],
            "patterns_shared": self.stats["patterns_shared"],
            "patterns_received": self.stats["patterns_received"],
            "uptime_seconds": int(uptime),
            "running": self.running,
        }

    # ─── MAIN LOOP ───

    def heartbeat_interval(self) -> float:
        return float(min(self.config.gossip_interval_seconds, HEARTBEAT_MAX_INTERVAL))

    async def _main_loop(self):
        """Heartbeat on a fixed interval; reconnect (with backoff) only when the link drops.

        Reads happen in the client's reader task, so a heartbeat is never held
        up by, and never waits for, anything the broker sends.
        """
        interval = self.heartbeat_interval()
        status_every = max(1, int(self.config.gossip_interval_seconds // interval))
        beats = 0

        while self.running:
            try:
                if not self.network.connected:
                    logger.warning("Not connected to broker; reconnecting")
                    await self.network.reconnect()
                    logger.info("Reconnected to broker")

                if not await self.network.send_heartbeat():
                    continue  # link marked lost; reconnect on the next pass

                if beats % status_every == 0:
                    status = self.get_status()
                    net = self.network.stats
                    logger.info(
                        f"[{self.config.node_id}] "
                        f"role={status['role']} "
                        f"model={'trained' if status['model_loaded'] else 'none'} "
                        f"registrations={net['registrations']} "
                        f"broker_msgs={net['messages_received']} "
                        f"relayed_patterns_discarded={net['patterns_relayed_to_us']} "
                        f"uptime={status['uptime_seconds']}s"
                    )
                beats += 1

                # Sleep until the next heartbeat, or wake early if the link drops.
                await self.network.wait_lost(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Main loop error: {e.__class__.__name__}: {e}")
                await asyncio.sleep(5)


# ============================================================================
# ENTRY POINT
# ============================================================================

def setup_logging(log_file: Optional[str] = None) -> None:
    """Log to stderr, and to a rotating file when one is given (service mode)."""
    from logging.handlers import RotatingFileHandler

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                                      encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)


def main():
    """Start a swarm node based on command-line args or auto-detection."""
    import argparse

    parser = argparse.ArgumentParser(description="DVCE Swarm Node")
    parser.add_argument("--config", type=str, help="Path to node config JSON")
    parser.add_argument("--profile", type=str, choices=["mac", "terrornode", "towerseven", "mac_i5"],
                        help="Use a pre-configured profile")
    parser.add_argument("--log-file", type=str, default=os.environ.get(LOG_FILE_ENV),
                        help=f"Also log to this file, rotated at {LOG_MAX_BYTES // (1024 * 1024)} MB "
                             f"x {LOG_BACKUPS} (default: ${LOG_FILE_ENV})")
    args = parser.parse_args()
    setup_logging(args.log_file)

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
    try:
        asyncio.run(node.start())
    except ModelNotLoadedError as e:
        logger.critical(f"❌ Node {config.node_id} NOT started — no trained model: {e}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
