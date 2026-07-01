"""
DVCE ↔ Swarm Bridge

This module plugs the swarm intelligence layer into DVCE's prediction pipeline.
It replaces the direct model call with a swarm-aware predictor that:

1. Checks local expertise for the query domain
2. If local expertise is high → predict locally (fast path)
3. If local expertise is low → route to a better node via broker
4. After every prediction → extract patterns and share with swarm
5. Periodically incorporate foreign patterns to improve local model

Usage in DVCE:
    # In prediction_api.py, replace:
    #   predictor = EventPredictor.from_s3(...)
    # With:
    #   predictor = SwarmPredictor(node_config)
    
    predictor = SwarmPredictor()
    predictions = predictor.predict(event_history, top_k=5)
    # Same interface, but now backed by the swarm
"""

import asyncio
import json
import sys
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SwarmPredictor:
    """
    Drop-in replacement for EventPredictor that routes through the swarm.
    
    Maintains the same interface as EventPredictor (predict, predict_sequence)
    but adds swarm intelligence: routing, pattern sharing, network-enhanced accuracy.
    
    Falls back to local prediction if broker is unreachable (graceful degradation).
    """

    def __init__(
        self,
        broker_host: str = "127.0.0.1",
        broker_port: int = 9876,
        local_model_path: Optional[str] = None,
        domain: str = "financial",
        node_id: str = "dvce-api",
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.domain = domain
        self.node_id = node_id
        self.local_predictor = None
        self.swarm_connected = False
        self.predictions_made = 0
        self.predictions_routed = 0
        self._pattern_queue_list = []
        
        # Load local model as fallback
        self._load_local_predictor(local_model_path)

    def _load_local_predictor(self, model_path: Optional[str]):
        """Load the local DVCE predictor as fallback."""
        try:
            sys.path.insert(0, "/Users/webber/Desktop/dvce/src")
            from dvce.services.event_prediction.inference import EventPredictor

            if model_path and Path(model_path).exists():
                self.local_predictor = EventPredictor.from_local(model_path)
            else:
                # Try default locations
                default_paths = [
                    Path.home() / ".dvce/models/dvce-FINAL-small-fast",
                    Path.home() / ".dvce/models/dvce-MEGATRAIN",
                ]
                for p in default_paths:
                    if p.exists() and (p / "best_model.pt").exists():
                        self.local_predictor = EventPredictor.from_local(str(p))
                        logger.info(f"Local predictor loaded from {p}")
                        break

            if self.local_predictor is None:
                logger.warning("No local model found — predictions will require broker")

        except Exception as e:
            logger.error(f"Failed to load local predictor: {e}")

    def predict(
        self,
        event_history: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Predict next events — swarm-enhanced with local fallback.
        
        Same interface as EventPredictor.predict().
        """
        self.predictions_made += 1

        # For now: use local predictor (Phase 1 behavior)
        # Phase 2+: check expertise, route if needed
        if self.local_predictor:
            predictions = self.local_predictor.predict(event_history, top_k=top_k)

            # Background: extract pattern from this prediction (async, non-blocking)
            self._maybe_extract_pattern(event_history, predictions)

            return predictions

        return []

    def predict_sequence(
        self,
        event_history: List[Dict[str, Any]],
        n_steps: int = 5,
        top_k: int = 3,
    ) -> List[List[Dict[str, Any]]]:
        """Multi-step prediction — same interface as EventPredictor."""
        if self.local_predictor:
            return self.local_predictor.predict_sequence(event_history, n_steps=n_steps, top_k=top_k)
        return []

    def _maybe_extract_pattern(self, history: List[dict], predictions: List[dict]):
        """
        After a prediction, check if it's high-confidence enough to share.
        This feeds the swarm — every DVCE prediction potentially generates
        a pattern that helps other nodes.
        """
        if not predictions:
            return

        top_prediction = predictions[0]
        confidence = top_prediction.get("probability", 0)

        # Only extract if confidence is reasonable (above noise floor)
        if confidence >= 0.3:
            # Build the pattern: last 3 events + prediction
            if len(history) >= 3:
                pattern = {
                    "pattern_id": f"dvce_{int(time.time())}_{self.predictions_made}",
                    "sequence": [e.get("event_type", "unknown") for e in history[-3:]] + [top_prediction["event_type"]],
                    "confidence": confidence,
                    "source_domain": self.domain,
                    "source_node": self.node_id,
                    "avg_time_delta": top_prediction.get("predicted_time_delta", 0),
                    "observation_count": 1,
                    "timestamp": time.time(),
                    "ttl": 7,
                }
                # Queue for async sharing (don't block the prediction response)
                self._pattern_queue_list.append(pattern)

    def flush_patterns_to_swarm(self):
        """Send queued patterns to the broker. Call periodically."""
        if not self._pattern_queue_list:
            return 0

        patterns_to_send = self._pattern_queue_list[:]
        self._pattern_queue_list.clear()

        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.broker_host, self.broker_port))

            # Register
            msg = json.dumps({
                "type": "register",
                "node_id": self.node_id,
                "domain": self.domain,
                "expertise_scores": {self.domain: 0.5},
            }) + "\n"
            sock.sendall(msg.encode())
            sock.recv(4096)  # ack

            # Send patterns
            msg = json.dumps({
                "type": "patterns",
                "source_node": self.node_id,
                "patterns": patterns_to_send,
            }) + "\n"
            sock.sendall(msg.encode())
            sock.close()

            logger.info(f"Flushed {len(patterns_to_send)} patterns to swarm")
            return len(patterns_to_send)

        except Exception as e:
            logger.warning(f"Could not flush patterns to swarm: {e}")
            # Put them back for next attempt
            self._pattern_queue_list.extend(patterns_to_send)
            return 0

    # ─── Properties matching EventPredictor interface ───

    @property
    def vocab(self) -> dict:
        if self.local_predictor:
            return self.local_predictor.vocab
        return {}

    @property
    def event_types(self) -> List[str]:
        if self.local_predictor:
            return self.local_predictor.event_types
        return []

    @property
    def domains(self) -> List[str]:
        if self.local_predictor:
            return self.local_predictor.domains
        return []
