# Workflow operacional de retenção no Lakebase

O Cliente 360 usa Delta/Unity Catalog como fonte analítica de clientes, churn e recomendações. O Lakebase é a fonte transacional exclusiva para o estado do caso, SLA, aprovação, concorrência e trilha imutável de eventos.

## Estado e controles

```text
PENDING_APPROVAL -> APPROVED -> IN_PROGRESS -> RESOLVED -> CLOSED
                 -> REJECTED
```

- `CARE_AGENT` cria, inicia, resolve e fecha casos.
- `ACTION_APPROVER` aprova ou rejeita; `ADMIN` preserva o bypass administrativo de RBAC.
- o próprio solicitante nunca pode aprovar ou rejeitar o caso;
- `Idempotency-Key` é obrigatório em toda mutação;
- `expected_version` implementa concorrência otimista;
- o caso captura `model_name`, `model_version`, `model_run_id`, score e snapshot da recomendação;
- falha do Lakebase retorna `503` nas mutações e estado explícito `DEGRADED` no Cliente 360.

O Quetzal IQ consulta o mesmo contrato pelo scope `retention` de `telecom_snapshot`. Esse acesso é somente leitura e respeita o escopo territorial do operador.

## Migração reproduzível

A migração aditiva está em `migrations/lakebase/001_retention_cases.py` e cria:

- `quetzal_app.schema_migrations`;
- `quetzal_app.retention_cases`;
- `quetzal_app.retention_case_events`.

O job DAB `quetzal_lakebase_migrate` não possui agenda nem trigger. O deploy apenas registra o job; a execução é manual:

```bash
databricks bundle validate -t demo --profile <perfil>
databricks bundle deploy -t demo --profile <perfil>
databricks bundle run -t demo quetzal_lakebase_migrate --profile <perfil>
```

A migração usa checksum, pode ser reexecutada com segurança e concede ao service principal do App somente `USAGE`, `SELECT`, `INSERT` e `UPDATE` necessários. DDL continua reservado ao operador que executa a migração.

## APIs

- `GET /api/customers/{customer_id}/retention-cases`
- `GET /api/retention-cases?limit=25`
- `POST /api/customers/{customer_id}/retention-cases`
- `PATCH /api/retention-cases/{case_id}`

As duas mutações exigem o header `Idempotency-Key`. O `PATCH` também exige a versão observada pelo cliente. Conflitos de idempotência, versão ou transição retornam `409`.

## Validação operacional

O preflight verifica conectividade, as duas tabelas e o registro da migração. Para promoção, validar nesta ordem: bundle, migração manual, preflight, criação do caso, reload, tentativa de autoaprovação (deve falhar), aprovação com segundo ator, avanço até encerramento e consulta somente leitura pelo Quetzal IQ.
