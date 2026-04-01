# Prompt — Testes Elite: Feature Flags Platform

## Filosofia de testes que separa sênior de júnior

Testes fracos verificam se o código *faz o que foi pedido*.
Testes de nível sênior verificam se o código *sobrevive ao que não foi pedido*.

Este guia cobre quatro dimensões que tornam o projeto referência:

1. **Corretude** — o sistema faz o que promete
2. **Consistência** — o sistema é previsível sob concorrência
3. **Resiliência** — o sistema falha de forma segura e controlada
4. **Segurança** — o sistema resiste a adversários ativos

---

## Stack de testes

```
pytest
pytest-asyncio          # async tests nativos
pytest-xdist            # paralelismo de testes
httpx[AsyncClient]      # para testar endpoints FastAPI sem servidor real
factory-boy             # geração de fixtures sem código manual
faker                   # dados realistas
hypothesis              # property-based testing
locust                  # benchmark de performance
sqlalchemy-utils         # helpers para test database
testcontainers-python    # PostgreSQL e Redis reais em Docker para testes
bandit                   # análise estática de segurança
safety                   # auditoria de dependências com CVEs
semgrep                  # análise de padrões de código inseguro
```

---

## Estrutura de diretórios de testes

```
tests/
├── unit/
│   ├── core/
│   │   ├── test_evaluation.py       # motor de avaliação isolado
│   │   ├── test_hashing.py          # uniformidade e determinismo
│   │   ├── test_targeting.py        # todas as regras de targeting
│   │   └── test_cache.py            # cache local puro
│   └── schemas/
│       └── test_validation.py       # Pydantic v2 edge cases
├── integration/
│   ├── test_api_flags.py            # endpoints com banco real
│   ├── test_api_evaluation.py       # evaluation com cache real
│   ├── test_pubsub_invalidation.py  # fluxo completo pub/sub
│   ├── test_audit_log.py            # audit log na mesma transação
│   └── test_webhook.py              # disparo e retry de webhooks
├── consistency/
│   ├── test_concurrent_evaluation.py   # concorrência no motor
│   ├── test_cache_invalidation_race.py # race condition no cache
│   └── test_rollout_distribution.py    # distribuição estatística
├── security/
│   ├── test_injection.py            # SQL, NoSQL, SSTI, command injection
│   ├── test_authn_authz.py          # autenticação e autorização
│   ├── test_input_validation.py     # payloads maliciosos e edge cases
│   ├── test_rate_limiting.py        # DoS e brute force
│   ├── test_audit_tampering.py      # tentativa de alterar audit log
│   └── test_sensitive_data.py       # vazamento de dados em respostas/logs
├── performance/
│   ├── test_evaluation_latency.py   # prova que < 1ms
│   ├── locustfile.py                # cenário de carga realista
│   └── benchmark_hashing.py        # benchmark do hash determinístico
├── conftest.py                      # fixtures compartilhadas
├── factories.py                     # factory-boy factories
└── utils/
    ├── assertions.py                # assertivas customizadas reutilizáveis
    └── attack_payloads.py           # payloads de ataque centralizados
```

---

## PARTE 1 — Testes de corretude do motor de avaliação

### 1.1 — Precedência de regras

