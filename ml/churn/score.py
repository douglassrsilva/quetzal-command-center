from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_PATH = globals().get("__file__") or globals().get("filename")
if not _SCRIPT_PATH:
    raise RuntimeError("Unable to resolve the Spark Python task source path")
_PROJECT_ROOT = Path(_SCRIPT_PATH).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import mlflow
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType

from ml.churn.train import FEATURES, TARGET
from ml.common import (
    model_version_by_alias,
    require_columns,
    uc_identifier,
)

DISPLAY_COLUMNS = [
    "cliente_id", "pais_codigo", "segmento_id", "edad", "antiguedad_dias",
    "credit_score", "nps_ultimo", "gasto_mensual_total", "total_facturas",
    "facturas_vencidas", "total_tickets", "tickets_cancelacion",
    "suscripciones_activas",
]
RESULT_COLUMNS = DISPLAY_COLUMNS + [TARGET]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score churn from the registered UC champion.")
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--output-table", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-alias", default="champion")
    parser.add_argument("--label-horizon-days", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    args = _args()
    source_table = uc_identifier(args.source_table)
    output_table = uc_identifier(args.output_table)
    model_name = uc_identifier(args.model_name)
    spark = SparkSession.builder.getOrCreate()
    source_all = spark.table(source_table)
    require_columns(source_all.columns, FEATURES + DISPLAY_COLUMNS + ["estado"], source=source_table)
    if TARGET not in source_all.columns:
        source_all = source_all.withColumn(TARGET, F.lit(None).cast("int"))
    source = source_all.filter(F.lower("estado") == "activo")

    _, version = model_version_by_alias(model_name, args.model_alias)
    registered_horizon = (version.tags or {}).get("quetzal_label_horizon_days")
    if registered_horizon != str(args.label_horizon_days):
        raise ValueError(
            f"Model horizon {registered_horizon!r} does not match configured horizon {args.label_horizon_days}"
        )
    model_uri = f"models:/{model_name}@{args.model_alias}"
    predict_probability = mlflow.pyfunc.spark_udf(
        spark, model_uri=model_uri, result_type=DoubleType(), env_manager="local",
    )
    model_input = F.struct(*[F.col(name).alias(name) for name in FEATURES])
    scored = (
        source.dropDuplicates(["cliente_id"])
        .withColumn("churn_probability", predict_probability(model_input))
        .withColumn("churn_predicted", (F.col("churn_probability") >= 0.5).cast("int"))
        .withColumn(
            "risk_tier",
            F.when(F.col("churn_probability") >= 0.80, "critico")
            .when(F.col("churn_probability") >= 0.60, "alto")
            .when(F.col("churn_probability") >= 0.30, "medio")
            .otherwise("bajo"),
        )
        .withColumn("scored_at", F.current_timestamp())
        .withColumn("model_name", F.lit(model_name))
        .withColumn("model_version", F.lit(str(version.version)))
        .withColumn("model_run_id", F.lit(version.run_id))
        .withColumn("score_source", F.lit("uc_model"))
        .withColumn("label_definition", F.lit("synthetic cancellation event after feature snapshot"))
        .withColumn("prediction_horizon_days", F.lit(args.label_horizon_days))
        .select(
            *RESULT_COLUMNS, "churn_probability", "churn_predicted", "risk_tier",
            "scored_at", "model_name", "model_version", "model_run_id",
            "score_source", "label_definition", "prediction_horizon_days",
        )
    )
    scored.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(output_table)
    print(json.dumps({
        "status": "scored",
        "output_table": output_table,
        "rows": spark.table(output_table).count(),
        "model_name": model_name,
        "model_version": str(version.version),
        "model_run_id": version.run_id,
        "score_source": "uc_model",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
