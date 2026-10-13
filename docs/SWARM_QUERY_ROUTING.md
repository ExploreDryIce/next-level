# Swarm Query Routing (T1) — Design Note

Status: **not built.** This note says what exists, and what T1 should be when it is built.
Written 2026-10-13.

## What exists today

| Piece | What it really does |
|---|---|
| `src/swarm/broker.py` | TCP relay and heartbeat registry. Stores whatever registered clients push and relays it to connected nodes. A `query` message returns the name of the node with the highest self-declared score; the query is not forwarded and no prediction comes back. |
| `src/node/swarm_node.py` | Loads its configured checkpoint (or holds no model), registers, heartbeats. `predict()` and `extract_patterns()` exist but nothing calls them. It never reads its socket after registering, so relayed patterns are never consumed. |
| `src/integrations/dvce_swarm_bridge.py` | `SwarmPredictor` answers every prediction with the local `EventPredictor`. It queues single-observation patterns and pushes them to the broker. |
| Expertise scores | A constant each node puts in its own register message (default `{domain: 0.5}`). Not measured. |
| Node domains | `financial`, `tech`, `grid`, `comms`. These are not the model's domains, which are the vocabulary prefixes `br hw cx sc gp fn wx cy`. |

So a prediction request never leaves the machine that received it.

## Goal of T1

A caller asks one question, "what follows this event history?", and the answer comes from the node
that has been measured to be best at that kind of history — or from the local model when no node is
measurably better. Routing must never make an answer worse or slower than local-only does today.

## Inputs

A query carries:

- `query_id` — caller-generated, echoed in the reply.
- `event_history` — list of `{event_type, timestamp, severity_score}`, exactly what `EventPredictor.predict` takes.
- `top_k`.
- `vocab_hash` — SHA-256 of the caller's sorted `vocab.json`. A node only answers queries whose hash matches its own.
- `deadline_ms` — how long the caller will wait (default 50, the prediction budget).

The routing key is derived, not supplied: the **domain prefix of the last in-vocabulary event** in
`event_history` (`sc_dye_stockout` → `sc`). The last event is used because it is the one the next
event is conditioned on most directly. If no event in the history is in the vocabulary, the query is
not routed and the local model's answer is returned with `unknown_inputs: true`.

## Routing rule

The broker keeps, per node and per domain prefix, a **measured** score: top-1 accuracy on the shared
held-out set for that prefix (see prerequisites), together with the sample count and the checkpoint
hash it was measured on. Self-declared scores are ignored for routing.

1. Candidates = nodes that are heartbeating (seen in the last 2 gossip intervals), have
   `model_loaded: true`, the same `vocab_hash`, and a measured score for the key prefix with at
   least 200 held-out samples.
2. Pick the candidate with the highest measured score.
3. Route to it only if its score beats the caller's own measured score for that prefix by at least
   **3 points of top-1**. Otherwise answer locally. With today's single shared checkpoint every node
   has the same score, so nothing is routed — which is correct.
4. The caller starts local inference at the same time as it sends the query. If the routed reply
   has not arrived by `deadline_ms`, the local answer is returned.

The broker forwards the query to the chosen node's socket and relays the reply by `query_id`. One
hop only: a node never re-routes.

## Merge rule

There is no blending of probabilities across nodes in T1. Exactly one answer is returned, and it
says where it came from:

- `source: "routed"`, `node_id`, `checkpoint_hash`, `measured_top1` — the specialist's answer, unmodified.
- `source: "local"` — the local model's answer, with `route_attempted` and the reason
  (`no_better_node`, `timeout`, `vocab_mismatch`, `unknown_inputs`).

Blending two models' distributions is a separate experiment. It needs evidence that the blend beats
the better of the two on held-out data, and it is not part of T1.

`SwarmPredictor.predict` keeps its signature and return shape. The provenance fields above travel in
a side channel (an attribute such as `last_prediction_source`), so existing callers are unaffected.

## What must be true of each specialist first

A node is not eligible to receive queries until all of these hold:

1. **It loads a trained checkpoint and reports it.** `model_loaded: true` with the checkpoint path
   and hash in its status. (Loader done 2026-10-13; a node with no checkpoint reports `model: none`.)
2. **It uses the shared vocabulary.** Same `vocab_hash` as the caller. The legacy 103-type
   `experiments/models/vocab.json` does not qualify.
3. **Its checkpoint differs from the caller's for a reason.** It was trained or fine-tuned on
   domain data the generalist did not see. A copy of the production checkpoint adds nothing.
4. **Its `predict()` matches the reference encoder.** `SwarmNode.predict` builds inputs through
   `EventTokenizer`/`EventSequenceTorchDataset`, while the API uses `EventPredictor`. On the same
   weights the two agree on top-1 but not on probabilities, and the node returns nothing for
   histories shorter than 3 events. The node must call the same encoding as `EventPredictor` and
   reproduce it on a fixed reference set before it serves anyone.
5. **Its score is measured, on a leak-free split, with the causal mask the checkpoint was trained
   with.** Per-prefix top-1 on the shared held-out set, at least 200 samples per prefix, stored with
   the checkpoint hash and re-measured whenever the checkpoint changes.
6. **It beats the generalist on its own prefix** by the routing margin on that held-out set.
   Otherwise it stays a heartbeat-only node.
7. **It answers inside the budget.** p95 round trip under `deadline_ms` from the coordinator over
   the tailnet. A Raspberry Pi 3 running a tiny model may fail this and should then not be routed to.
8. **It reads its socket.** Today a node never reads after registering, so it cannot receive a
   query at all, and unread relay traffic can fill its receive buffer.
9. **Its connection is stable.** One process per `node_id`, current broker token, no re-register
   churn (the broker log shows collisions and silent drops when this is not true).

## Order of work

1. Shared held-out set and a script that writes measured per-prefix scores for a checkpoint.
2. Node: reader loop, reference-encoder `predict`, `query`/`answer` messages.
3. Broker: store measured scores, forward `query`, relay `answer` by `query_id`.
4. Bridge: speculative local inference plus the routing rule, behind a flag that defaults to off.
5. Turn the flag on only after a specialist passes items 1–9 above.

Acceptance: with the flag on, held-out top-1 on the specialist's prefix rises by at least the
routing margin, top-1 on every other prefix is unchanged, and p95 prediction latency stays under 50 ms.
