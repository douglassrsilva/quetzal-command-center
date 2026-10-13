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

import lightgbm as lgb
import mlflow
import mlflow.sklearn
import pandas as pd
import xgboost as xgb
from mlflow import MlflowClient
from mlflow.models import infer_signature
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from sklearn.base import BaseEstimator
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.common import require_columns, uc_identifier

NUMERIC_FEATURES = [
    "edad", "antiguedad_dias", "credit_score", "nps_ultimo",
    "gasto_mensual_total", "total_facturas", "avg_monto_factura",
    "facturas_vencidas", "avg_dias_atraso", "max_dias_atraso",
    "total_tickets", "tickets_cancelacion", "avg_csat", "total_recontactos",
    "total_suscripciones", "suscripciones_activas",
]
CATEGORICAL_FEATURES = ["pais_codigo", "segmento_id", "canal_adquisicion"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "churned"
TEMPORAL_CONTRACT_COLUMNS = [
    "estado", "feature_snapshot_at", "label_observed_at",
    "label_horizon_days", "target_definition", "data_origin",
]


@dataclass
class ChurnProbabilityModel(BaseEstimator):
    """Sklearn-compatible wrapper whose prediction is a probability, not a class."""

    estimator: Pipeline

    def predict(self, frame):
        return self.estimator.predict_proba(frame)[:, 1]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and register the Quetzal churn champion.")
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--model-alias", default="champion")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-train-rows", type=int, default=250_000)
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--label-horizon-days", type=int, default=30)
    return parser.parse_args()


def _estimator(classifier) -> Pipeline:
    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    return Pipeline([
        ("features", ColumnTransformer([
            ("numeric", numeric, NUMERIC_FEATURES),
            ("categorical", categorical, CATEGORICAL_FEATURES),
        ])),
        ("classifier", classifier),
    ])


def validate_temporal_contract(source, expected_horizon_days: int) -> None:
    require_columns(source.columns, TEMPORAL_CONTRACT_COLUMNS, source="churn source")
    horizons = sorted(
        int(row["label_horizon_days"])
        for row in source.select("label_horizon_days").distinct().collect()
    )
    if horizons != [expected_horizon_days]:
        raise ValueError(
            f"Churn source horizon {horizons} does not match configured horizon {expected_horizon_days}"
        )
    invalid_temporal_order = source.filter(
        F.to_date("label_observed_at") <= F.to_date("feature_snapshot_at")
    ).limit(1).count()
    if invalid_temporal_order:
        raise ValueError("Churn labels must be observed after their feature snapshot")


