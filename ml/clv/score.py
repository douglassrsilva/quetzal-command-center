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
from pyspark.sql.types import LongType

from ml.clv.train import FEATURES, feature_frame
from ml.common import (
    model_version_by_alias,
    require_columns,
    uc_identifier,
)

RESULT_COLUMNS = [
    "cliente_id", "pais_codigo", "segmento_id", "estado",
    "gasto_mensual_total", "revenue_lifetime_est", "antiguedad_dias",
    "suscripciones_activas", "total_suscripciones", "credit_score",
    "nps_ultimo", "churn_probability", "ratio_vencidas", "avg_dias_atraso",
    "synthetic_churn_propensity", "churn_risk_score",
]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score CLV segments with the UC champion.")
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--churn-table", required=True)
    parser.add_argument("--output-table", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-alias", default="champion")
    return parser.parse_args()


def main() -> None:
    args = _args()
    source_table = uc_identifier(args.source_table)
    churn_table = uc_identifier(args.churn_table)
    output_table = uc_identifier(args.output_table)
    model_name = uc_identifier(args.model_name)
    spark = SparkSession.builder.getOrCreate()
    source = feature_frame(spark, source_table, churn_table)
    require_columns(source.columns, FEATURES + RESULT_COLUMNS, source=source_table)
    client, version = model_version_by_alias(model_name, args.model_alias)
    mapping_path = client.download_artifacts(version.run_id, "segment_map.json")
    with open(mapping_path, encoding="utf-8") as handle:
        segment_map = json.load(handle)
    if not segment_map:
        raise ValueError(f"Model {model_name} version {version.version} has no segment mapping")

    predict_segment = mlflow.pyfunc.spark_udf(
        spark,
        model_uri=f"models:/{model_name}@{args.model_alias}",
        result_type=LongType(),
        env_manager="local",
    )
    model_input = F.struct(*[F.col(name).alias(name) for name in FEATURES])
    mapping_items = [item for pair in sorted(segment_map.items()) for item in (F.lit(pair[0]), F.lit(pair[1]))]
    mapping_expression = F.create_map(*mapping_items)
    scored = (
        source.dropDuplicates(["cliente_id"])
        .withColumn("segment", predict_segment(model_input).cast("int"))
        .withColumn("segment_name", mapping_expression[F.col("segment").cast("string")])
        .withColumn("scored_at", F.current_timestamp())
        .withColumn("model_name", F.lit(model_name))
        .withColumn("model_version", F.lit(str(version.version)))
        .withColumn("model_run_id", F.lit(version.run_id))
        .withColumn("score_source", F.lit("uc_model"))
        .select(
            *RESULT_COLUMNS, "segment", "segment_name", "scored_at",
            "model_name", "model_version", "model_run_id", "score_source",
        )
    )
    scored.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(output_table)
    print(json.dumps({
        "status": "scored", "output_table": output_table,
        "rows": spark.table(output_table).count(), "model_name": model_name,
        "model_version": str(version.version), "model_run_id": version.run_id,
        "segment_map": segment_map,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