```python
# tests/unit/core/test_evaluation.py
import pytest
from src.core.evaluation import EvaluationEngine
from tests.factories import FlagFactory, RuleFactory

class TestEvaluationPrecedence:
    """
    Cada teste verifica UMA camada da precedência.
    Ordem: override > targeting > rollout > default.
    """

    def test_environment_override_beats_targeting(self):
        """Override de ambiente tem prioridade máxima, sempre."""
        flag = FlagFactory.build(
            environments={
                "production": {
                    "enabled": True,
                    "override": False,  # override force-off
                    "rollout_percentage": 100,
                }
            },
            rules=[RuleFactory.build(serve=True, priority=1)]
        )
        context = EvaluationContext(
            user_id="user-123",
            environment="production",
            attributes={"country": "BR"}  # bate na regra
        )
        result = EvaluationEngine().evaluate(flag, context)
        assert result.value is False
        assert result.reason == "OVERRIDE"

    def test_targeting_rule_beats_rollout(self):
        """Regra de targeting tem prioridade sobre percentual de rollout."""
        flag = FlagFactory.build(
            environments={
                "production": {
                    "enabled": True,
                    "rollout_percentage": 0,  # nenhum usuário no rollout
                    "rules": [
                        {"conditions": [{"attribute": "plan", "operator": "eq", "value": "enterprise"}],
                         "serve": True, "priority": 1}
                    ]
                }
            }
        )
        context = EvaluationContext(
            user_id="any-user",
            environment="production",
            attributes={"plan": "enterprise"}
        )
        result = EvaluationEngine().evaluate(flag, context)
        assert result.value is True
        assert result.reason == "TARGETING_MATCH"

    def test_rollout_zero_returns_default(self):
        """Rollout 0% retorna default independente do user_id."""
        flag = FlagFactory.build(
            default_value=False,
            environments={"production": {"enabled": True, "rollout_percentage": 0}}
        )
        for user_id in ["user-1", "user-999", "superuser", "admin"]:
            context = EvaluationContext(user_id=user_id, environment="production")
            result = EvaluationEngine().evaluate(flag, context)
            assert result.value is False, f"Falhou para user_id={user_id}"
            assert result.reason == "DEFAULT"

    def test_rollout_100_returns_true_for_all(self):
        """Rollout 100% retorna True para qualquer user_id."""
        flag = FlagFactory.build(
            default_value=False,
            environments={"production": {"enabled": True, "rollout_percentage": 100}}
        )
        from faker import Faker
        fake = Faker()
        for _ in range(500):
            context = EvaluationContext(user_id=fake.uuid4(), environment="production")
            result = EvaluationEngine().evaluate(flag, context)
            assert result.value is True

    def test_disabled_flag_returns_default_regardless_of_rules(self):
        """Flag desabilitada retorna default mesmo com regras que batem."""
        flag = FlagFactory.build(
            default_value=False,
            environments={
                "production": {
                    "enabled": False,  # desabilitada
                    "rollout_percentage": 100,
                    "rules": [{"conditions": [], "serve": True, "priority": 1}]
                }
            }
        )
        context = EvaluationContext(user_id="any", environment="production")
        result = EvaluationEngine().evaluate(flag, context)
        assert result.value is False
        assert result.reason == "FLAG_DISABLED"
```

### 1.2 — Determinismo e uniformidade do hash

```python
# tests/unit/core/test_hashing.py
import statistics
from src.core.hashing import compute_rollout_hash

class TestDeterministicHash:

    def test_same_inputs_always_produce_same_result(self):
        """O hash é determinístico: mesmos inputs = mesmo output, sempre."""
        for _ in range(1000):
            h1 = compute_rollout_hash("my-flag", "user-abc")
            h2 = compute_rollout_hash("my-flag", "user-abc")
            assert h1 == h2

    def test_different_flags_same_user_different_hash(self):
        """
        user_id idêntico em flags diferentes deve ter distribuições independentes.
        Sem isso, ativar flag A sempre ativaria flag B para os mesmos usuários.
        """
        results_flag_a = []
        results_flag_b = []
        for i in range(10000):
            user_id = f"user-{i}"
            ha = compute_rollout_hash("flag-a", user_id) < 5000
            hb = compute_rollout_hash("flag-b", user_id) < 5000
            results_flag_a.append(ha)
            results_flag_b.append(hb)

        # As distribuições são independentes — correlação deve ser baixa
        overlap = sum(1 for a, b in zip(results_flag_a, results_flag_b) if a == b)
        correlation = overlap / 10000
        # Correlação esperada para independentes: ~50% (± 2%)
        assert 0.48 <= correlation <= 0.52, \
            f"Correlação anômala entre flags: {correlation:.2%}"

    def test_rollout_distribution_is_uniform(self):
        """
        Para rollout de 50%, exatamente ~50% dos usuários devem estar incluídos.
        Tolerância estatística: ± 1% para 100.000 amostras.
        """
        from faker import Faker
        fake = Faker()
        flag_key = "distribution-test"
        n = 100_000
        threshold = 5000  # 50% de 10000 buckets

        included = sum(
            1 for _ in range(n)
            if compute_rollout_hash(flag_key, fake.uuid4()) < threshold
        )
        ratio = included / n
        assert 0.49 <= ratio <= 0.51, \
            f"Distribuição fora do esperado: {ratio:.2%} (esperado 50% ± 1%)"

    @pytest.mark.parametrize("percentage", [0, 1, 10, 25, 50, 75, 90, 99, 100])
    def test_rollout_boundary_percentages(self, percentage):
        """
        Percentuais extremos devem produzir distribuições corretas.
        0% → nenhum usuário; 100% → todos os usuários.
        """
        from faker import Faker
        fake = Faker()
        threshold = percentage * 100  # 0-10000

        n = 10_000
        included = sum(
            1 for _ in range(n)
            if compute_rollout_hash("boundary-test", fake.uuid4()) < threshold
        )
        ratio = included / n
        tolerance = 0.03  # ± 3% para n menor
        assert abs(ratio - percentage / 100) <= tolerance, \
            f"Percentual {percentage}%: obtido {ratio:.2%}"
```