def main() -> None:
    args = _args()
    source_table = uc_identifier(args.source_table)
    model_name = uc_identifier(args.model_name)
    if not 0 < args.test_size < 1:
        raise ValueError("test-size must be between 0 and 1")
    if args.label_horizon_days <= 0:
        raise ValueError("label-horizon-days must define a future observation window")

    spark = SparkSession.builder.getOrCreate()
    source_all = spark.table(source_table)
    require_columns(source_all.columns, FEATURES + [TARGET], source=source_table)
    validate_temporal_contract(source_all, args.label_horizon_days)
    source = source_all.filter(F.lower("estado") == "activo")
    source_rows = source_all.count()
    total_rows = source.count()
    if total_rows == 0:
        raise ValueError(f"{source_table} has no eligible active customers")
    train_rows = min(total_rows, args.max_train_rows) if args.max_train_rows > 0 else total_rows
    frame = (
        source.select(*(FEATURES + [TARGET]))
        .orderBy(F.rand(args.seed))
        .limit(train_rows)
        .toPandas()
    )
    frame[TARGET] = pd.to_numeric(frame[TARGET], errors="raise").astype(int)
    if frame[TARGET].nunique() != 2:
        raise ValueError("Churn training requires both target classes")

    x_train, x_test, y_train, y_test = train_test_split(
        frame[FEATURES], frame[TARGET], test_size=args.test_size,
        random_state=args.seed, stratify=frame[TARGET],
    )
    positive_weight = float((y_train == 0).sum() / max((y_train == 1).sum(), 1))
    candidates = {
        "lightgbm": lgb.LGBMClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.05, num_leaves=31,
            min_child_samples=50, class_weight="balanced", random_state=args.seed,
            n_jobs=-1, verbose=-1,
        ),
        "xgboost": xgb.XGBClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.05,
            scale_pos_weight=positive_weight, min_child_weight=5, subsample=0.8,
            colsample_bytree=0.8, random_state=args.seed, n_jobs=-1,
            eval_metric="aucpr", verbosity=0,
        ),
        "logistic_regression": LogisticRegression(
            class_weight="balanced", max_iter=1_000, random_state=args.seed,
        ),
    }

    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(args.experiment_name)
    results: dict[str, dict] = {}
    with mlflow.start_run(run_name="churn_model_comparison") as parent:
        mlflow.log_params({
            "source_table": source_table,
            "source_rows": source_rows,
            "eligible_active_rows": total_rows,
            "sample_rows": len(frame),
            "split_strategy": "stratified_random_snapshot",
            "test_size": args.test_size,
            "seed": args.seed,
            "label_definition": "synthetic cancellation event after feature snapshot",
            "label_horizon_days": args.label_horizon_days,
            "data_origin": "synthetic_demo",
        })
        mlflow.log_dict({
            "features": FEATURES,
            "target": TARGET,
            "excluded_from_training": ["synthetic_churn_propensity", "churn_risk_score", "estado"],
            "limitations": [
                "The future churn event is synthetic and is not an observed production cancellation.",
                "A single synthetic cohort supports a future horizon but not temporal out-of-time validation.",
            ],
        }, "feature_contract.json")

        for algorithm, classifier in candidates.items():
            with mlflow.start_run(run_name=algorithm, nested=True) as child:
                estimator = _estimator(classifier)
                estimator.fit(x_train, y_train)
                probability = estimator.predict_proba(x_test)[:, 1]
                prediction = (probability >= 0.5).astype(int)
                metrics = {
                    "auc_roc": float(roc_auc_score(y_test, probability)),
                    "auc_pr": float(average_precision_score(y_test, probability)),
                    "f1": float(f1_score(y_test, prediction, zero_division=0)),
                    "precision": float(precision_score(y_test, prediction, zero_division=0)),
                    "recall": float(recall_score(y_test, prediction, zero_division=0)),
                }
                mlflow.log_param("algorithm", algorithm)
                mlflow.log_metrics(metrics)
                probability_model = ChurnProbabilityModel(estimator)
                signature = infer_signature(x_test.head(20), probability_model.predict(x_test.head(20)))
                mlflow.sklearn.log_model(
                    probability_model,
                    artifact_path="model",
                    signature=signature,
                    input_example=x_test.head(5),
                )
                results[algorithm] = {"metrics": metrics, "run_id": child.info.run_id}

        best_algorithm = max(results, key=lambda name: results[name]["metrics"]["auc_pr"])
        mlflow.set_tag("selected_algorithm", best_algorithm)
        mlflow.log_dict(results, "model_comparison.json")
        parent_run_id = parent.info.run_id

    best = results[best_algorithm]
    registered = mlflow.register_model(f"runs:/{best['run_id']}/model", model_name)
    client = MlflowClient()
    client.set_registered_model_alias(model_name, args.model_alias, registered.version)
    for key, value in {
        "quetzal_algorithm": best_algorithm,
        "quetzal_auc_pr": best["metrics"]["auc_pr"],
        "quetzal_parent_run_id": parent_run_id,
        "quetzal_label_horizon_days": args.label_horizon_days,
        "quetzal_score_semantics": "model_probability",
        "quetzal_data_origin": "synthetic_demo",
    }.items():
        client.set_model_version_tag(model_name, registered.version, key, str(value))

    print(json.dumps({
        "status": "registered",
        "model_name": model_name,
        "model_version": str(registered.version),
        "alias": args.model_alias,
        "algorithm": best_algorithm,
        "parent_run_id": parent_run_id,
        "metrics": best["metrics"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
