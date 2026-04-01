# Feature Flags Platform

## Vision
Production-grade feature flags platform built from scratch — enabling safe deploys via
rollout percentages, targeting rules, and environment overrides. Zero vendor lock-in,
full observability, sub-millisecond evaluation latency.

## Core Value Proposition
- **Evaluation < 1ms** — In-memory evaluation, zero I/O per request
- **Deterministic rollout** — MurmurHash3 ensures consistent user bucketing across restarts
- **Audit trail** — Immutable, transactional audit log for every state change
- **Pub/sub invalidation** — Redis pub/sub keeps all replicas in sync in < 100ms

## Tech Stack
- FastAPI (async-first, no sync endpoints)
- PostgreSQL + SQLAlchemy 2 async
- Redis (pub/sub invalidation, not polling)
- Pydantic v2
- Prometheus + prometheus-fastapi-instrumentator
- Python 3.12

## Primary Users
Backend engineers and platform teams needing canary releases, A/B testing,
and kill switches without adopting external SaaS.

## Success Criteria
1. `docker-compose up` boots everything (API + PostgreSQL + Redis)
2. `/api/v1/evaluate` p99 < 1ms (in-memory, warm cache)
3. Full test suite passes: unit + integration + consistency + security + performance
4. `bandit` + `semgrep` scans pass with zero high-severity findings
5. SDK installable via `pip install -e ./sdk`
6. 3 ADRs documenting key architectural decisions

## Out of Scope (v1)
- Multi-tenancy / organizations
- A/B test analytics / statistics engine
- Self-hosted UI dashboard
- OpenFeature SDK compatibility layer
