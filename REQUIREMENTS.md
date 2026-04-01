# Requirements — Feature Flags Platform

## v1 Requirements (this milestone)

### R01 — Evaluation Engine
- [ ] R01.1: Evaluate flags in-memory with zero I/O per request
- [ ] R01.2: Precedence order: override > targeting > rollout > default (documented + tested)
- [ ] R01.3: Return `EvaluationResult` with `value`, `reason`, `flag_key`, `environment`
- [ ] R01.4: Reasons: OVERRIDE, TARGETING_MATCH, ROLLOUT, DEFAULT, FLAG_DISABLED

### R02 — Deterministic Hash Rollout
- [ ] R02.1: Use `mmh3.hash(f"{flag_key}:{user_id}", seed=42) % 10000`
- [ ] R02.2: Same inputs → same result always (cross-process, cross-restart)
- [ ] R02.3: Distribution test: 100k users at 50% → 49–51% inclusion
- [ ] R02.4: Different flags same user → independent distributions

### R03 — Local Cache + Pub/Sub Invalidation
- [ ] R03.1: Cache warm-up on startup (load all flags from DB before accepting requests)
- [ ] R03.2: Invalidation via Redis pub/sub channel `feature_flags:invalidate`
- [ ] R03.3: `CacheNotReadyError` raised if evaluate called before warm-up complete
- [ ] R03.4: asyncio.Lock (non-blocking) for all cache writes
- [ ] R03.5: Background task (asyncio) for pub/sub subscriber

### R04 — Data Models
- [ ] R04.1: Flag model: id(UUID), key(slug, immutable), name, description, flag_type, default_value(JSONB), environments(JSONB), version, created_by, timestamps
- [ ] R04.2: AuditLog model: immutable (no UPDATE/DELETE), flag_id FK, action, actor, changes(JSONB), metadata(JSONB)
- [ ] R04.3: Every flag mutation creates audit entry in same transaction
- [ ] R04.4: EnvironmentConfig embedded in JSONB: enabled, override, rollout_percentage, rules

### R05 — Targeting Rules
- [ ] R05.1: Operators: eq, neq, in, not_in, contains, starts_with, gt, gte, lt, lte
- [ ] R05.2: Condition combinators: AND / OR
- [ ] R05.3: Priority-ordered rules (lower number = higher priority, first match wins)
- [ ] R05.4: Rule structure: id, name, priority, conditions[], condition_combinator, serve

### R06 — REST API Endpoints
- [ ] R06.1: POST/GET/PATCH/DELETE /api/v1/flags
- [ ] R06.2: POST /api/v1/flags/{key}/environments/{env}/enable|disable
- [ ] R06.3: POST/PUT/DELETE /api/v1/flags/{key}/rules/{rule_id}
- [ ] R06.4: POST /api/v1/evaluate + POST /api/v1/evaluate/batch
- [ ] R06.5: GET /api/v1/flags/{key}/audit
- [ ] R06.6: GET /api/v1/health + GET /metrics

### R07 — Authentication & Authorization
- [ ] R07.1: JWT Bearer token required for all endpoints
- [ ] R07.2: alg=none attack explicitly rejected
- [ ] R07.3: Expired JWT → 401 (no clock tolerance)
- [ ] R07.4: Roles: viewer (read-only), editor (CRUD flags), admin (all)
- [ ] R07.5: viewer cannot POST/PATCH/DELETE → 403

### R08 — Webhooks
- [ ] R08.1: Fire on flag.enabled / flag.disabled
- [ ] R08.2: Payload: flag_key, environment, actor, timestamp, previous_state
- [ ] R08.3: Exponential backoff: 3 retries, delays 1s / 5s / 25s
- [ ] R08.4: Timeout per request: 5s
- [ ] R08.5: asyncio.create_task (non-blocking response)
- [ ] R08.6: Persist failed attempts for reprocessing

### R09 — Observability
- [ ] R09.1: Prometheus metrics: flag_evaluation_duration_seconds (histogram ≤1ms buckets)
- [ ] R09.2: flag_evaluation_total (labels: flag_key, result, reason)
- [ ] R09.3: cache_hit_total / cache_miss_total / cache_size_flags
- [ ] R09.4: pubsub_invalidations_total / pubsub_lag_seconds
- [ ] R09.5: webhook_dispatch_total / webhook_dispatch_duration_seconds
- [ ] R09.6: db_pool_size / db_pool_checked_out

### R10 — SDK
- [ ] R10.1: `FlagClient.is_enabled(flag_key, user_id)` → bool
- [ ] R10.2: `FlagClient.get_variant(flag_key, user_id, attributes)` → Any
- [ ] R10.3: Local TTL cache (default 30s)
- [ ] R10.4: Never raises exception to caller (silent default + warning log)
- [ ] R10.5: Thread-safe / async-safe
- [ ] R10.6: Installable via `pip install -e ./sdk`

### R11 — Testing
- [ ] R11.1: Unit tests: evaluation precedence, hashing uniformity, targeting operators, cache state machine
- [ ] R11.2: Integration tests: API with real DB, pub/sub full flow, audit log transactional
- [ ] R11.3: Consistency tests: 1000 concurrent evaluations during cache invalidation
- [ ] R11.4: Security tests: SQL injection payloads, JWT alg=none, rate limiting, audit immutability
- [ ] R11.5: Performance tests: p50 < 0.1ms, p95 < 0.5ms, p99 < 1ms
- [ ] R11.6: Coverage ≥ 85%

### R12 — Infrastructure
- [ ] R12.1: docker-compose.yml with api + postgres + redis
- [ ] R12.2: Alembic migrations (make migrate)
- [ ] R12.3: Seed script (make seed)
- [ ] R12.4: Makefile targets: dev, test, migrate, seed, lint, security-scan
- [ ] R12.5: GitHub Actions CI: unit → consistency → security → performance

### R13 — Documentation
- [ ] R13.1: ADR 001: why-not-launchdarkly.md
- [ ] R13.2: ADR 002: eventual-consistency-tradeoff.md
- [ ] R13.3: ADR 003: deterministic-hashing.md

## v2 (out of scope now)
- Multi-tenancy
- Analytics dashboard
- OpenFeature compatibility
- GeoIP targeting operator
