"""A swarm node loads a real trained checkpoint or says plainly that it has none.

Before this, the Mac node built a "large" model from a fixed size table, found
no checkpoint, and ran on random weights with a 103-type vocab while reporting
itself as a prediction node. These tests pin the replacement behaviour:

- a checkpoint that records its own architecture (like production, which fits
  no entry in the size table) loads exactly, with its own vocab ids;
- a configured checkpoint that is missing or does not match stops the node;
- a node with no checkpoint configured has no model at all, and says so.

The checkpoints here are tiny throwaway models written to tmp_path. Nothing
reads or writes ~/.dvce/models except the last test, which only reads and is
skipped when the production bundle is absent.
"""

import json
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "node"))

import swarm_node as SN  # noqa: E402
from config import NodeConfig, PRODUCTION_MODEL_DIR, mac_node_config  # noqa: E402

from dvce.services.event_prediction.torch_model import (  # noqa: E402
    EventTransformerTorch,
    TorchModelConfig,
)

TYPES = ["<PAD>", "<BOS>", "<EOS>", "<UNK>", "sc_port_closure", "sc_lead_time_increase",
         "wx_hurricane", "fn_rate_hike"]
# Deliberately not a row of LEGACY_MODEL_SIZES, like the production checkpoint.
ARCH = {"d_model": 24, "n_heads": 3, "n_layers": 1, "d_ff": 48, "time_encoding_dim": 12}


def _write_bundle(directory: Path, *, causal_memory=True, vocab_types=TYPES, save_arch=True):
    """Write best_model.pt + vocab.json the way the DVCE trainer does."""
    directory.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(7)
    cfg = TorchModelConfig(vocab_size=len(TYPES), context_dim=64, max_seq_len=256,
                           causal_memory=causal_memory, **ARCH)
    model = EventTransformerTorch(cfg)
    saved_cfg = {"vocab_size": len(TYPES), "context_dim": 64, "max_seq_len": 256,
                 "causal_memory": causal_memory}
    if save_arch:
        saved_cfg.update(ARCH)
    torch.save({"model_state_dict": model.state_dict(), "config": saved_cfg},
               directory / "best_model.pt")
    (directory / "vocab.json").write_text(json.dumps({t: i for i, t in enumerate(vocab_types)}))
    return model


def _node(**overrides) -> SN.SwarmNode:
    config = NodeConfig(node_id="test-node", node_name="Test", domain="supply_chain",
                        device="cpu", **overrides)
    node = SN.SwarmNode(config)
    node.device = "cpu"
    return node


def test_loads_checkpoint_with_its_own_architecture_and_vocab(tmp_path):
    trained = _write_bundle(tmp_path / "bundle")
    node = _node(model_dir=str(tmp_path / "bundle"), model_size="large")
    node._load_model()

    # Architecture came from the checkpoint, not from model_size="large".
    assert node.model.config.d_model == 24
    assert node.model.config.n_layers == 1
    assert node.model.config.causal_memory is True
    # Weights are the trained ones, not a fresh initialisation.
    loaded = node.model.state_dict()
    for name, tensor in trained.state_dict().items():
        assert torch.equal(loaded[name], tensor), name
    # Vocab ids are the checkpoint's embedding rows.
    assert node.tokenizer.vocabulary.encode("sc_lead_time_increase") == 5
    assert node.tokenizer.vocabulary.decode(6) == "wx_hurricane"
    assert node.tokenizer.vocabulary.encode("not_a_known_type") == 3  # <UNK>, vocab frozen

    status = node.get_status()
    assert status["model_loaded"] is True
    assert status["model_checkpoint"] == str(tmp_path / "bundle" / "best_model.pt")
    assert status["model_vocab_size"] == len(TYPES)


def test_checkpoint_without_causal_flag_runs_without_the_mask(tmp_path):
    _write_bundle(tmp_path / "bundle", causal_memory=False)
    node = _node(model_dir=str(tmp_path / "bundle"))
    node._load_model()
    assert node.model.config.causal_memory is False


def test_configured_but_missing_checkpoint_stops_the_node(tmp_path):
    node = _node(model_dir=str(tmp_path / "does-not-exist"))
    with pytest.raises(SN.ModelNotLoadedError, match="Refusing to start with random weights"):
        node._load_model()
    assert node.model is None
    assert node.get_status()["model_loaded"] is False


def test_missing_vocab_stops_the_node(tmp_path):
    _write_bundle(tmp_path / "bundle")
    (tmp_path / "bundle" / "vocab.json").unlink()
    with pytest.raises(SN.ModelNotLoadedError, match="Vocabulary not found"):
        _node(model_dir=str(tmp_path / "bundle"))._load_model()


