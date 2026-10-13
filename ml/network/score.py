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

from ml.common import (
    model_version_by_alias,
    require_columns,
    uc_identifier,
)
from ml.network.train import FEATURES

RESULT_COLUMNS = [
    "torre_id", "pais_codigo", "ciudad", "tecnologia", "timestamp",
    "latencia_ms", "throughput_mbps", "packet_loss_pct", "uso_capacidad_pct",
    "temperatura_equipo_c", "usuarios_conectados", "alerta",
]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score network telemetry with the UC champion.")
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--output-table", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-alias", default="champion")
    return parser.parse_args()


def main() -> None:
    args = _args()
    source_table = uc_identifier(args.source_table)
    output_table = uc_identifier(args.output_table)
    model_name = uc_identifier(args.model_name)
    spark = SparkSession.builder.getOrCreate()
    source = spark.table(source_table)
    require_columns(source.columns, FEATURES + RESULT_COLUMNS, source=source_table)
    _, version = model_version_by_alias(model_name, args.model_alias)
    predict_score = mlflow.pyfunc.spark_udf(
        spark,
        model_uri=f"models:/{model_name}@{args.model_alias}",
        result_type=DoubleType(),
        env_manager="local",
    )
    model_input = F.struct(*[F.col(name).alias(name) for name in FEATURES])
    scored = (
        source
        .withColumn("anomaly_score", predict_score(model_input))
        .withColumn("is_anomaly", (F.col("anomaly_score") < 0).cast("int"))
        .withColumn(
            "anomaly_severity",
            F.when(F.col("anomaly_score") < -0.15, "critica")
            .when(F.col("anomaly_score") < -0.10, "alta")
            .when(F.col("anomaly_score") < -0.05, "media")
            .otherwise("normal"),
        )
        .withColumn("scored_at", F.current_timestamp())
        .withColumn("model_name", F.lit(model_name))
        .withColumn("model_version", F.lit(str(version.version)))
        .withColumn("model_run_id", F.lit(version.run_id))
        .withColumn("score_source", F.lit("uc_model"))
        .select(
            *RESULT_COLUMNS, "anomaly_score", "is_anomaly", "anomaly_severity",
            "scored_at", "model_name", "model_version", "model_run_id", "score_source",
        )
    )
    scored.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(output_table)
    print(json.dumps({
        "status": "scored", "output_table": output_table,
        "rows": spark.table(output_table).count(), "model_name": model_name,
        "model_version": str(version.version), "model_run_id": version.run_id,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
