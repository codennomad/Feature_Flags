# Prompt — Feature Flags Platform (Top 1% Engineering)

## Contexto que você precisa absorver antes de escrever uma linha

Você é um engenheiro sênior construindo infraestrutura crítica de produção.
Feature flags não é um CRUD — é o sistema que permite que empresas como
Stripe, Cloudflare e Linear façam deploy de código com segurança sem reescrever
nada. O que diferencia um projeto medíocre de um que impressiona engenheiros
sênior não é o que o sistema *faz*, é como ele *falha* e como ele *escala*.

Toda decisão de design precisa ter uma razão. Você não usa Redis pub/sub porque
é legal — você usa porque consistência eventual em < 100ms é o trade-off certo
para evitar consultas de banco a cada evaluation request. Se perguntarem "por
que não LaunchDarkly?", você terá um ADR de 300 palavras explicando o custo,
o vendor lock-in, e o que você aprende construindo isso do zero.

---

## Stack mandatória (sem substituições)

- **FastAPI** — async from day one, sem sync endpoints
- **PostgreSQL** + **SQLAlchemy 2 async** — sem ORM sync, sem greenlets escondidos
- **Redis** — pub/sub para invalidação de cache, não polling
- **Pydantic v2** — `model_validator`, `field_validator`, sem Pydantic v1 compat
- **Prometheus** + `prometheus-fastapi-instrumentator` — métricas desde o primeiro endpoint
- **Python 3.12** — `asyncio.TaskGroup`, pattern matching onde faz sentido

---

## Estrutura de diretórios obrigatória

```
feature-flags/
├── src/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── flags.py          # CRUD + ativação
│   │   │   ├── evaluation.py     # endpoint de avaliação
│   │   │   ├── environments.py   # gerenciamento de ambientes
│   │   │   └── webhooks.py       # registro e disparo de webhooks
│   │   └── deps.py               # injeção de dependências (DB, cache, user)
│   ├── core/
│   │   ├── evaluation.py         # motor de avaliação — o coração do sistema
│   │   ├── cache.py              # local cache + invalidação via pub/sub
│   │   ├── hashing.py            # hash determinístico para rollout
│   │   └── targeting.py          # regras de targeting por atributo
│   ├── models/
│   │   ├── flag.py               # SQLAlchemy models
│   │   ├── audit.py              # audit log imutável
│   │   └── environment.py
│   ├── schemas/
│   │   ├── flag.py               # Pydantic v2 schemas de request/response
│   │   └── evaluation.py         # EvaluationContext, EvaluationResult
│   ├── infra/
│   │   ├── database.py           # async engine + session factory
│   │   ├── redis.py              # connection pool + pub/sub listener
│   │   └── metrics.py            # Prometheus custom metrics
│   └── main.py                   # app factory, lifespan, middleware
├── sdk/                           # pacote Python separado (pip install)
│   ├── feature_flags_sdk/
│   │   ├── client.py             # FlagClient thread-safe
│   │   ├── cache.py              # TTL cache local no SDK
│   │   └── models.py
│   └── pyproject.toml
├── docs/
│   └── adr/
│       ├── 001-why-not-launchdarkly.md
│       ├── 002-eventual-consistency-tradeoff.md
│       └── 003-deterministic-hashing.md
├── docker-compose.yml
├── pyproject.toml
└── Makefile
```

---

## Requisitos de implementação — por camada

### 1. Motor de avaliação (`core/evaluation.py`)

Este é o componente mais importante. Implemente com estas regras exatas:

```python
# A ordem de precedência é CRÍTICA — documente no código
# 1. Override por ambiente (maior prioridade)
# 2. Targeting rules (top-down, first match wins)
# 3. Rollout percentual por hash determinístico
# 4. Default value da flag (menor prioridade)
```

O `EvaluationContext` deve receber:
- `user_id: str` — obrigatório para rollout determinístico
- `environment: str` — staging, production, etc.
- `attributes: dict[str, Any]` — para targeting rules (país, plano, email)

A avaliação inteira ocorre **em memória, sem I/O**. O cache é carregado na
startup e atualizado via pub/sub. Se o cache não tiver a flag, retorne o
`default_value` sem nunca consultar o banco durante evaluation.

Métricas obrigatórias neste módulo:
- `flag_evaluation_duration_seconds` — histogram com buckets até 1ms
- `flag_evaluation_total` — counter com labels `flag_key`, `result`, `reason`
- `cache_hit_total` vs `cache_miss_total`

