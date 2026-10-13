from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_data_and_ml_jobs_are_manual_only():
    resource = _read("resources/data_ml.yml")
    assert "execution_mode: manual-only" in resource
    assert "schedule:" not in resource
    assert "trigger:" not in resource
    assert "continuous: false" in resource
    assert "full_refresh: true" in resource


def test_lakeflow_source_is_parameterized_and_contains_all_layers():
    resource = _read("resources/data_ml.yml")
    bronze = _read("lakeflow/bronze/ingestion.py")
    assert "quetzal.volume_path" in bronze
    assert "classic_stable_douglas" not in bronze
    for path in (
        "../lakeflow/bronze/ingestion.py",
        "../lakeflow/silver/quality.py",
        "../lakeflow/gold/business_kpis.py",
    ):
        assert path in resource


def test_synthetic_propensity_is_not_promoted_to_model_probability():
    generator = _read("notebooks/synthetic_data/05_churn_interacciones.py")
    churn_score = _read("ml/churn/score.py")
    assert 'withColumn("synthetic_churn_propensity"' in generator
    assert 'withColumn("churn_risk_score", F.col("synthetic_churn_propensity"))' in generator
    assert 'withColumn("churn_probability", predict_probability' in churn_score
    assert "synthetic_churn_propensity" not in churn_score


def test_churn_training_requires_a_future_temporal_contract():
    bundle = _read("databricks.yml")
    generator = _read("notebooks/synthetic_data/05_churn_interacciones.py")
    training = _read("ml/churn/train.py")
    assert 'churn_label_horizon_days:' in bundle
    assert 'default: "30"' in bundle
    assert 'F.date_add(F.to_date(F.lit(REFERENCE_DATE)), CHURN_LABEL_HORIZON_DAYS)' in generator
    assert "Churn labels must be observed after their feature snapshot" in training
    assert 'source_all.filter(F.lower("estado") == "activo")' in training


def test_synthetic_billing_uses_typed_reference_dates():
    billing = _read("notebooks/synthetic_data/03_suscripciones_billing.py")
    assert "F.to_date(F.lit(REFERENCE_DATE))" in billing
    assert 'F.coalesce(F.col("fecha_fin"), F.lit(REFERENCE_DATE))' not in billing


def test_scoring_outputs_are_attributed_to_registered_model_runs():
    for relative in ("ml/churn/score.py", "ml/network/score.py", "ml/clv/score.py"):
        source = _read(relative)
        assert 'F.lit(version.run_id)' in source
        assert 'F.lit(str(version.version))' in source
        assert 'F.lit("uc_model")' in source


def test_uc_model_version_tags_avoid_reserved_characters():
    training_files = (
        "ml/churn/train.py",
        "ml/network/train.py",
        "ml/clv/train.py",
    )
    for relative in training_files:
        source = _read(relative)
        assert '"quetzal.' not in source
        assert '"quetzal_' in source
    assert 'get("quetzal_label_horizon_days")' in _read("ml/churn/score.py")


def test_ml_python_tasks_support_the_serverless_wrapper_path():
    resource = _read("resources/data_ml.yml")
    assert "mlflow==3.5.0" in resource
    files = (
        "ml/churn/train.py",
        "ml/churn/score.py",
        "ml/network/train.py",
        "ml/network/score.py",
        "ml/clv/train.py",
        "ml/clv/score.py",
    )
    for relative in files:
        source = _read(relative)
        assert 'globals().get("__file__") or globals().get("filename")' in source
        assert "Path(__file__)" not in source


def test_ml_experiments_use_self_contained_shared_names():
    bundle = _read("databricks.yml")
    resource = _read("resources/data_ml.yml")
    assert "Workspace experiment prefix" in bundle
    for suffix in (
        "-churn-prediction",
        "-network-anomaly-detection",
        "-clv-segmentation",
    ):
        assert f"${{var.ml_experiment_root}}{suffix}" in resource
    for legacy_path in (
        "${var.ml_experiment_root}/churn_prediction",
        "${var.ml_experiment_root}/network_anomaly_detection",
        "${var.ml_experiment_root}/clv_segmentation",
    ):
        assert legacy_path not in resource


def test_clv_uses_model_churn_probability_not_the_demo_rule():
    training = _read("ml/clv/train.py")
    assert '"churn_probability"' in training
    assert '"excluded_from_training": ["synthetic_churn_propensity", "churn_risk_score"]' in training


def test_stage_b_sources_do_not_embed_personal_workspace_paths():
    files = [
        ROOT / "resources/data_ml.yml",
        *list((ROOT / "lakeflow").rglob("*.py")),
        *list((ROOT / "ml").rglob("*.py")),
        *list((ROOT / "notebooks/synthetic_data").glob("*.py")),
    ]
    forbidden = ("douglas.s@databricks.com", "/Users/douglas.s", "classic_stable_douglas_s_catalog")
    for path in files:
        content = path.read_text(encoding="utf-8")
        assert not any(value in content for value in forbidden), path
