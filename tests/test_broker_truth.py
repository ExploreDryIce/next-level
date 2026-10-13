"""The broker reports what it is — a relay — and keeps personal data out of source.

- The SMS alert recipient comes from DVCE_ALERT_SMS_TO; unset means no SMS.
- `status` keeps its existing keys and adds what they do and do not mean.
- A `query` reply says plainly that nothing was forwarded.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

os.environ["DVCE_BROKER_TOKEN"] = "test-token-not-a-secret"
os.environ.setdefault("DVCE_BROKER_TOKEN_LEGACY", "")
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC / "swarm"))

import broker as B  # noqa: E402


class _FakeSMTP:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)


def _smtp_env(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(B.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setenv("GMAIL_USER", "sender@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "not-a-real-password")


def test_no_sms_is_sent_when_recipient_is_unset(monkeypatch, caplog):
    _smtp_env(monkeypatch)
    monkeypatch.delenv("DVCE_ALERT_SMS_TO", raising=False)
    with caplog.at_level("WARNING"):
        B._send_sms_alert("UNAUTHORIZED node 'x' tried to join swarm")
    assert _FakeSMTP.sent == []
    assert "no SMS config" in caplog.text  # the alert is still logged


def test_sms_goes_to_the_recipient_from_the_environment(monkeypatch):
    _smtp_env(monkeypatch)
    monkeypatch.setenv("DVCE_ALERT_SMS_TO", "5550100@sms.example.com")
    B._send_sms_alert("test alert")
    assert len(_FakeSMTP.sent) == 1
    assert _FakeSMTP.sent[0]["To"] == "5550100@sms.example.com"


def test_no_phone_number_or_sms_address_in_swarm_source():
    phone_like = re.compile(r"\b\d{10}\b|\d{3}[-. ]\d{3}[-. ]\d{4}")
    for path in (SRC / "swarm").glob("*.py"):
        text = path.read_text()
        assert not re.search(r"\d{7,}@", text), f"SMS address literal in {path.name}"
        assert not phone_like.search(text), f"phone-like literal in {path.name}"


def _broker(tmp_path, pool=()):
    b = B.PatternBroker(host="127.0.0.1", port=0)
    b._store_path = tmp_path / "store.json"
    b.pattern_pool = list(pool)
    b.stats["start_time"] = 1.0
    return b


def test_status_keeps_existing_keys_and_adds_capabilities(tmp_path):
    status = _broker(tmp_path)._get_status()
    for key in ("type", "uptime_seconds", "connected_nodes", "pattern_pool_size",
                "total_patterns_relayed", "pattern_store_path", "nodes"):
        assert key in status
    caps = status["capabilities"]
    assert caps["relay"] is True
    assert caps["query_routing"] is False
    assert caps["model_inference"] is False


def test_status_separates_sequence_patterns_from_raw_feed_events(tmp_path):
    pool = [
        {"event_type": "trade_volume_surge", "source": "finnhub_realtime"},
        {"event_type": "trade_volume_surge", "source": "finnhub_realtime"},
        {"sequence": ["sc_a", "sc_b", "sc_c", "sc_d"], "confidence": 0.4,
         "source_node": "dvce-api"},
    ]
    status = _broker(tmp_path, pool)._get_status()
    assert status["pattern_pool_size"] == 3
    assert status["pattern_pool_breakdown"] == {
        "sequence_patterns": 1,
        "raw_events": 2,
        "by_declared_source": {"finnhub_realtime": 2, "dvce-api": 1},
    }


def test_node_expertise_is_reported_as_not_measured(tmp_path):
    b = _broker(tmp_path)
    b.nodes["n1"] = B.ConnectedNode(node_id="n1", domain="tech",
                                    expertise_scores={"tech": 0.5}, writer=None,
                                    last_heartbeat=1.0)
    node = b._get_status()["nodes"][0]
    assert node["expertise"] == {"tech": 0.5}
    assert node["expertise_measured"] is False


def test_query_reply_says_nothing_was_forwarded(tmp_path):
    b = _broker(tmp_path)
    b.nodes["n1"] = B.ConnectedNode(node_id="n1", domain="tech",
                                    expertise_scores={"tech": 0.5}, writer=None)
    loop = asyncio.new_event_loop()
    hit = loop.run_until_complete(b._route_query({"type": "query"}, "tech"))
    miss = loop.run_until_complete(b._route_query({"type": "query"}, "health"))
    loop.close()
    assert hit["routed_to"] == "n1" and hit["forwarded"] is False
    assert miss["routed_to"] is None and miss["forwarded"] is False
    assert "not forwarded" in hit["note"]