---

## PARTE 2 — Testes de consistência sob concorrência

```python
# tests/consistency/test_concurrent_evaluation.py
import asyncio
import pytest
from src.core.cache import FlagCache
from src.core.evaluation import EvaluationEngine

class TestConcurrentEvaluation:

    @pytest.mark.asyncio
    async def test_cache_invalidation_during_concurrent_evaluation(self):
        """
        Cenário crítico: invalidação de cache enquanto 1000 goroutines
        estão avaliando a mesma flag. Nenhuma deve receber resultado
        inconsistente (nem erro, nem panic, nem resultado de flag errada).
        """
        cache = FlagCache()
        engine = EvaluationEngine(cache=cache)

        flag_key = "concurrent-test-flag"
        await cache.set(flag_key, FlagFactory.build(key=flag_key, default_value=False))

        results = []
        errors = []

        async def evaluate_continuously(user_id: str):
            for _ in range(100):
                try:
                    ctx = EvaluationContext(user_id=user_id, environment="production")
                    flag = cache.get(flag_key)
                    result = engine.evaluate(flag, ctx)
                    # O resultado deve ser bool, nunca None ou exceção
                    assert isinstance(result.value, bool)
                    results.append(result.value)
                except Exception as e:
                    errors.append(str(e))
                await asyncio.sleep(0)  # yield para o event loop

        async def invalidate_periodically():
            for i in range(10):
                await asyncio.sleep(0.01)
                new_flag = FlagFactory.build(
                    key=flag_key,
                    default_value=bool(i % 2)  # alterna true/false
                )
                await cache.invalidate(flag_key, new_flag)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(invalidate_periodically())
            for i in range(100):
                tg.create_task(evaluate_continuously(f"user-{i}"))

        assert len(errors) == 0, f"Erros durante concorrência: {errors[:5]}"
        assert len(results) == 10_000  # 100 goroutines × 100 avaliações

    @pytest.mark.asyncio
    async def test_warm_up_blocks_requests_until_complete(self):
        """
        Durante o warm_up, requests de evaluation não devem ser aceitos.
        Isso previne avaliações com cache vazio que retornariam defaults errados.
        """
        cache = FlagCache()

        warm_up_complete = asyncio.Event()
        evaluation_attempted_before_ready = False

        async def slow_warm_up():
            await asyncio.sleep(0.1)  # simula carregamento lento
            await cache.mark_ready()
            warm_up_complete.set()

        async def try_evaluate_early():
            nonlocal evaluation_attempted_before_ready
            # Tenta avaliar antes do warm_up completar
            if not cache.is_ready():
                evaluation_attempted_before_ready = True
                with pytest.raises(CacheNotReadyError):
                    cache.get("any-flag")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(slow_warm_up())
            tg.create_task(try_evaluate_early())

        assert evaluation_attempted_before_ready, "Teste não alcançou a condição desejada"
```

---

## PARTE 3 — Testes de segurança

### 3.1 — SQL Injection

