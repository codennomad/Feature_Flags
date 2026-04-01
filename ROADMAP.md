# Roadmap — Feature Flags Platform

## Milestone: v1.0.0 — Production-Ready Feature Flags

### Phase 1 — Project Foundation
**Status:** ⬜ not started
**Requirements:** R12 (infra), R09 (observability base)
**Deliverables:**
- `feature-flags/` directory structure (all src/ and sdk/ dirs)
- `pyproject.toml` with all dependencies
- `Makefile` with all targets
- `src/config.py` — Pydantic Settings
- `src/infra/database.py` — async engine + session factory
- `src/infra/redis.py` — connection pool + pub/sub skeleton
- `src/infra/metrics.py` — all Prometheus metrics registered
- `docker-compose.yml` — api + postgres + redis
- `alembic.ini` + `migrations/` — Alembic setup
- `.env.example`

---

### Phase 2 — Data Models + Schemas
**Status:** ⬜ not started
**Requirements:** R04, R05 (data contracts)
**Deliverables:**
- `src/models/flag.py` — Flag SQLAlchemy model (UUID, JSONB)
- `src/models/audit.py` — AuditLog (immutable, no update/delete)
- `src/models/environment.py` — EnvironmentConfig dataclass
- `src/schemas/flag.py` — Pydantic v2 request/response schemas
- `src/schemas/evaluation.py` — EvaluationContext, EvaluationResult
- Alembic migration: `001_initial_schema.py`

---

### Phase 3 — Core Engine
**Status:** ⬜ not started
**Requirements:** R01, R02, R03, R05
**Deliverables:**
- `src/core/hashing.py` — `compute_rollout_hash()` with mmh3
- `src/core/targeting.py` — all 10 operators + AND/OR combinator
- `src/core/cache.py` — FlagCache (warm_up, get, invalidate, is_ready)
- `src/core/evaluation.py` — EvaluationEngine (zero I/O, precedence order)
- All core metrics instrumented

---

### Phase 4 — API Layer
**Status:** ⬜ not started
**Requirements:** R06, R07, R08
**Deliverables:**
- `src/api/deps.py` — get_session, get_current_user, require_role
- `src/api/v1/flags.py` — CRUD + enable/disable + rules CRUD
- `src/api/v1/evaluation.py` — POST /evaluate + POST /evaluate/batch
- `src/api/v1/environments.py` — environment management
- `src/api/v1/webhooks.py` — registration + dispatch with retry
- `src/api/v1/audit.py` — GET /flags/{key}/audit (read-only)
- JWT auth middleware (HS256, reject alg=none)
- Rate limiting (slowapi)

---

### Phase 5 — App Factory + Lifespan
**Status:** ⬜ not started
**Requirements:** R09 (full metrics), R03 (startup order)
**Deliverables:**
- `src/main.py` — FastAPI factory, lifespan (startup order documented), CORS, error handlers
- Prometheus endpoint `/metrics`
- Health endpoint `/api/v1/health`
- Structured logging (no token leakage in logs)
- Error handlers that never expose stack traces

---

### Phase 6 — SDK
**Status:** ⬜ not started
**Requirements:** R10
**Deliverables:**
- `sdk/feature_flags_sdk/client.py` — FlagClient (thread-safe, async-safe)
- `sdk/feature_flags_sdk/cache.py` — TTL cache
- `sdk/feature_flags_sdk/models.py` — SDK response models
- `sdk/pyproject.toml` — installable package
- Silent failure (never raises to caller)

---

### Phase 7 — Test Suite
**Status:** ⬜ not started
**Requirements:** R11
**Deliverables:**
- `tests/conftest.py` + `tests/factories.py` + `tests/utils/`
- `tests/unit/core/` — test_evaluation.py, test_hashing.py, test_targeting.py, test_cache.py
- `tests/unit/schemas/test_validation.py`
- `tests/integration/` — test_api_flags.py, test_api_evaluation.py, test_pubsub_invalidation.py, test_audit_log.py, test_webhook.py
- `tests/consistency/` — concurrent evaluation + cache race + rollout distribution
- `tests/security/` — injection, authn/authz, input validation, rate limiting, audit tampering, sensitive data
- `tests/performance/` — test_evaluation_latency.py, locustfile.py, benchmark_hashing.py

---

### Phase 8 — CI/CD + ADRs + Polish
**Status:** ⬜ not started
**Requirements:** R12, R13
**Deliverables:**
- `.github/workflows/test.yml` — full CI pipeline
- `docs/adr/001-why-not-launchdarkly.md`
- `docs/adr/002-eventual-consistency-tradeoff.md`
- `docs/adr/003-deterministic-hashing.md`
- `src/scripts/seed.py` — seed flags + rules
- `make security-scan` passing (bandit + safety + pip-audit)
- README.md with quickstart

---

## Phase Dependencies
```
Phase 1 (Foundation)
    └─► Phase 2 (Models + Schemas)
            └─► Phase 3 (Core Engine)
                    └─► Phase 4 (API Layer)
                            └─► Phase 5 (App Factory)
                                    ├─► Phase 6 (SDK)
                                    └─► Phase 7 (Tests)
                                            └─► Phase 8 (CI/CD + ADRs)
```
