# Requirements: Swarm Persistence, Continuous Training & NATS Upgrade

## Introduction

The swarm currently loses all pattern intelligence on broker restart, doesn't automatically retrain on new data, and uses a simple TCP protocol that won't scale. These three improvements make the swarm a living, self-improving system: patterns persist across restarts, new data triggers retraining, and the communication layer is production-ready.

## Glossary

- **Pattern_Store**: Persistent JSON file on disk where the broker saves all accumulated patterns
- **Training_Loop**: Automated nightly process on TerrorNode that retrains specialist models using new patterns + fresh live data
- **NATS_Broker**: NATS JetStream message broker replacing the custom TCP broker, providing persistence, replay, and pub/sub

## Requirements

### Requirement 1: Broker Pattern Persistence

**User Story:** As the swarm network, I need patterns to survive broker restarts, so that accumulated intelligence isn't lost when the coordinator reboots.

#### Acceptance Criteria

1. WHEN the broker receives patterns from any node, IT SHALL append them to a Pattern_Store file on disk within 5 seconds
2. WHEN the broker starts, IT SHALL load all non-expired patterns from the Pattern_Store into its in-memory pool
3. THE Pattern_Store SHALL be a JSON file at `~/.dvce/swarm/pattern_store.json` containing all patterns with their metadata (source, timestamp, confidence, TTL)
4. WHEN a pattern's TTL expires, THE broker SHALL remove it from the Pattern_Store during the next cleanup cycle (hourly)
5. THE Pattern_Store SHALL support at least 50,000 patterns without performance degradation on read/write

### Requirement 2: Snapshot Feedback Loop

**User Story:** As the DVCE platform, I want every prediction to generate patterns that flow back to the swarm, so that the system gets smarter with every API call.

#### Acceptance Criteria

1. WHEN the Snapshot Engine runs a prediction via get_predictor(), IT SHALL extract patterns from any prediction with confidence > 0.5 and queue them for sharing
2. WHEN 10 or more patterns are queued OR 5 minutes have elapsed since last flush, THE Snapshot Engine SHALL flush patterns to the broker via the SwarmPredictor.flush_patterns_to_swarm() method
3. WHEN patterns are flushed successfully, THE Snapshot Engine SHALL log the count and reset the queue
4. THE feedback loop SHALL operate asynchronously so it never blocks the API response

### Requirement 3: TerrorNode Nightly Training

**User Story:** As the swarm, I want TerrorNode to retrain its specialist model nightly using new patterns and fresh data, so that predictions improve continuously without manual intervention.

#### Acceptance Criteria

1. THE Training_Loop SHALL run as a Windows Scheduled Task on TerrorNode at 02:00 local time every night
2. THE Training_Loop SHALL load all foreign patterns received in the last 24 hours from the node's cached pattern file
3. THE Training_Loop SHALL combine foreign patterns with the latest training data from `E:\dvce-data\training\` to create an augmented training set
4. THE Training_Loop SHALL fine-tune the current specialist model for 5 epochs on the augmented data using CUDA
5. WHEN training completes, THE Training_Loop SHALL save the updated model checkpoint and update the node's expertise scores based on validation accuracy
6. THE Training_Loop SHALL push updated expertise scores to the broker on next heartbeat

### Requirement 4: NATS JetStream Migration

**User Story:** As the swarm network, I need a production-grade message broker that handles persistence, replay, and reconnection automatically, so that the network is resilient to outages.

#### Acceptance Criteria

1. THE broker SHALL be replaced with a NATS server running JetStream, with subjects: `swarm.patterns.>`, `swarm.queries.>`, `swarm.status.>`
2. EACH node SHALL publish patterns to `swarm.patterns.{domain}` and subscribe to `swarm.patterns.*` for cross-domain pattern reception
3. JetStream SHALL persist all pattern messages with a 7-day retention policy, so nodes that reconnect after downtime receive missed patterns
4. WHEN a node disconnects and reconnects, IT SHALL receive all patterns published since its last acknowledged message (automatic replay)
5. THE migration SHALL maintain backward compatibility: nodes can connect via either TCP (legacy) or NATS, with a 30-day transition period
6. NATS SHALL run on the Mac coordinator as a single-node server (upgradeable to cluster later)

## Timeline

- Requirement 1 (broker persistence): This session — immediate impact
- Requirement 2 (feedback loop): This session — wires snapshot to swarm
- Requirement 3 (nightly training): Deploy script to MSI — runs unattended
- Requirement 4 (NATS): Next session — biggest change, needs NATS installed
