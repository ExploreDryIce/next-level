"""
Node configuration — defines what a swarm node is and how it behaves.
Each node has an identity, a model, a domain, and connection info.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import json
import platform


@dataclass
class NodeConfig:
    """Configuration for a single swarm node."""

    # Identity
    node_id: str                          # Unique identifier (e.g., "terrornode", "macbook-m4")
    node_name: str                        # Human-readable name
    domain: str                           # Primary domain specialization

    # Network
    broker_host: str = "100.64.0.1"       # NATS broker address (coordinator node)
    broker_port: int = 4222               # NATS port
    tailscale_ip: Optional[str] = None    # This node's Tailscale IP

    # Model
    model_size: str = "standard"          # tiny | standard | large
    model_path: Optional[str] = None      # Path to .pt checkpoint
    vocab_path: Optional[str] = None      # Path to vocab.json

    # Hardware
    device: str = "auto"                  # auto | cpu | cuda | mps
    max_memory_mb: int = 2048             # Max memory for model operations

    # Pattern sharing
    pattern_dir: str = "patterns"         # Where to store received patterns
    gossip_interval_seconds: int = 60     # How often to share patterns
    max_patterns_per_gossip: int = 50     # Max patterns to send per round
    pattern_confidence_threshold: float = 0.6  # Min confidence to share

    # Training
    retrain_interval_hours: int = 168     # Weekly retraining by default
    checkpoint_dir: str = "checkpoints"

    # Expertise
    expertise_scores: dict = field(default_factory=dict)

    def detect_device(self) -> str:
        """Auto-detect the best available compute device."""
        if self.device != "auto":
            return self.device

        import torch
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def save(self, path: Path):
        """Save config to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in self.__dict__.items()}
        path.write_text(json.dumps(data, indent=2, default=str))

    @classmethod
    def load(cls, path: Path) -> "NodeConfig":
        """Load config from JSON."""
        data = json.loads(path.read_text())
        return cls(**data)


# ============================================================================
# PRE-CONFIGURED NODE PROFILES
# ============================================================================

def mac_node_config() -> NodeConfig:
    """MacBook Pro M4 Max — coordinator + financial specialist."""
    return NodeConfig(
        node_id="macbook-m4",
        node_name="MacBook Pro M4 Max (Coordinator)",
        domain="financial",
        broker_host="127.0.0.1",  # Runs the broker locally
        broker_port=9876,
        tailscale_ip=None,  # Will be set at runtime
        model_size="large",
        device="mps",
        max_memory_mb=8192,
        gossip_interval_seconds=30,
    )


def terrornode_config() -> NodeConfig:
    """MSI GP63 Leopard — tech/cyber specialist with CUDA."""
    return NodeConfig(
        node_id="terrornode",
        node_name="TerrorNode (MSI GP63 - CUDA)",
        domain="tech",
        broker_host="100.97.250.64",  # Mac's Tailscale IP (runs the broker)
        broker_port=9876,
        tailscale_ip="100.99.237.66",
        model_size="standard",
        device="cuda",
        max_memory_mb=4096,
        gossip_interval_seconds=60,
    )


def towerseven_config() -> NodeConfig:
    """Raspberry Pi 3 — edge anomaly detector, tiny model."""
    return NodeConfig(
        node_id="towerseven",
        node_name="TowerSeven (Raspberry Pi 3 - Edge)",
        domain="natural",
        broker_host="100.97.250.64",  # Mac's Tailscale IP (runs the broker)
        broker_port=9876,
        tailscale_ip=None,  # Pi connects via local network
        model_size="tiny",
        device="cpu",
        max_memory_mb=512,  # Pi 3 only has 1GB total
        gossip_interval_seconds=300,  # Less frequent — save resources
        max_patterns_per_gossip=10,  # Smaller payloads
        pattern_confidence_threshold=0.7,  # Only share high-confidence
    )


def mac_i5_config() -> NodeConfig:
    """Old MacBook Pro i5 — health + logistics specialist, CPU-only."""
    return NodeConfig(
        node_id="mac-i5",
        node_name="MacBook Pro i5 (Health/Logistics)",
        domain="health",
        broker_host="192.168.1.119",  # M4 Max local IP (runs broker)
        broker_port=9876,
        tailscale_ip=None,
        model_size="standard",
        device="cpu",
        max_memory_mb=4096,  # 8GB total, leave half for OS
        gossip_interval_seconds=120,  # Every 2 min
        max_patterns_per_gossip=25,
        pattern_confidence_threshold=0.6,
    )
