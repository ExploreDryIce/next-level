"""SwarmPredictor keeps EventPredictor's interface and reports its own work truthfully.

- Interface parity is pinned so relabelling can never drift it.
- predict() returns exactly what the local model returns; nothing is routed.
- A flush the broker rejected is reported as 0 sent, not as a success.
"""

import inspect
import json
import os
import socket
import sys
import threading
from pathlib import Path

os.environ.setdefault("DVCE_BROKER_TOKEN", "test-token-not-a-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "integrations"))

import dvce_swarm_bridge as bridge  # noqa: E402
from dvce.services.event_prediction.inference import EventPredictor  # noqa: E402


class _LocalModel:
    """Stands in for EventPredictor so no checkpoint is read."""

    vocab = {"sc_a": 4, "sc_b": 5, "sc_c": 6, "sc_d": 7}
    event_types = ["sc_a", "sc_b", "sc_c", "sc_d"]
    domains = ["sc"]

    def predict(self, event_history, top_k=10):
        return [{"event_type": "sc_d", "probability": 0.9,
                 "predicted_time_delta": None, "predicted_severity": None}]

    def predict_sequence(self, event_history, n_steps=5, top_k=3):
        return [self.predict(event_history)] * n_steps


def _predictor(monkeypatch, port=1):
    monkeypatch.setattr(bridge.SwarmPredictor, "_load_local_predictor",
                        lambda self, path: setattr(self, "local_predictor", _LocalModel()))
    return bridge.SwarmPredictor(broker_host="127.0.0.1", broker_port=port)


def test_interface_matches_event_predictor():
    for method in ("predict", "predict_sequence"):
        ours = inspect.signature(getattr(bridge.SwarmPredictor, method))
        theirs = inspect.signature(getattr(EventPredictor, method))
        assert list(ours.parameters) == list(theirs.parameters), method
        assert [p.default for p in ours.parameters.values()] == \
               [p.default for p in theirs.parameters.values()], method
    for prop in ("vocab", "event_types", "domains"):
        assert isinstance(getattr(bridge.SwarmPredictor, prop), property), prop
    # DVCE detects the swarm predictor by this method and reads this attribute.
    assert callable(bridge.SwarmPredictor.flush_patterns_to_swarm)


def test_predictions_are_the_local_models_and_nothing_is_routed(monkeypatch):
    predictor = _predictor(monkeypatch)
    history = [{"event_type": t} for t in ("sc_a", "sc_b", "sc_c")]
    assert predictor.predict(history, top_k=5) == _LocalModel().predict(history)
    assert predictor.predictions_made == 1
    assert predictor.predictions_routed == 0
    assert predictor.swarm_connected is False
    assert len(predictor._pattern_queue_list) == 1
    assert predictor._pattern_queue_list[0]["observation_count"] == 1


def _fake_broker(reply):
    """One-shot TCP server: answers the register line with `reply`, records the rest."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received = []

    def serve():
        conn, _ = server.accept()
        conn.settimeout(2)
        reader = conn.makefile("r")
        received.append(json.loads(reader.readline()))
        conn.sendall((json.dumps(reply) + "\n").encode())
        try:
            line = reader.readline()
            if line:
                received.append(json.loads(line))
        except OSError:
            pass
        conn.close()
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server.getsockname()[1], received, thread


def test_rejected_flush_reports_zero_and_keeps_the_queue(monkeypatch, caplog):
    port, received, thread = _fake_broker({"type": "rejected", "reason": "invalid token"})
    predictor = _predictor(monkeypatch, port)
    predictor.predict([{"event_type": t} for t in ("sc_a", "sc_b", "sc_c")])
    with caplog.at_level("WARNING"):
        assert predictor.flush_patterns_to_swarm() == 0
    thread.join(timeout=3)
    assert len(predictor._pattern_queue_list) == 1
    assert [m["type"] for m in received] == ["register"]
    assert "NOT sent" in caplog.text


def test_accepted_flush_sends_the_queue(monkeypatch):
    port, received, thread = _fake_broker({"type": "registered", "swarm_size": 1, "nodes": []})
    predictor = _predictor(monkeypatch, port)
    predictor.predict([{"event_type": t} for t in ("sc_a", "sc_b", "sc_c")])
    assert predictor.flush_patterns_to_swarm() == 1
    thread.join(timeout=3)
    assert predictor._pattern_queue_list == []
    assert [m["type"] for m in received] == ["register", "patterns"]
    assert received[1]["patterns"][0]["sequence"] == ["sc_a", "sc_b", "sc_c", "sc_d"]
