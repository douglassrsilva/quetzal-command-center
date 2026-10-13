# Contrato de dados e ML do Quetzal

Este documento descreve a Etapa B versionada no bundle. Ele não é evidência de uma nova execução: os recursos foram recuperados e adaptados por leitura, e nenhum pipeline, gerador, treinamento ou scoring foi iniciado durante a implementação.

## Fluxo reconstruível

```text
Job manual de dados sintéticos
  -> /Volumes/<catalog>/<schema>/<raw_volume> (Parquet)
  -> Lakeflow Declarative Pipeline manual
       Bronze Auto Loader -> Silver + expectations -> Gold MVs
  -> Job manual de ML
       churn train -> UC model@champion -> gold_churn_predictions
       network train -> UC model@champion -> gold_network_anomalies
       churn score -> CLV train -> UC model@champion -> gold_clv_segments
  -> App, Genie, AI/BI e Graph Intelligence
```

Todos os nomes de catálogo, schema, volume, experimentos, modelos e outputs vêm de variáveis do DAB. Os jobs não possuem `schedule` nem `trigger`, têm `max_concurrent_runs: 1` e só geram custo quando iniciados manualmente. O deploy do bundle cria ou atualiza a configuração; não inicia processamento.

## Produtos de dados

| Camada | Fonte/saída | Semântica |
|---|---|---|
| Raw | `dim_*`, `fact_*`, `ml_churn_features` no volume UC | Dados sintéticos determinísticos, seed e data de referência explícitas |
| Bronze | `bronze_*` | Ingestão por Auto Loader com `_ingested_at`; o job manual reinicia checkpoints por snapshot |
| Silver | `silver_*` | Deduplicação, watermark e expectations de contrato |
| Gold BI | receita, assinantes, ARPU, rede, satisfação e billing | Materialized views consumíveis pelo App/Genie |
| Gold ML | `gold_churn_predictions` | Probabilidade produzida exclusivamente pelo modelo UC |
| Gold ML | `gold_network_anomalies` | Score de decisão do Isolation Forest; não é probabilidade de falha ou SLA |
| Gold ML | `gold_clv_segments` | Segmentação K-Means descritiva; não é estimativa causal de lifetime value |

Cada tabela de scoring grava `model_name`, `model_version`, `model_run_id`, `score_source='uc_model'` e `scored_at`. O overwrite permanece explícito e ocorre somente dentro do job manual.

## Churn: três conceitos diferentes

1. `churned`: evento sintético de cancelamento observado depois do snapshot de features.
2. `synthetic_churn_propensity`: regra determinística usada para explicar a geração demonstrativa. Não é modelo nem probabilidade calibrada.
3. `churn_probability`: saída do modelo registrado no Unity Catalog. Somente `ml/churn/score.py` cria esse campo.

`churn_risk_score` foi mantido apenas como alias legado de `synthetic_churn_propensity` para não quebrar consumidores existentes. Ele é excluído do treinamento de churn e do treinamento CLV. O Genie recebe instrução explícita para nunca tratá-lo como probabilidade ML.

### Label, horizonte e split

O fonte original recuperado usava `estado = inactivo` no mesmo snapshot e, portanto, não tinha horizonte preditivo. A versão DAB corrige o contrato: `feature_snapshot_at` marca o corte, `label_observed_at` ocorre 30 dias depois por padrão e `churned` representa um evento sintético futuro apenas para clientes ativos. O treinamento falha fechado se a tabela não contiver esse ordenamento temporal ou se o horizonte divergir do parâmetro/modelo registrado.

Ainda existe uma limitação importante: há uma única coorte sintética. O split continua aleatório estratificado, identificado no MLflow como `stratified_random_snapshot`, e não comprova generalização temporal. Para produção, o cliente deve construir várias safras reais, excluir sinais posteriores ao corte e avaliar por split out-of-time. Métricas de calibração e estabilidade devem virar gates de promoção.

## Ciclos de modelo

### Churn

- compara LightGBM, XGBoost e regressão logística apenas sobre clientes ativos no corte;
- seleciona o campeão por AUC-PR, adequada ao desbalanceamento;
- registra o pipeline completo de preparação e probabilidade no UC Model Registry;
- a regra sintética é explicitamente excluída das features.

### Anomalia de rede

- empacota `StandardScaler` e `IsolationForest` em um único artefato;
- usa `decision_function`: valores menores são mais anômalos e `< 0` define anomalia;
- não interpreta o score como disponibilidade, causalidade ou crédito de SLA.

### CLV/valor

- usa K-Means com seleção de `K` por silhouette em amostra limitada;
- consome a `churn_probability` do último scoring real do campeão, nunca a regra sintética;
- persiste o mapa de nomes de negócio como artefato do mesmo run MLflow.

## Recursos DAB e operação

Os recursos estão em `resources/data_ml.yml`:

- `quetzal_synthetic_data_generation`: cria o landing sintético em cinco tarefas dependentes;
- `quetzal_lakeflow_refresh`: reconstrói o pipeline medallion com full refresh manual, porque o gerador sobrescreve o landing Parquet e cada snapshot precisa reiniciar os checkpoints do Auto Loader;
- `quetzal_ml_refresh`: treina, registra e executa os três scorings, com CLV dependente do churn.

Validação sem custo de processamento:

```bash
databricks bundle validate -t demo --profile <perfil>
```

Execução é opcional, destrutiva sobre as saídas da demo e exige autorização específica:

```bash
databricks bundle run -t demo quetzal_synthetic_data_generation --profile <perfil>
databricks bundle run -t demo quetzal_lakeflow_refresh --profile <perfil>
databricks bundle run -t demo quetzal_ml_refresh --profile <perfil>
```

Nunca execute os três comandos apenas para provar que o deploy funcionou. Primeiro revise variáveis, volume, permissões, custo estimado, outputs que serão sobrescritos e plano de rollback.

O `quetzal_lakeflow_refresh` executa um full refresh deliberado. Isso aumenta o custo de cada execução, mas evita misturar checkpoints de snapshots anteriores com arquivos sobrescritos pelo gerador. Como o job não possui agenda, o custo só ocorre após uma ação manual explícita.