def test_vocab_of_the_wrong_size_stops_the_node(tmp_path):
    _write_bundle(tmp_path / "bundle", vocab_types=TYPES + ["cy_ransomware"])
    node = _node(model_dir=str(tmp_path / "bundle"))
    with pytest.raises(SN.ModelNotLoadedError, match="Vocabulary/checkpoint mismatch"):
        node._load_model()
    assert node.model is None


def test_checkpoint_that_does_not_fit_its_architecture_stops_the_node(tmp_path):
    # No dims saved, so the size table is used — and "tiny" is not this model.
    _write_bundle(tmp_path / "bundle", save_arch=False)
    node = _node(model_dir=str(tmp_path / "bundle"), model_size="tiny")
    with pytest.raises(SN.ModelNotLoadedError, match="does not fit"):
        node._load_model()
    assert node.model is None


def test_node_with_no_checkpoint_configured_has_no_model(tmp_path, caplog):
    node = _node()
    with caplog.at_level("WARNING"):
        node._load_model()

    assert node.model is None  # not a randomly initialised stand-in
    assert "NO MODEL" in caplog.text
    status = node.get_status()
    assert status["model_loaded"] is False
    assert status["model_checkpoint"] is None
    assert status["role"] == "heartbeat-only"
    assert status["expertise_measured"] is False
    with pytest.raises(SN.ModelNotLoadedError):
        node.predict([{"event_type": "sc_port_closure"}] * 3)
    with pytest.raises(SN.ModelNotLoadedError):
        node.extract_patterns([[{"event_type": "sc_port_closure"}] * 5])


def test_predict_returns_event_type_names_from_the_loaded_vocab(tmp_path):
    _write_bundle(tmp_path / "bundle")
    node = _node(model_dir=str(tmp_path / "bundle"))
    node._load_model()
    history = [{"event_type": t, "timestamp": 1000.0 + 60 * i}
               for i, t in enumerate(["sc_port_closure", "wx_hurricane", "fn_rate_hike"])]
    predictions = node.predict(history, top_k=3)
    assert len(predictions) == 3
    assert all(p["event_type"] in TYPES for p in predictions)


def test_explicit_model_path_uses_sibling_vocab(tmp_path):
    _write_bundle(tmp_path / "bundle")
    node = _node(model_path=str(tmp_path / "bundle" / "best_model.pt"))
    assert SN.resolve_model_files(node.config) == (
        tmp_path / "bundle" / "best_model.pt", tmp_path / "bundle" / "vocab.json")
    node._load_model()
    assert node.get_status()["model_loaded"] is True


def test_vocab_with_gaps_or_no_special_tokens_is_rejected(tmp_path):
    gappy = tmp_path / "gappy.json"
    gappy.write_text(json.dumps({"<PAD>": 0, "<BOS>": 1, "<EOS>": 2, "<UNK>": 3, "sc_x": 9}))
    with pytest.raises(SN.ModelNotLoadedError, match="contiguous"):
        SN.load_type_to_id(gappy)
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps({"type_to_id": {"sc_x": 0, "sc_y": 1}}))
    with pytest.raises(SN.ModelNotLoadedError, match="special tokens"):
        SN.load_type_to_id(bare)


def test_mac_profile_points_at_the_production_bundle(monkeypatch, tmp_path):
    monkeypatch.delenv("DVCE_NODE_MODEL_DIR", raising=False)
    assert mac_node_config().model_dir == str(PRODUCTION_MODEL_DIR)
    monkeypatch.setenv("DVCE_NODE_MODEL_DIR", str(tmp_path))
    assert mac_node_config().model_dir == str(tmp_path)


def test_mac_node_exits_nonzero_when_the_bundle_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DVCE_NODE_MODEL_DIR", str(tmp_path / "gone"))
    monkeypatch.setattr(sys, "argv", ["swarm_node.py", "--profile", "mac"])
    with pytest.raises(SystemExit) as exit_info:
        SN.main()
    assert exit_info.value.code == 2


@pytest.mark.skipif(not (PRODUCTION_MODEL_DIR / "best_model.pt").exists(),
                    reason="production bundle not present on this machine")
def test_production_bundle_loads_read_only():
    node = _node(model_dir=str(PRODUCTION_MODEL_DIR), model_size="large")
    node._load_model()
    info = node.model_info
    assert info["loaded"] is True
    assert info["vocab_size"] == node.model.config.vocab_size
    saved = torch.load(PRODUCTION_MODEL_DIR / "best_model.pt", map_location="cpu")
    assert bool(saved["config"].get("causal_memory")) == info["causal_memory"]
    loaded = node.model.state_dict()
    for name, tensor in saved["model_state_dict"].items():
        assert torch.equal(loaded[name], tensor), name