### 2. Hash determinístico para rollout (`core/hashing.py`)

```python
# Implemente exatamente desta forma:
# hash = mmh3.hash(f"{flag_key}:{user_id}", seed=42) % 10000
# user está no rollout se hash < (rollout_percentage * 100)
#
# Por que mmh3?
# - Distribuição uniforme validada
# - < 1 microsegundo por hash
# - Determinístico entre processos e restarts
# - Sem dependência da stdlib hash() que varia por seed de processo
```

Inclua um teste de uniformidade: distribua 100.000 user IDs aleatórios e
verifique que a distribuição para um rollout de 50% fica entre 49% e 51%.

### 3. Cache local com invalidação (`core/cache.py`)

```python
# Estrutura do cache:
# {
#   "flags": dict[str, FlagSnapshot],  # snapshot completo da flag
#   "version": int,                     # versão global para invalidação
#   "loaded_at": datetime
# }
#
# Invalidação via Redis pub/sub:
# Canal: "feature_flags:invalidate"
# Payload: {"flag_key": "my-flag", "version": 42, "action": "update"|"delete"}
#
# O subscriber roda como background task no lifespan da aplicação.
# Use asyncio.Queue para passar mensagens do subscriber para o updater.
# NUNCA faça lock bloqueante — use asyncio.Lock apenas.
```

**Detalhe crítico:** O cache local é por processo. Em múltiplas replicas,
cada processo recebe a mensagem pub/sub independentemente. Implemente um
`warm_up()` no lifespan que carrega todas as flags do banco antes de aceitar
requests.

### 4. Modelo de dados

**Flag:**
```sql
-- Campos obrigatórios:
id UUID PRIMARY KEY
key VARCHAR(255) UNIQUE NOT NULL  -- slugified, imutável após criação
name VARCHAR(255) NOT NULL
description TEXT
flag_type VARCHAR(50)  -- "boolean", "string", "number", "json"
default_value JSONB NOT NULL
environments JSONB NOT NULL  -- {"production": {...}, "staging": {...}}
created_at TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
created_by VARCHAR(255) NOT NULL
version INTEGER NOT NULL DEFAULT 1  -- incrementado a cada mudança
```

**Audit log (imutável — sem UPDATE, sem DELETE):**
```sql
id UUID PRIMARY KEY
flag_id UUID NOT NULL REFERENCES flags(id)
action VARCHAR(50) NOT NULL  -- "created", "updated", "enabled", "disabled", "rule_added"
actor VARCHAR(255) NOT NULL
changes JSONB NOT NULL  -- diff antes/depois
metadata JSONB          -- IP, user_agent, request_id
created_at TIMESTAMPTZ NOT NULL DEFAULT now()
-- sem updated_at — auditoria não tem update
```

**Regra:** Todo endpoint que modifica uma flag **deve** inserir no audit log
na mesma transação. Use um context manager para garantir isso.

### 5. Targeting rules

```python
# Estrutura de uma regra (em JSONB na flag):
{
  "id": "rule-uuid",
  "name": "Beta users Brazil",
  "priority": 1,
  "conditions": [
    {"attribute": "country", "operator": "in", "value": ["BR", "PT"]},
    {"attribute": "plan", "operator": "eq", "value": "beta"}
  ],
  "condition_combinator": "AND",  # ou "OR"
  "serve": true  # valor a servir quando a regra bate
}

# Operadores suportados:
# eq, neq, in, not_in, contains, starts_with, gt, gte, lt, lte
```

### 6. Webhook dispatcher

- Dispare webhook em `flag.enabled` e `flag.disabled`
- Payload deve incluir: `flag_key`, `environment`, `actor`, `timestamp`, `previous_state`
- Implemente retry com exponential backoff: 3 tentativas, delays de 1s, 5s, 25s
- Timeout por request: 5 segundos
- **Use `asyncio.create_task` para não bloquear o response**
- Persista tentativas falhadas em tabela separada para reprocessamento

### 7. Endpoints obrigatórios

