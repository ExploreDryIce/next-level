"""
DVCE ↔ Swarm Bridge

SwarmPredictor has the same interface as DVCE's EventPredictor and is what the
DVCE API loads when this repo is present.

What it does TODAY (verified 2026-10-13):
1. Every prediction is made by the local EventPredictor, on this machine, from
   the local checkpoint. The numbers are identical to calling EventPredictor
   directly. No other node is consulted and nothing is "swarm-enhanced".
2. After a prediction on known event types with probability >= 0.3, it queues
   a single-observation pattern (last 3 inputs + top prediction).
3. flush_patterns_to_swarm() pushes that queue to the broker, which stores and
   relays it. No node reads those patterns back into a model.

What it does NOT do: expertise checks, routing to another node, merging of
answers, or learning from foreign patterns. `predictions_routed` is always 0
and `swarm_connected` is always False. The routing design is in
docs/SWARM_QUERY_ROUTING.md.

Usage in DVCE:
    predictor = SwarmPredictor()
    predictions = predictor.predict(event_history, top_k=5)
"""

import asyncio
import json
import os
import sys
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SwarmPredictor:
    """
    Drop-in replacement for EventPredictor that also queues patterns for the broker.

    Same interface as EventPredictor (predict, predict_sequence, vocab,
    event_types, domains). Predictions come from the local model only; the
    broker is used solely as a place to push patterns, and predictions do not
    depend on it being reachable.
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
        self.swarm_connected = False   # never set: there is no live swarm session
        self.predictions_made = 0
        self.predictions_routed = 0    # never incremented: there is no routing
        self._pattern_queue_list = []
        
        # The local model is the only predictor there is (not a fallback).
        self._load_local_predictor(local_model_path)
        logger.info(
            "SwarmPredictor ready: predictions are local-model only (no routing, "
            "no foreign patterns applied); the broker only receives queued patterns"
        )

    def _load_local_predictor(self, model_path: Optional[str]):
        """Load the local DVCE predictor — the only source of predictions."""
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
                logger.warning(
                    "No local model found — predict() will return []. "
                    "The broker cannot answer predictions."
                )

        except Exception as e:
            logger.error(f"Failed to load local predictor: {e}")

    def predict(
        self,
        event_history: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Predict next events with the local model.

        Same interface and same output as EventPredictor.predict(). The swarm
        does not take part in the prediction.
        """
        self.predictions_made += 1

        # Local model only. Routing is not implemented
        # (docs/SWARM_QUERY_ROUTING.md).
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
        After a prediction, queue it as a pattern if it clears the noise floor.

        A queued pattern is one model output seen once (observation_count=1),
        not a validated regularity, and no node currently consumes it.
        """
        if not predictions:
            return

        top_prediction = predictions[0]
        confidence = top_prediction.get("probability", 0)

        # Never share a pattern built on inputs the model doesn't know: those
        # predictions are the corpus prior (e.g. gp_military_strike), not a
        # learned transition. The snapshot engine probed with raw, unmapped
        # names and queued one such fabricated pattern per snapshot (2026-09-14).
        vocab = getattr(self.local_predictor, "vocab", None) or {}
        if vocab and any(e.get("event_type") not in vocab for e in history[-3:]):
            return

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

            # Register. The token was missing entirely here, so every flush
            # was rejected as UNAUTHORIZED and the queued patterns were
            # dropped — silently, because the ack below is never inspected.
            msg = json.dumps({
                "type": "register",
                "node_id": self.node_id,
                "domain": self.domain,
                "expertise_scores": {self.domain: 0.5},
                "token": os.environ["DVCE_BROKER_TOKEN"],
            }) + "\n"
            sock.sendall(msg.encode())
            ack = sock.recv(4096)
            try:
                rejected = json.loads(ack.decode().strip() or "{}").get("type") == "rejected"
            except (ValueError, AttributeError):
                rejected = False
            if rejected:
                # Previously this was reported as a successful flush.
                sock.close()
                logger.warning(
                    f"Broker rejected registration for '{self.node_id}' — "
                    f"{len(patterns_to_send)} patterns NOT sent, kept in queue"
                )
                self._pattern_queue_list.extend(patterns_to_send)
                return 0

            # Send patterns
            msg = json.dumps({
                "type": "patterns",
                "source_node": self.node_id,
                "patterns": patterns_to_send,
            }) + "\n"
            sock.sendall(msg.encode())
            sock.close()

            logger.info(
                f"Pushed {len(patterns_to_send)} queued patterns to the broker "
                f"(stored and relayed; not confirmed as used by any node)"
            )
            return len(patterns_to_send)

        except Exception as e:
            logger.warning(f"Could not push patterns to the broker: {e}")
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
