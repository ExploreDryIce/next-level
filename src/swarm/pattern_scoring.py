"""Pattern Quality Scoring — Measures which cross-domain patterns actually improve predictions.

The swarm shares patterns across domains. But not all patterns are useful.
This module tracks:
1. Which patterns were shared (source domain → target domain)
2. Whether predictions improved after receiving those patterns
3. A quality score per pattern type (updated over time)

This creates a feedback loop: high-quality patterns get prioritized,
low-quality ones get filtered — the swarm gets smarter about what to share.

Architecture:
    Pattern received → prediction made → outcome observed → score updated
    
    Score = (predictions_improved / predictions_total) * confidence_weight
    confidence_weight = min(1.0, sample_count / 20)  # Need 20+ samples for full confidence

Storage: ~/.dvce/swarm/pattern_scores.json (persistent, updated every 5 minutes)

Usage:
    scorer = PatternScorer()
    
    # When a pattern is used in prediction
    scorer.record_prediction(pattern_id, domain, predicted_event, confidence)
    
    # When we learn if prediction was correct
    scorer.record_outcome(pattern_id, was_correct, actual_event)
    
    # Get pattern quality for filtering
    score = scorer.get_score(pattern_type, source_domain, target_domain)
    
    # Filter patterns before sharing
    good_patterns = scorer.filter_by_quality(patterns, min_score=0.3)
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STORE_PATH = Path.home() / ".dvce" / "swarm" / "pattern_scores.json"


@dataclass
class PatternRecord:
    """Tracks a single pattern's effectiveness over time."""
    pattern_type: str
    source_domain: str
    target_domain: str
    
    # Counts
    times_shared: int = 0
    times_used_in_prediction: int = 0
    predictions_correct: int = 0
    predictions_wrong: int = 0
    
    # Quality metrics
    accuracy: float = 0.0           # correct / total
    lift: float = 0.0               # accuracy vs. baseline (without pattern)
    confidence: float = 0.0         # How confident we are in the score (based on sample size)
    quality_score: float = 0.5      # Final composite score [0,1]
    
    # Timing
    first_seen: float = 0.0
    last_used: float = 0.0
    last_scored: float = 0.0

    def to_dict(self) -> dict:
        return {
            "pattern_type": self.pattern_type,
            "source_domain": self.source_domain,
            "target_domain": self.target_domain,
            "times_shared": self.times_shared,
            "times_used_in_prediction": self.times_used_in_prediction,
            "predictions_correct": self.predictions_correct,
            "predictions_wrong": self.predictions_wrong,
            "accuracy": self.accuracy,
            "lift": self.lift,
            "confidence": self.confidence,
            "quality_score": self.quality_score,
            "first_seen": self.first_seen,
            "last_used": self.last_used,
            "last_scored": self.last_scored,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PatternRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PendingPrediction:
    """A prediction waiting for outcome verification."""
    prediction_id: str
    pattern_type: str
    source_domain: str
    target_domain: str
    predicted_event: str
    confidence: float
    timestamp: float
    ttl: float = 3600.0  # Wait up to 1 hour for outcome


class PatternScorer:
    """Tracks and scores cross-domain pattern effectiveness.
    
    The core question: when domain A shares a pattern with domain B,
    does domain B's prediction accuracy actually improve?
    """

    def __init__(self, store_path: Optional[Path] = None):
        self.store_path = store_path or STORE_PATH
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Pattern records: key = (pattern_type, source_domain, target_domain)
        self.records: Dict[Tuple[str, str, str], PatternRecord] = {}
        
        # Pending predictions waiting for outcome
        self.pending: Dict[str, PendingPrediction] = {}
        
        # Baseline accuracy per domain (without cross-domain patterns)
        self.baselines: Dict[str, float] = {
            "financial": 0.45,
            "weather": 0.55,
            "geo": 0.40,
            "cyber": 0.35,
            "grid": 0.42,
            "political": 0.38,
        }
        
        # Cross-domain effectiveness matrix (accumulated over time)
        self.cross_domain_matrix: Dict[str, Dict[str, float]] = defaultdict(
            lambda: defaultdict(lambda: 0.5)
        )
        
        self._dirty = False
        self._load()

    # ─── Recording Events ────────────────────────────────────────

    def record_pattern_shared(self, pattern_type: str, source_domain: str, target_domain: str):
        """Record that a pattern was shared from one domain to another."""
        key = (pattern_type, source_domain, target_domain)
        record = self._get_or_create(key)
        record.times_shared += 1
        if record.first_seen == 0:
            record.first_seen = time.time()
        self._dirty = True

    def record_prediction(
        self,
        prediction_id: str,
        pattern_type: str,
        source_domain: str,
        target_domain: str,
        predicted_event: str,
        confidence: float,
    ):
        """Record that a prediction was made using a cross-domain pattern.
        
        Call this when the predictor uses patterns from another domain.
        Later, call record_outcome() when we know if the prediction was correct.
        """
        key = (pattern_type, source_domain, target_domain)
        record = self._get_or_create(key)
        record.times_used_in_prediction += 1
        record.last_used = time.time()
        self._dirty = True

        # Store pending prediction
        self.pending[prediction_id] = PendingPrediction(
            prediction_id=prediction_id,
            pattern_type=pattern_type,
            source_domain=source_domain,
            target_domain=target_domain,
            predicted_event=predicted_event,
            confidence=confidence,
            timestamp=time.time(),
        )

    def record_outcome(
        self,
        prediction_id: str,
        was_correct: bool,
        actual_event: Optional[str] = None,
    ):
        """Record whether a prediction turned out to be correct.
        
        This closes the feedback loop — we now know if the cross-domain
        pattern actually helped.
        """
        pending = self.pending.pop(prediction_id, None)
        if pending is None:
            return  # No matching prediction

        key = (pending.pattern_type, pending.source_domain, pending.target_domain)
        record = self._get_or_create(key)

        if was_correct:
            record.predictions_correct += 1
        else:
            record.predictions_wrong += 1

        # Recalculate scores
        self._rescore(record)
        self._dirty = True

    # ─── Scoring ─────────────────────────────────────────────────

    def _rescore(self, record: PatternRecord):
        """Recalculate quality score for a pattern record."""
        total = record.predictions_correct + record.predictions_wrong
        if total == 0:
            record.quality_score = 0.5  # Unknown = neutral
            return

        # Accuracy
        record.accuracy = record.predictions_correct / total

        # Confidence (need 20+ samples for full confidence)
        record.confidence = min(1.0, total / 20.0)

        # Lift vs. baseline
        baseline = self.baselines.get(record.target_domain, 0.4)
        if baseline > 0:
            record.lift = (record.accuracy - baseline) / baseline
        else:
            record.lift = 0.0

        # Composite quality score
        # = accuracy weighted by confidence, with bonus for positive lift
        raw_score = record.accuracy * record.confidence
        lift_bonus = max(0, record.lift * 0.2)  # Up to +20% for positive lift
        record.quality_score = min(1.0, raw_score + lift_bonus)
        record.last_scored = time.time()

        # Update cross-domain matrix
        self.cross_domain_matrix[record.source_domain][record.target_domain] = record.quality_score

    def get_score(
        self, pattern_type: str, source_domain: str, target_domain: str
    ) -> float:
        """Get the quality score for a specific pattern type + domain pair."""
        key = (pattern_type, source_domain, target_domain)
        record = self.records.get(key)
        if record:
            return record.quality_score
        return 0.5  # Unknown pattern = neutral score

    def get_domain_pair_score(self, source_domain: str, target_domain: str) -> float:
        """Get the aggregate quality score for a domain pair (all pattern types)."""
        relevant = [
            r for (_, sd, td), r in self.records.items()
            if sd == source_domain and td == target_domain
        ]
        if not relevant:
            return 0.5

        # Weighted average by sample count
        total_samples = sum(r.predictions_correct + r.predictions_wrong for r in relevant)
        if total_samples == 0:
            return 0.5

        weighted_sum = sum(
            r.quality_score * (r.predictions_correct + r.predictions_wrong)
            for r in relevant
        )
        return weighted_sum / total_samples

    # ─── Filtering ───────────────────────────────────────────────

    def filter_by_quality(
        self, patterns: List[dict], min_score: float = 0.3, target_domain: Optional[str] = None
    ) -> List[dict]:
        """Filter patterns, keeping only those above the quality threshold.
        
        Patterns with no score history are kept (benefit of the doubt).
        Only patterns with proven low quality get filtered out.
        """
        filtered = []
        for pattern in patterns:
            p_type = pattern.get("event_type", pattern.get("pattern_type", "unknown"))
            source = pattern.get("domain", pattern.get("source_domain", "unknown"))
            target = target_domain or "general"

            score = self.get_score(p_type, source, target)

            # Keep if score is above threshold OR if we don't have enough data
            key = (p_type, source, target)
            record = self.records.get(key)
            if record is None or record.confidence < 0.5:
                # Not enough data — keep it (don't filter unknowns)
                filtered.append(pattern)
            elif score >= min_score:
                filtered.append(pattern)
            else:
                logger.debug(f"Filtered low-quality pattern: {p_type} ({source}→{target}) score={score:.2f}")

        removed = len(patterns) - len(filtered)
        if removed > 0:
            logger.info(f"Pattern quality filter: kept {len(filtered)}/{len(patterns)} (removed {removed} low-quality)")

        return filtered

    # ─── Reporting ───────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of pattern quality scores."""
        if not self.records:
            return {"total_records": 0, "message": "No patterns scored yet"}

        scored = [r for r in self.records.values() if r.predictions_correct + r.predictions_wrong > 0]
        
        return {
            "total_records": len(self.records),
            "scored_records": len(scored),
            "avg_quality": (
                sum(r.quality_score for r in scored) / len(scored) if scored else 0
            ),
            "best_patterns": sorted(
                [r.to_dict() for r in scored if r.confidence > 0.5],
                key=lambda x: x["quality_score"],
                reverse=True,
            )[:10],
            "worst_patterns": sorted(
                [r.to_dict() for r in scored if r.confidence > 0.5],
                key=lambda x: x["quality_score"],
            )[:5],
            "cross_domain_matrix": dict(self.cross_domain_matrix),
            "domain_baselines": self.baselines,
        }

    def get_cross_domain_report(self) -> str:
        """Human-readable report of which domain pairs work well together."""
        lines = ["Cross-Domain Pattern Effectiveness:", "=" * 50, ""]
        lines.append(f"{'Source → Target':<30} {'Score':>8} {'Samples':>10} {'Lift':>8}")
        lines.append("-" * 60)

        pairs = []
        for (ptype, sd, td), record in self.records.items():
            total = record.predictions_correct + record.predictions_wrong
            if total > 0:
                pairs.append((sd, td, record.quality_score, total, record.lift))

        # Aggregate by domain pair
        pair_agg: Dict[Tuple[str, str], List] = defaultdict(list)
        for sd, td, score, n, lift in pairs:
            pair_agg[(sd, td)].append((score, n, lift))

        for (sd, td), entries in sorted(pair_agg.items(), key=lambda x: -max(e[0] for e in x[1])):
            avg_score = sum(e[0] for e in entries) / len(entries)
            total_n = sum(e[1] for e in entries)
            avg_lift = sum(e[2] for e in entries) / len(entries)
            quality = "🟢" if avg_score > 0.6 else "🟡" if avg_score > 0.4 else "🔴"
            lines.append(f"{quality} {sd:>12} → {td:<12} {avg_score:>7.2f} {total_n:>10} {avg_lift:>+7.1%}")

        lines.append("")
        lines.append("🟢 = High quality (>0.6)  🟡 = Mixed (0.4-0.6)  🔴 = Low quality (<0.4)")
        return "\n".join(lines)

    # ─── Persistence ─────────────────────────────────────────────

    def _get_or_create(self, key: Tuple[str, str, str]) -> PatternRecord:
        if key not in self.records:
            self.records[key] = PatternRecord(
                pattern_type=key[0],
                source_domain=key[1],
                target_domain=key[2],
                first_seen=time.time(),
            )
        return self.records[key]

    def _load(self):
        """Load scores from disk."""
        if not self.store_path.exists():
            return

        try:
            data = json.loads(self.store_path.read_text())
            for entry in data.get("records", []):
                record = PatternRecord.from_dict(entry)
                key = (record.pattern_type, record.source_domain, record.target_domain)
                self.records[key] = record

            self.baselines.update(data.get("baselines", {}))
            logger.info(f"Loaded {len(self.records)} pattern score records from disk")
        except Exception as e:
            logger.warning(f"Failed to load pattern scores: {e}")

    def save(self):
        """Save scores to disk."""
        data = {
            "records": [r.to_dict() for r in self.records.values()],
            "baselines": self.baselines,
            "cross_domain_matrix": dict(self.cross_domain_matrix),
            "saved_at": time.time(),
        }
        try:
            self.store_path.write_text(json.dumps(data, indent=2))
            self._dirty = False
        except Exception as e:
            logger.error(f"Failed to save pattern scores: {e}")

    def cleanup_pending(self):
        """Remove expired pending predictions."""
        now = time.time()
        expired = [
            pid for pid, p in self.pending.items()
            if now - p.timestamp > p.ttl
        ]
        for pid in expired:
            # Treat expired predictions as incorrect (we didn't observe the event)
            self.record_outcome(pid, was_correct=False)
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired pending predictions")


# ─── Integration with Broker ─────────────────────────────────────────────────

class ScoringBrokerMixin:
    """Mixin to add pattern scoring to the PatternBroker.
    
    Usage: Add this to the broker's broadcast logic to score and filter.
    
    Example:
        scorer = PatternScorer()
        
        # Before broadcasting:
        patterns = scorer.filter_by_quality(patterns, target_domain=node.domain)
        
        # After prediction outcome:
        scorer.record_outcome(prediction_id, was_correct=True)
        
        # Periodic save:
        scorer.save()
    """
    pass


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    scorer = PatternScorer()
    
    print(scorer.get_cross_domain_report())
    print()
    
    summary = scorer.get_summary()
    print(f"Total records: {summary['total_records']}")
    print(f"Scored records: {summary.get('scored_records', 0)}")
    print(f"Average quality: {summary.get('avg_quality', 0):.3f}")