```
# Gerenciamento de flags
POST   /api/v1/flags
GET    /api/v1/flags
GET    /api/v1/flags/{flag_key}
PATCH  /api/v1/flags/{flag_key}
DELETE /api/v1/flags/{flag_key}

# Ativação por ambiente
POST   /api/v1/flags/{flag_key}/environments/{env}/enable
POST   /api/v1/flags/{flag_key}/environments/{env}/disable

# Regras de targeting
POST   /api/v1/flags/{flag_key}/rules
PUT    /api/v1/flags/{flag_key}/rules/{rule_id}
DELETE /api/v1/flags/{flag_key}/rules/{rule_id}

# Avaliação (crítico — deve ser < 1ms)
POST   /api/v1/evaluate
POST   /api/v1/evaluate/batch  # múltiplas flags em uma chamada

# Audit
GET    /api/v1/flags/{flag_key}/audit

# Admin
GET    /api/v1/health
GET    /metrics  # Prometheus scrape endpoint
```

### 8. Python SDK (pacote separado)

```python
# Interface pública do SDK — mantenha simples:
from feature_flags_sdk import FlagClient

client = FlagClient(
    api_url="https://flags.company.com",
    api_key="sk-...",
    cache_ttl=30,           # segundos
    default_timeout=0.5,    # nunca mais que 500ms — falha silenciosa
)

# Uso:
is_enabled = client.is_enabled("new-checkout", user_id="user-123")
variant = client.get_variant("pricing-experiment", user_id="user-123",
                              attributes={"country": "BR", "plan": "pro"})

# O SDK tem seu próprio cache local com TTL.
# Nunca lance exceção para o caller — retorne sempre o default.
# Instrua o SDK a logar warnings, não erros fatais.
```

---

## ADR obrigatório: Por que não LaunchDarkly

Arquivo: `docs/adr/001-why-not-launchdarkly.md`

Escreva um ADR real cobrindo:
- **Contexto:** O que o time precisa
- **Opções consideradas:** LaunchDarkly, Unleash, Flagsmith, homebrew
- **Decisão:** Por que homebrew neste contexto
- **Consequências positivas:** Controle total, zero vendor lock-in, aprendizado
- **Consequências negativas:** Manutenção, features faltantes, tempo de setup
- **Quando revisar:** Critérios objetivos (ex: time > 20 engenheiros)

---

## Métricas Prometheus que engenheiros sênior procuram

```python
# Estes são os sinais que mostram que você entende operação em produção:
flag_evaluation_duration_seconds  # histogram — p50, p95, p99
flag_evaluation_total             # by flag_key, result (true/false), reason
cache_refresh_duration_seconds    # quanto tempo o warm-up leva
cache_size_flags                  # quantas flags no cache
pubsub_invalidations_total        # quantas invalidações recebidas
pubsub_lag_seconds                # atraso entre publicação e aplicação
webhook_dispatch_total            # by status (success, retry, failed)
webhook_dispatch_duration_seconds # latência dos webhooks externos
db_pool_size                      # tamanho do pool de conexões
db_pool_checked_out               # conexões em uso
```

---

## Lifespan da aplicação (ordem crítica)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP — ordem importa
    await database.connect()          # 1. banco primeiro
    await redis.connect()             # 2. redis
    await cache.warm_up()             # 3. carrega todas as flags
    await pubsub.start_listener()     # 4. começa a ouvir invalidações
    metrics.register_collectors()     # 5. métricas
    logger.info("ready", flags_loaded=cache.size())
    
    yield
    
    # SHUTDOWN — ordem inversa
    await pubsub.stop_listener()
    await redis.disconnect()
    await database.disconnect()
```

---

## O que engenheiros sênior vão revisar primeiro

1. **`core/evaluation.py`** — O motor tem zero I/O? A ordem de precedência está documentada e testada?
2. **`core/hashing.py`** — O hash é realmente determinístico entre processos? Há teste de uniformidade?
3. **`core/cache.py`** — A invalidação via pub/sub é race-condition-free? O warm_up é atômico?
4. **`docs/adr/`** — Os ADRs têm trade-offs reais ou são genéricos?
5. **Métricas** — O p99 de evaluation está abaixo de 1ms? Isso é observável via Prometheus?
6. **Audit log** — Está na mesma transação da mudança? É impossível ter mudança sem log?

---

## Entregáveis finais esperados

- [ ] `docker-compose up` sobe tudo (API + PostgreSQL + Redis)
- [ ] `make migrate` roda as migrations
- [ ] `make seed` insere flags de exemplo com targeting rules
- [ ] `/metrics` expõe métricas Prometheus
- [ ] SDK instalável via `pip install -e ./sdk`
- [ ] `docs/adr/` com 3 ADRs reais
- [ ] `Makefile` com targets: `dev`, `test`, `migrate`, `seed`, `lint`
- [ ] Benchmark documentado provando evaluation < 1ms (use `locust` ou `wrk`)