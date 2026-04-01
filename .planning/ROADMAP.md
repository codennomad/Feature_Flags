# Roadmap: Feature Flags Platform

## Overview

Plataforma de feature flags production-grade construída com FastAPI async, PostgreSQL, Redis pub/sub, SDK Python e suite de testes de nível sênior. O sistema avalia flags em < 1ms sem I/O e invalida cache via pub/sub em < 100ms.

## Phases

- [x] **Phase 1: Foundation** - GSD setup + project scaffold
- [x] **Phase 2: Models + Schemas** - SQLAlchemy models + Pydantic v2 schemas
- [x] **Phase 3: Core Engine** - Motor de avaliação + hashing + targeting + cache
- [x] **Phase 4: API Layer** - REST endpoints + JWT auth + rate limiting
- [x] **Phase 5: App Factory** - main.py + lifespan + infra completa
- [x] **Phase 6: SDK** - Python SDK thread-safe + TTL cache
- [x] **Phase 7: Tests** - Suite completa unit/consistency/security/performance
- [x] **Phase 8: CI/CD** - GitHub Actions + 3 ADRs + seed script
- [x] **Phase 9: Gap Closure** - Fechar lacunas vs prompt.md: environments.py, sdk/models.py, docker-compose.yml, métricas pubsub_lag + webhook_duration

## Phase Details

### Phase 1: Foundation
**Goal**: GSD setup + scaffold inicial com git
**Depends on**: Nothing
**Success Criteria**:
  1. .github/GSD instalado
  2. Estrutura de diretórios criada
**Plans**: 1 plan
Plans:
- [x] 01-01: GSD setup + project scaffold

### Phase 2: Models + Schemas
**Goal**: SQLAlchemy 2 async models + Pydantic v2 schemas
**Depends on**: Phase 1
**Success Criteria**:
  1. Flag, AuditLog, Webhook models criados
  2. Pydantic v2 schemas com validações de segurança
**Plans**: 1 plan
Plans:
- [x] 02-01: SQLAlchemy models + Pydantic v2 schemas

### Phase 3: Core Engine
**Goal**: Motor de avaliação em memória, hash determinístico, cache pub/sub
**Depends on**: Phase 2
**Success Criteria**:
  1. EvaluationEngine com ordem de precedência correta
  2. mmh3 seed=42 com 10.000 buckets
  3. FlagCache com asyncio.Lock + CacheNotReadyError
**Plans**: 1 plan
Plans:
- [x] 03-01: evaluation engine + hashing + targeting + cache

### Phase 4: API Layer
**Goal**: Todos os endpoints REST obrigatórios + JWT HS256 + slowapi
**Depends on**: Phase 3
**Success Criteria**:
  1. CRUD flags + enable/disable + rules + audit + evaluation + batch + webhooks
  2. JWT com algorithms=[settings.jwt_algorithm] (alg=none bloqueado)
  3. Rate limiting 1000/min single, 200/min batch
**Plans**: 1 plan
Plans:
- [x] 04-01: REST endpoints + JWT auth + rate limiting

### Phase 5: App Factory
**Goal**: main.py com lifespan na ordem certa + toda infra (config, database, redis, metrics)
**Depends on**: Phase 4
**Success Criteria**:
  1. Lifespan: DB → Redis → warm_up → pub/sub → metrics
  2. create_app() factory function
  3. Prometheus + CORS + TrustedHost middleware
**Plans**: 1 plan
Plans:
- [x] 05-01: app factory + lifespan + infra + tooling

### Phase 6: SDK
**Goal**: Python SDK instalável via pip com FlagClient thread-safe + TTL cache
**Depends on**: Phase 5
**Success Criteria**:
  1. FlagClient nunca lança exceção para o caller
  2. TTLCache com RLock + time.monotonic
  3. sdk/pyproject.toml instalável
**Plans**: 1 plan
Plans:
- [x] 06-01: Python SDK thread-safe + TTL cache

### Phase 7: Tests
**Goal**: Suite completa alinhada com suite_test.md (imutável)
**Depends on**: Phase 6
**Success Criteria**:
  1. TestEvaluationPrecedence + TestDeterministicHash
  2. TestConcurrentEvaluation com asyncio.TaskGroup
  3. Testes de segurança: SQL injection, alg=none, RBAC, rate limiting
  4. p99 < 1ms como gate de CI
**Plans**: 1 plan
Plans:
- [x] 07-01: suite completa unit+consistency+security+performance

### Phase 8: CI/CD
**Goal**: GitHub Actions CI + 3 ADRs + seed script
**Depends on**: Phase 7
**Success Criteria**:
  1. Pipeline: unit → consistency → security-scan → security-tests → performance
  2. 3 ADRs completos (LaunchDarkly, eventual consistency, mmh3)
  3. make seed popula flags de exemplo
**Plans**: 1 plan
Plans:
- [x] 08-01: GitHub Actions + 3 ADRs + seed script

### Phase 9: Gap Closure
**Goal**: Fechar 4 lacunas identificadas vs prompt.md
**Depends on**: Phase 8
**Success Criteria**:
  1. src/api/v1/environments.py existe com endpoints de enable/disable separados
  2. sdk/feature_flags_sdk/models.py existe com tipos do SDK
  3. docker-compose.yml na raiz (API + PostgreSQL + Redis + Prometheus)
  4. pubsub_lag_seconds e webhook_dispatch_duration_seconds em metrics.py
**Plans**: 1 plan
Plans:
- [x] 09-01: gap closure (environments.py + sdk/models.py + docker-compose.yml + metrics) — commit 3c2dc11