```python
# tests/security/test_injection.py
import pytest

# Centralizar payloads facilita manutenção e auditoria
SQL_INJECTION_PAYLOADS = [
    "'; DROP TABLE flags; --",
    "' OR '1'='1",
    "' OR 1=1--",
    "'; SELECT * FROM audit_logs; --",
    "1; UPDATE flags SET default_value='{}' WHERE 1=1--",
    "' UNION SELECT id, key, null FROM flags--",
    "\\'; DROP TABLE flags; --",
    "%27 OR %271%27=%271",
    "1' AND SLEEP(5)--",          # blind time-based
    "' AND 1=CAST((SELECT version()) AS INT)--",  # error-based
    "' AND EXTRACTVALUE(1, CONCAT(0x7e, (SELECT version())))--",
]

NOSQL_INJECTION_PAYLOADS = [
    {"$gt": ""},
    {"$where": "this.key.length > 0"},
    {"$regex": ".*"},
    '{"$gt": ""}',
]

SSTI_PAYLOADS = [
    "{{7*7}}",
    "${7*7}",
    "#{7*7}",
    "{{config}}",
    "{{request.application.__globals__}}",
    "<%= 7*7 %>",
]

class TestSQLInjection:

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    async def test_flag_key_sql_injection(self, async_client, payload):
        """flag_key é usado em queries — deve rejeitar payloads SQL."""
        response = await async_client.get(f"/api/v1/flags/{payload}")
        # Nunca deve retornar 500 (indica erro SQL não tratado)
        # Deve retornar 404 (não encontrado) ou 422 (validação)
        assert response.status_code in (404, 422), \
            f"Payload SQL retornou {response.status_code}: {payload!r}"
        # Nunca expor detalhes do banco no response
        body = response.text.lower()
        for leak_word in ["syntax error", "postgresql", "sqlalchemy", "column", "relation"]:
            assert leak_word not in body, \
                f"Detalhe de banco vazou no response: {leak_word!r}"

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    async def test_evaluation_user_id_injection(self, async_client, payload):
        """user_id no payload de evaluation deve ser tratado como string opaca."""
        response = await async_client.post("/api/v1/evaluate", json={
            "flag_key": "test-flag",
            "user_id": payload,
            "environment": "production"
        })
        # user_id nunca vai direto ao banco, mas o teste documenta isso
        assert response.status_code in (200, 404, 422)
        assert "syntax error" not in response.text.lower()

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    async def test_search_parameter_injection(self, async_client, payload):
        """Parâmetros de busca na listagem de flags."""
        response = await async_client.get(f"/api/v1/flags?search={payload}")
        assert response.status_code in (200, 422)
        assert "syntax error" not in response.text.lower()
        # Não deve retornar mais flags do que o normal
        if response.status_code == 200:
            data = response.json()
            assert len(data.get("items", [])) <= 100  # limite razoável
```

### 3.2 — Autenticação e Autorização

