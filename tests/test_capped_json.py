import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingestion.daily_pull import _capped_json  # noqa: E402


def test_small_payload_unchanged():
    data = {"features": [1, 2, 3]}
    assert json.loads(_capped_json(data, 10_000)) == data


def test_large_payload_stays_valid_json_and_fits():
    data = {"features": [{"id": i, "text": "x" * 200} for i in range(5000)], "type": "FeatureCollection"}
    out = _capped_json(data, 200_000)
    parsed = json.loads(out)  # the old [:N] slice raised here
    assert len(out) <= 200_000
    assert parsed["_truncated"] is True and parsed["type"] == "FeatureCollection"
    assert 0 < len(parsed["features"]) < 5000


def test_top_level_list_trimmed():
    out = _capped_json([{"v": "y" * 100}] * 10_000, 50_000)
    assert len(out) <= 50_000 and isinstance(json.loads(out), list)
