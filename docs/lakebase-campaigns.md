# Ciclo gobernado de campañas en Lakebase

El optimizador sigue siendo determinista y de solo lectura. La persistencia empieza únicamente cuando un operador selecciona **Guardar como nueva** o **Guardar nueva versión**. Lakebase conserva el estado operacional; Unity Catalog continúa siendo la fuente analítica de clientes, consentimiento, churn, productos y economía.

## Contrato y estados

```text
DRAFT -> PENDING_APPROVAL -> APPROVED
                         -> REJECTED
      -> CANCELLED
PENDING_APPROVAL -> CANCELLED
```

- `CARE_AGENT` crea, revisa, envía a aprobación y cancela campañas propias o asignadas.
- `ACTION_APPROVER` aprueba o rechaza dentro de su alcance territorial.
- `ADMIN` mantiene el bypass administrativo de RBAC, pero no puede aprobar una campaña que él mismo solicitó.
- cada mutación exige `Idempotency-Key` y `expected_version` protege contra actualizaciones concurrentes;
- una revisión solo es válida en `DRAFT` y crea un snapshot inmutable nuevo;
- guardar o revisar vuelve a ejecutar `campaign-rules-v1` en el servidor. La API no acepta una audiencia ni una economía calculadas por el navegador;
- no existe estado, endpoint ni transición de envío. `campaign_sent` tiene un `CHECK (campaign_sent = false)` en Lakebase.

## Persistencia

La migración `002_campaign_workflow` crea:

- `quetzal_app.campaign_drafts`: estado actual, propietario, scope, fingerprint y snapshot restaurable;
- `quetzal_app.campaign_draft_versions`: versiones inmutables de parámetros, audiencia y economía;
- `quetzal_app.campaign_events`: ledger inmutable de creación, revisión y decisiones.

Las lecturas y decisiones aplican el scope territorial autenticado. El App recibe solamente `USAGE`, `SELECT`, `INSERT` y `UPDATE`; DDL continúa reservado al operador de la migración.

## APIs

- `GET /api/campaigns/drafts?limit=12`
- `GET /api/campaigns/drafts/{campaign_id}`
- `POST /api/campaigns/drafts`
- `PATCH /api/campaigns/drafts/{campaign_id}/revision`
- `PATCH /api/campaigns/drafts/{campaign_id}`

Los conflictos de idempotencia, versión, ownership, segregación o transición retornan `409`. Lakebase no disponible o sin schema retorna `503`; el preflight reporta el componente degradado.

## Migración DAB manual

El mismo job manual ejecuta primero `001_retention_cases` y después `002_campaign_workflow`. No posee `schedule` ni `trigger`.

```bash
databricks bundle validate -t demo --profile <perfil>
databricks bundle deploy -t demo --profile <perfil>
databricks bundle run -t demo quetzal_lakebase_migrate --profile <perfil>
```

La migración es aditiva, protegida por checksum e idempotente. Promover el App no inicia la migración automáticamente.

## Validación de promoción

1. Ejecutar el job manual y confirmar ambas tasks en `SUCCESS`.
2. Confirmar Lakebase `READY` en `/api/operations/preflight`.
3. Optimizar una audiencia y guardar una campaña.
4. Recargar el navegador y restaurar el mismo `campaign_id`, `draft_id` y `audience_fingerprint`.
5. Cambiar una premisa, optimizar y guardar una nueva versión; `snapshot_version` debe incrementar sin eliminar la anterior.
6. Enviar a aprobación e intentar decidir con el solicitante; la API debe rechazar con `409`.
7. Aprobar o rechazar con un segundo actor `ACTION_APPROVER` dentro del mismo scope.
8. Confirmar en todas las respuestas y registros que `campaign_sent=false`.

La demo puede detenerse después del envío a aprobación cuando no exista un segundo actor autenticado. Nunca se falsifica una aprobación para completar el guion.