```python
# tests/security/test_authn_authz.py

class TestAuthentication:

    async def test_all_endpoints_require_authentication(self, async_client):
        """
        Sem token JWT, todos os endpoints retornam 401.
        Nenhum endpoint deve ser acessível sem autenticação.
        """
        endpoints = [
            ("GET",    "/api/v1/flags"),
            ("POST",   "/api/v1/flags"),
            ("GET",    "/api/v1/flags/some-flag"),
            ("PATCH",  "/api/v1/flags/some-flag"),
            ("DELETE", "/api/v1/flags/some-flag"),
            ("POST",   "/api/v1/evaluate"),
            ("POST",   "/api/v1/evaluate/batch"),
            ("GET",    "/api/v1/flags/some-flag/audit"),
        ]
        for method, path in endpoints:
            response = await async_client.request(method, path)
            assert response.status_code == 401, \
                f"{method} {path} retornou {response.status_code} sem autenticação"

    async def test_expired_jwt_returns_401(self, async_client):
        """JWT expirado deve ser rejeitado — sem tolerância de clock."""
        expired_token = generate_jwt(
            sub="user-123",
            exp=datetime.utcnow() - timedelta(seconds=1)
        )
        response = await async_client.get(
            "/api/v1/flags",
            headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert response.status_code == 401

    async def test_tampered_jwt_signature_rejected(self, async_client):
        """JWT com assinatura alterada deve ser rejeitado."""
        valid_token = generate_valid_jwt(sub="user-123")
        # Altera o último caractere da assinatura
        tampered = valid_token[:-1] + ("A" if valid_token[-1] != "A" else "B")
        response = await async_client.get(
            "/api/v1/flags",
            headers={"Authorization": f"Bearer {tampered}"}
        )
        assert response.status_code == 401

    async def test_none_algorithm_jwt_rejected(self, async_client):
        """
        Ataque clássico: JWT com alg=none.
        Muitas implementações aceitam por engano — a nossa não deve.
        """
        import base64, json
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "admin", "exp": 9999999999}).encode()
        ).rstrip(b"=").decode()
        none_token = f"{header}.{payload}."

        response = await async_client.get(
            "/api/v1/flags",
            headers={"Authorization": f"Bearer {none_token}"}
        )
        assert response.status_code == 401

    async def test_viewer_cannot_modify_flags(self, async_client, viewer_token):
        """Role 'viewer' pode listar mas não pode criar/modificar/deletar."""
        headers = {"Authorization": f"Bearer {viewer_token}"}

        # Pode visualizar
        assert (await async_client.get("/api/v1/flags", headers=headers)).status_code == 200

        # Não pode modificar
        assert (await async_client.post("/api/v1/flags",
            headers=headers, json={"key": "x", "name": "X"})).status_code == 403
        assert (await async_client.delete(
            "/api/v1/flags/some-flag", headers=headers)).status_code == 403


class TestAuditTampering:

    async def test_audit_log_has_no_update_endpoint(self, async_client, admin_token):
        """
        O audit log é imutável por design.
        Não deve existir nenhum endpoint para alterar registros de auditoria.
        """
        headers = {"Authorization": f"Bearer {admin_token}"}
        audit_id = "some-real-audit-id"

        for method in ["PUT", "PATCH", "DELETE"]:
            response = await async_client.request(
                method, f"/api/v1/audit/{audit_id}", headers=headers
            )
            # Deve retornar 405 (Method Not Allowed) ou 404
            assert response.status_code in (404, 405), \
                f"{method} /api/v1/audit/{audit_id} não deveria existir"

    async def test_audit_entry_created_even_if_main_operation_succeeds(
        self, async_client, db_session, admin_token
    ):
        """
        Criar uma flag DEVE gerar entrada no audit log na mesma transação.
        Sem entrada = sem flag. Isso garante rastreabilidade completa.
        """
        headers = {"Authorization": f"Bearer {admin_token}"}
        flag_data = {"key": "audit-test-flag", "name": "Audit Test", "default_value": False}

        response = await async_client.post("/api/v1/flags", headers=headers, json=flag_data)
        assert response.status_code == 201
        flag_id = response.json()["id"]

        # Verifica que o audit log foi criado
        audit_count = await db_session.scalar(
            select(func.count()).where(AuditLog.flag_id == flag_id)
        )
        assert audit_count == 1, "Nenhuma entrada de audit log foi criada"
```

### 3.3 — Validação de input e rate limiting

