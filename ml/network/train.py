from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_PATH = globals().get("__file__") or globals().get("filename")
if not _SCRIPT_PATH:
    raise RuntimeError("Unable to resolve the Spark Python task source path")
_PROJECT_ROOT = Path(_SCRIPT_PATH).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import mlflow
import mlflow.sklearn
import numpy as np
from mlflow import MlflowClient
from mlflow.models import infer_signature
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from sklearn.base import BaseEstimator
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.common import require_columns, uc_identifier

FEATURES = [
    "latencia_ms", "throughput_mbps", "packet_loss_pct",
    "uso_capacidad_pct", "temperatura_equipo_c", "usuarios_conectados",
]


@dataclass
class AnomalyScoreModel(BaseEstimator):
    """Packages the scaler and Isolation Forest as one registered artifact."""

    estimator: Pipeline

    def predict(self, frame):
        return self.estimator.decision_function(frame)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and register network anomaly detection.")
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--model-alias", default="champion")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-train-rows", type=int, default=500_000)
    parser.add_argument("--contamination", type=float, default=0.05)
    return parser.parse_args()


def main() -> None:
    args = _args()
    source_table = uc_identifier(args.source_table)
    model_name = uc_identifier(args.model_name)
    if not 0 < args.contamination <= 0.5:
        raise ValueError("contamination must be in (0, 0.5]")
    spark = SparkSession.builder.getOrCreate()
    source = spark.table(source_table)
    require_columns(source.columns, FEATURES, source=source_table)
    total_rows = source.count()
    if total_rows == 0:
        raise ValueError(f"{source_table} is empty")
    train_rows = min(total_rows, args.max_train_rows) if args.max_train_rows > 0 else total_rows
    frame = source.select(*FEATURES).orderBy(F.rand(args.seed)).limit(train_rows).toPandas().fillna(0)

    estimator = Pipeline([
        ("scale", StandardScaler()),
        ("isolation_forest", IsolationForest(
            n_estimators=200,
            max_samples=min(10_000, len(frame)),
            contamination=args.contamination,
            max_features=1.0,
            random_state=args.seed,
            n_jobs=-1,
        )),
    ])
    estimator.fit(frame)
    score = estimator.decision_function(frame)
    anomaly_count = int((score < 0).sum())
    model = AnomalyScoreModel(estimator)

    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(args.experiment_name)
    with mlflow.start_run(run_name="isolation_forest_network") as run:
        mlflow.log_params({
            "source_table": source_table,
            "source_rows": total_rows,
            "sample_rows": len(frame),
            "contamination": args.contamination,
            "seed": args.seed,
            "algorithm": "IsolationForest",
            "data_origin": "synthetic_demo",
        })
        mlflow.log_metrics({
            "n_anomalies": anomaly_count,
            "pct_anomalies": 100.0 * anomaly_count / len(frame),
            "anomaly_score_mean": float(np.mean(score)),
            "anomaly_score_std": float(np.std(score)),
        })
        mlflow.log_dict({
            "features": FEATURES,
            "score_semantics": "Isolation Forest decision_function; lower is more anomalous; score < 0 is anomaly",
            "limitations": ["Unsupervised anomaly score is not outage probability or contractual SLA."],
        }, "feature_contract.json")
        signature = infer_signature(frame.head(20), model.predict(frame.head(20)))
        mlflow.sklearn.log_model(model, artifact_path="model", signature=signature, input_example=frame.head(5))
        run_id = run.info.run_id

    registered = mlflow.register_model(f"runs:/{run_id}/model", model_name)
    client = MlflowClient()
    client.set_registered_model_alias(model_name, args.model_alias, registered.version)
    for key, value in {
        "quetzal_algorithm": "IsolationForest",
        "quetzal_score_semantics": "decision_function",
        "quetzal_data_origin": "synthetic_demo",
    }.items():
        client.set_model_version_tag(model_name, registered.version, key, str(value))
    print(json.dumps({
        "status": "registered", "model_name": model_name,
        "model_version": str(registered.version), "alias": args.model_alias,
        "run_id": run_id, "sample_rows": len(frame), "anomalies": anomaly_count,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