```python
# tests/security/test_input_validation.py

OVERSIZED_PAYLOADS = {
    "key": "a" * 10_000,
    "name": "x" * 100_000,
    "description": "y" * 1_000_000,
}

SPECIAL_CHARS = [
    "<script>alert(1)</script>",
    "javascript:alert(1)",
    "../../../etc/passwd",
    "..\\..\\..\\windows\\system32",
    "\x00\x01\x02",                   # null bytes
    "\n\r\t",                          # control chars
    "🔥" * 1000,                       # unicode flood
    "\u202e",                          # unicode right-to-left override
]

class TestInputValidation:

    @pytest.mark.parametrize("field,value", OVERSIZED_PAYLOADS.items())
    async def test_oversized_fields_rejected(self, async_client, admin_token, field, value):
        """Campos com tamanho excessivo devem ser rejeitados com 422."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        payload = {"key": "valid-key", "name": "Valid Name", "default_value": False}
        payload[field] = value

        response = await async_client.post("/api/v1/flags", headers=headers, json=payload)
        assert response.status_code == 422, \
            f"Campo '{field}' com {len(value)} chars deveria ser rejeitado"

    async def test_deeply_nested_json_rejected(self, async_client, admin_token):
        """
        JSON profundamente aninhado pode causar stack overflow durante parsing.
        Limite de profundidade deve ser validado.
        """
        headers = {"Authorization": f"Bearer {admin_token}"}
        def make_nested(depth):
            if depth == 0: return "value"
            return {"nested": make_nested(depth - 1)}

        deep_json = make_nested(1000)
        response = await async_client.post(
            "/api/v1/flags",
            headers=headers,
            json={"key": "test", "name": "test", "default_value": deep_json}
        )
        assert response.status_code in (400, 413, 422)


# tests/security/test_rate_limiting.py
class TestRateLimiting:

    async def test_evaluation_endpoint_rate_limited(self, async_client, auth_headers):
        """
        O endpoint de evaluation é o mais crítico — deve ter rate limiting.
        Acima do limite, retorna 429 com Retry-After header.
        """
        # Envia requests rápidos além do limite
        responses = []
        for _ in range(200):
            r = await async_client.post(
                "/api/v1/evaluate",
                headers=auth_headers,
                json={"flag_key": "test", "user_id": "user-1", "environment": "production"}
            )
            responses.append(r.status_code)

        rate_limited = [s for s in responses if s == 429]
        assert len(rate_limited) > 0, "Rate limiting não foi ativado"

        # Verifica presença do header Retry-After
        for r_idx, status in enumerate(responses):
            if status == 429:
                response = responses[r_idx]
                # O objeto de response precisa ter o header
                break

    async def test_brute_force_auth_limited(self, async_client):
        """
        Tentativas repetidas com tokens inválidos devem ser limitadas.
        Previne brute force em tokens de curta vida.
        """
        for i in range(50):
            response = await async_client.get(
                "/api/v1/flags",
                headers={"Authorization": f"Bearer invalid-token-{i}"}
            )
        # Após muitas tentativas, deve bloquear por IP
        assert response.status_code in (401, 429)


# tests/security/test_sensitive_data.py
class TestSensitiveDataLeakage:

    async def test_error_responses_do_not_expose_stack_traces(self, async_client, admin_token):
        """
        Em produção, erros 500 não devem expor stack traces ou detalhes internos.
        """
        headers = {"Authorization": f"Bearer {admin_token}"}
        # Força uma situação que pode causar erro interno
        response = await async_client.get(
            "/api/v1/flags/flag-that-will-cause-db-error",
            headers=headers
        )
        body = response.text
        # Nunca expor:
        for sensitive in ["Traceback", "File \"", "line ", "sqlalchemy", "asyncpg", "/src/"]:
            assert sensitive not in body, \
                f"Informação sensível '{sensitive}' exposta no response de erro"

    async def test_api_keys_not_logged(self, caplog, async_client):
        """
        API keys no header Authorization não devem aparecer em logs.
        Crítico para compliance.
        """
        real_token = generate_valid_jwt(sub="user-123")
        with caplog.at_level(logging.DEBUG):
            await async_client.get(
                "/api/v1/flags",
                headers={"Authorization": f"Bearer {real_token}"}
            )
        # O token completo não deve aparecer em nenhum log
        for record in caplog.records:
            assert real_token not in record.message, \
                f"Token JWT exposto no log: {record.message[:100]}"
```

---

## PARTE 4 — Testes de performance

```python
# tests/performance/test_evaluation_latency.py
import time
import statistics

class TestEvaluationLatency:

    def test_single_evaluation_under_1ms(self, loaded_cache):
        """
        A promessa central do sistema: avaliação em < 1ms.
        Testado com cache warm e sem I/O.
        """
        engine = EvaluationEngine(cache=loaded_cache)
        context = EvaluationContext(
            user_id="benchmark-user",
            environment="production",
            attributes={"country": "BR", "plan": "pro"}
        )
        flag = loaded_cache.get("test-flag")

        # Aquece JIT/caches de CPU
        for _ in range(1000):
            engine.evaluate(flag, context)

        # Mede latência real
        latencies = []
        for _ in range(10_000):
            start = time.perf_counter_ns()
            engine.evaluate(flag, context)
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            latencies.append(elapsed_ms)

        p50 = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=20)[18]  # 95th percentile
        p99 = statistics.quantiles(latencies, n=100)[98]  # 99th percentile

        assert p50 < 0.1,  f"p50 muito alto: {p50:.3f}ms (esperado < 0.1ms)"
        assert p95 < 0.5,  f"p95 muito alto: {p95:.3f}ms (esperado < 0.5ms)"
        assert p99 < 1.0,  f"p99 fora do SLA: {p99:.3f}ms (esperado < 1ms)"

        # Documenta o resultado (aparece no relatório de CI)
        print(f"\nLatência de avaliação — p50={p50:.3f}ms p95={p95:.3f}ms p99={p99:.3f}ms")
```

```python
# tests/performance/locustfile.py
"""
Cenário realista de carga. Rode com:
  locust -f tests/performance/locustfile.py --headless -u 500 -r 50 -t 60s
"""
from locust import HttpUser, task, between

class FeatureFlagUser(HttpUser):
    wait_time = between(0.001, 0.01)  # 100-1000 RPS por usuário

    def on_start(self):
        # Autentica uma vez
        resp = self.client.post("/api/v1/auth/token",
                                json={"api_key": "load-test-key"})
        self.token = resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(10)  # 10x mais frequente que escrita
    def evaluate_flag(self):
        self.client.post("/api/v1/evaluate",
            headers=self.headers,
            json={
                "flag_key": "checkout-v2",
                "user_id": f"user-{self.user_id % 10000}",
                "environment": "production",
                "attributes": {"country": "BR", "plan": "pro"}
            },
            name="/api/v1/evaluate"
        )

    @task(1)
    def batch_evaluate(self):
        self.client.post("/api/v1/evaluate/batch",
            headers=self.headers,
            json={
                "flags": ["checkout-v2", "new-pricing", "dark-mode"],
                "user_id": f"user-{self.user_id % 10000}",
                "environment": "production"
            },
            name="/api/v1/evaluate/batch"
        )

    @task(1)
    def list_flags(self):
        self.client.get("/api/v1/flags", headers=self.headers)
```

---

## PARTE 5 — Análise estática de segurança (CI obrigatório)

```makefile
# Makefile
security-scan:
    @echo "=== Bandit: análise de código Python ==="
    bandit -r src/ -ll -ii --skip B101
    # B101: asserts em código de produção — OK para nós, ignoramos
    # -ll: só medium+ severity
    # -ii: só medium+ confidence

    @echo "=== Safety: CVEs em dependências ==="
    safety check --full-report

    @echo "=== Semgrep: padrões de código inseguro ==="
    semgrep --config=p/python --config=p/fastapi --config=p/jwt \
            --error --quiet src/

    @echo "=== pip-audit: vulnerabilidades em dependências ==="
    pip-audit --requirement requirements.txt

test-security: security-scan
    pytest tests/security/ -v --tb=short -x
    @echo "=== Todos os testes de segurança passaram ==="
```

---

## PARTE 6 — Coverage e qualidade mínima

```ini
# pyproject.toml — seção [tool.pytest.ini_options]
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "security: testes de segurança (demore > 30s em CI)",
    "performance: testes de latência (requerem ambiente controlado)",
    "consistency: testes de concorrência",
]
# Roda paralelo exceto segurança (que pode ser flaky com timing)
addopts = "-n auto --ignore=tests/security --ignore=tests/performance"

[tool.coverage.run]
source = ["src"]
omit = ["*/migrations/*", "*/conftest.py"]

[tool.coverage.report]
fail_under = 85                      # mínimo para merge
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
]
# Módulos críticos têm exigência maior
[tool.coverage.paths]
core = ["src/core/"]
```

```yaml
# .github/workflows/test.yml — pipeline de CI
name: Tests
on: [push, pull_request]
jobs:
  test:
    steps:
      - name: Unit + Integration
        run: pytest tests/unit tests/integration -v --cov=src --cov-fail-under=85

      - name: Consistency (concorrência)
        run: pytest tests/consistency -v --timeout=60

      - name: Security static analysis
        run: make security-scan

      - name: Security tests
        run: pytest tests/security -v -m security --timeout=120

      - name: Performance regression
        run: pytest tests/performance/test_evaluation_latency.py -v
        # Falha se p99 > 1ms — regressão de performance vira falha de CI
```

---

## O que engenheiros sênior procuram nos testes

1. **Testes de uniformidade do hash** — provam que o rollout é estatisticamente correto, não apenas que "funciona"
2. **Teste de precedência completo** — cada camada (override, targeting, rollout, default) tem seu próprio teste isolado
3. **Testes de concorrência com `asyncio.TaskGroup`** — não simulam concorrência, *são* concorrentes
4. **Injeção SQL com payloads reais** — não apenas inputs genéricos malformados
5. **JWT alg=none** — ataque bem documentado que muitas implementações erram
6. **Audit log imutável com teste de integração** — verifica que o log é criado na mesma transação, não depois
7. **Latência como assertion em CI** — p99 > 1ms falha o build; não é só documentação
8. **Bandit + Semgrep no pipeline** — segurança como código, não como revisão manual