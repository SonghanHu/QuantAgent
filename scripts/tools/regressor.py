"""Regression with scikit-learn: pick model, features, and optional hyperparameter search."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from agent.workspace import Workspace

import numpy as np
import pandas as pd

_VALID_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")
from scipy.stats import loguniform, randint, uniform
from sklearn.datasets import make_regression
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Lasso, LinearRegression, Ridge
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import RandomizedSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

EstimatorFactory = Callable[[int], Any]


def _normalize_model_name(name: str) -> str:
    return name.lower().strip().replace(" ", "_").replace("-", "_")


def _estimator_factories() -> dict[str, EstimatorFactory]:
    return {
        "linear_regression": lambda rs: LinearRegression(),
        "lr": lambda rs: LinearRegression(),
        "ols": lambda rs: LinearRegression(),
        "ridge": lambda rs: Ridge(),
        "lasso": lambda rs: Lasso(max_iter=100_000, random_state=rs),
        "elasticnet": lambda rs: ElasticNet(max_iter=100_000, random_state=rs),
        "elastic_net": lambda rs: ElasticNet(max_iter=100_000, random_state=rs),
        "enet": lambda rs: ElasticNet(max_iter=100_000, random_state=rs),
        "random_forest": lambda rs: RandomForestRegressor(
            n_estimators=100, random_state=rs, n_jobs=-1
        ),
        "rf": lambda rs: RandomForestRegressor(n_estimators=100, random_state=rs, n_jobs=-1),
        "gradient_boosting": lambda rs: GradientBoostingRegressor(random_state=rs),
        "gbr": lambda rs: GradientBoostingRegressor(random_state=rs),
        "gbm": lambda rs: GradientBoostingRegressor(random_state=rs),
        "svr": lambda rs: SVR(),
    }


def _param_distributions() -> dict[str, dict[str, Any]]:
    return {
        "ridge": {"model__alpha": loguniform(1e-4, 50)},
        "lasso": {"model__alpha": loguniform(1e-5, 10)},
        "elasticnet": {
            "model__alpha": loguniform(1e-5, 5),
            "model__l1_ratio": uniform(0.0, 1.0),
        },
        "elastic_net": {
            "model__alpha": loguniform(1e-5, 5),
            "model__l1_ratio": uniform(0.0, 1.0),
        },
        "enet": {
            "model__alpha": loguniform(1e-5, 5),
            "model__l1_ratio": uniform(0.0, 1.0),
        },
        "random_forest": {
            "model__n_estimators": randint(40, 250),
            "model__max_depth": [None, 4, 8, 16, 24],
            "model__min_samples_leaf": randint(1, 8),
        },
        "rf": {
            "model__n_estimators": randint(40, 250),
            "model__max_depth": [None, 4, 8, 16, 24],
            "model__min_samples_leaf": randint(1, 8),
        },
        "gradient_boosting": {
            "model__learning_rate": loguniform(0.01, 0.4),
            "model__max_depth": randint(2, 8),
            "model__n_estimators": randint(50, 250),
        },
        "gbr": {
            "model__learning_rate": loguniform(0.01, 0.4),
            "model__max_depth": randint(2, 8),
            "model__n_estimators": randint(50, 250),
        },
        "gbm": {
            "model__learning_rate": loguniform(0.01, 0.4),
            "model__max_depth": randint(2, 8),
            "model__n_estimators": randint(50, 250),
        },
        "svr": {
            "model__C": loguniform(1e-2, 200),
            "model__epsilon": loguniform(1e-4, 0.5),
            "model__kernel": ["rbf", "linear"],
        },
    }


def _parse_feature_columns(raw: list[str] | str | None) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    raise TypeError("feature_columns must be str, list[str], or None")


def _load_frame(data_path: str | None, *, n_samples: int, n_features: int, target_column: str, rs: int) -> pd.DataFrame:
    if not data_path:
        X, y = make_regression(
            n_samples=n_samples,
            n_features=n_features,
            noise=15.0,
            random_state=rs,
        )
        cols = [f"f{i}" for i in range(n_features)]
        df = pd.DataFrame(X, columns=cols)
        df[target_column] = y
        return df
    path = Path(data_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"data_path not found: {path}")
    suf = path.suffix.lower()
    if suf in (".parquet", ".pq"):
        return pd.read_parquet(path)
    if suf in (".csv", ".txt"):
        return pd.read_csv(path)
    raise ValueError(f"Unsupported data_path suffix: {suf} (use .csv or .parquet)")


def _maybe_add_forward_return_target(df: pd.DataFrame, target_column: str) -> tuple[pd.DataFrame, str | None]:
    """
    If *target_column* is missing but OHLCV price columns exist (typical yfinance panel),
    add *target_column* = one-step forward simple return of the best available price series.

    Returns (df, source_column_used_or_None).
    """
    if target_column in df.columns:
        return df, None
    candidates = [
        "Adj Close",
        "Adj_Close",
        "AdjClose",
        "adj_close",
        "Close",
        "close",
    ]
    col = next((c for c in candidates if c in df.columns), None)
    if col is None:
        lower_map = {str(x).lower().replace(" ", "_"): x for x in df.columns}
        for key in ("adj_close", "close"):
            if key in lower_map:
                col = lower_map[key]
                break
    if col is None:
        return df, None
    out = df.copy()
    px = pd.to_numeric(out[col], errors="coerce")
    out[target_column] = px.pct_change().shift(-1)
    return out, col


def _resolve_features(df: pd.DataFrame, target_column: str, explicit: list[str] | None) -> list[str]:
    if explicit is not None and len(explicit) > 0:
        missing = [c for c in explicit if c not in df.columns]
        if missing:
            raise KeyError(f"feature_columns not in data: {missing}; available={list(df.columns)}")
        return explicit
    num = df.select_dtypes(include=[np.number]).columns.tolist()
    if target_column in num:
        num.remove(target_column)
    if not num:
        raise ValueError("No numeric feature columns; set feature_columns explicitly.")
    return num


def _canonical_model_key_for_spec(spec: str | None) -> str | None:
    """
    Convert user/plan requested model family text into one of the internal registry keys.
    Returns None if not recognized.
    """
    if spec is None:
        return None
    s = str(spec).strip().lower().replace(" ", "_").replace("-", "_")
    if not s:
        return None

    if "random_forest" in s or "randomforest" in s or s in ("rf", "random_forest_regressor", "randomforestregressor"):
        return "random_forest"
    if s in ("ridge", "ridge_regressor"):
        return "ridge"
    if "linear_regression" in s or s in ("lr", "linearregression", "ols", "ordinary_least_squares"):
        return "linear_regression"
    if s in ("lasso",):
        return "lasso"
    if s in ("elasticnet", "elastic_net", "enet", "elastic_net_regressor"):
        return "elasticnet"
    if "gradient_boosting" in s or "gbm" in s or "gradientboosting" in s:
        return "gradient_boosting"
    if s in ("svr", "support_vector_regression", "supportvectorregression"):
        return "svr"
    if s in ("gbm", "gbr", "gboost", "gradient_boosting_regressor"):
        return "gradient_boosting"
    return None


def _model_display_name(key: str) -> str:
    return {
        "random_forest": "RandomForestRegressor",
        "ridge": "Ridge",
        "linear_regression": "LinearRegression",
        "lasso": "Lasso",
        "elasticnet": "ElasticNet",
        "gradient_boosting": "GradientBoostingRegressor",
        "svr": "SVR",
    }.get(key, key)


def _infer_target_horizon(target_column: str, derived_from_price: str | None) -> str:
    """
    Best-effort horizon inference for the auto-created forward-return target.
    """
    if derived_from_price is not None and target_column == "target":
        # In this pipeline, the auto-added target is always forward 1-period return.
        return "next-day return"

    t = str(target_column).lower()
    if "week" in t or "next_week" in t:
        return "next-week return"
    if "5d" in t or "5_day" in t or "5_days" in t:
        return "next-5 trading days return"
    if "3d" in t or "3_day" in t or "3_days" in t:
        return "next-3 trading days return"
    if "day" in t:
        return "forward return (inferred from target column)"
    return "forward return (unknown horizon)"


def _build_pipeline(base_estimator: Any) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", base_estimator),
        ]
    )


def _jsonify_params(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if hasattr(v, "item"):
            out[k] = v.item()
        elif isinstance(v, (np.floating, np.integer)):
            out[k] = float(v)
        elif isinstance(v, np.ndarray):
            out[k] = v.tolist()
        else:
            out[k] = v
    return out


def train_model(
    model_name: str = "ridge",
    requested_model_name: str | None = None,
    feature_columns: list[str] | str | None = None,
    target_column: str = "target",
    tune_hyperparameters: bool = False,
    data_path: str | None = None,
    random_state: int = 42,
    test_size: float = 0.2,
    n_samples: int = 500,
    n_features: int = 8,
    cv_folds: int = 3,
    tuning_iter: int = 16,
    workspace: Workspace | None = None,
) -> dict[str, Any]:
    """
    Fit a regression model: you choose **model**, **which columns are features**, and **whether to tune**.

    If `requested_model_name` is provided, the tool will record whether the executed model matches the request
    (spec-deviation detection for evaluation / debugging).

    - **Data:** ``data_path`` to ``.csv`` / ``.parquet``, or omit to use synthetic regression data
      (column names ``f0..f{n-1}`` + ``target_column``).
    - **Target:** If the frame has no ``target_column`` but has ``Adj Close`` / ``Close`` (e.g. yfinance),
      a **forward 1-period return** is created automatically under ``target_column`` (default ``target``).
    - **Features:** ``feature_columns`` as list or comma-separated string; if omitted, all numeric
      columns except ``target_column`` are used.
    - **Model:** ``model_name`` one of:
      ``linear_regression`` / ``ridge`` / ``lasso`` / ``elasticnet`` /
      ``random_forest`` / ``gradient_boosting`` / ``svr`` (plus aliases ``lr``, ``rf``, ``gbm``, …).
    - **Spec tracking:** ``requested_model_name`` is optional free-form text (e.g. `RandomForestRegressor` or
      `Random Forest`). When provided, the tool outputs `spec_deviated` and `spec_deviation_reason`.
    - **Tuning:** ``tune_hyperparameters=True`` runs ``RandomizedSearchCV`` when a search space exists;
      ``linear_regression`` cannot tune (OLS); request is ignored with ``tune_ignored=True``.

    Returns JSON-friendly metrics and ``best_params`` when applicable.
    """
    if data_path is None and workspace is not None:
        if workspace.has("engineered_data"):
            data_path = str(workspace.df_path("engineered_data"))
            if workspace.has("feature_plan") and target_column == "target":
                fp = workspace.load_json("feature_plan")
                fp_target = str(fp.get("target_column", "")).strip()
                if fp_target and _VALID_COL_RE.match(fp_target) and len(fp_target) <= 60:
                    target_column = fp_target
        elif workspace.has("raw_data"):
            data_path = str(workspace.df_path("raw_data"))

    key = _normalize_model_name(model_name)
    factories = _estimator_factories()
    if key not in factories:
        raise KeyError(f"Unknown model_name={model_name!r}; allowed: {sorted(factories)}")

    fc = _parse_feature_columns(feature_columns)
    df = _load_frame(data_path, n_samples=n_samples, n_features=n_features, target_column=target_column, rs=random_state)
    df, derived_from = _maybe_add_forward_return_target(df, target_column)
    if target_column not in df.columns:
        raise KeyError(
            f"target_column {target_column!r} not in data columns: {list(df.columns)}. "
            "Add a target (e.g. run feature engineering / run_data_analyst) or use OHLCV with Adj Close/Close."
        )

    feats = _resolve_features(df, target_column, fc)
    # Guard against feature engineering producing inf/-inf (division by zero, overflow, etc).
    # scikit-learn estimators (e.g. RandomForest) do not accept inf values.
    mask = df[target_column].notna()
    df = df.loc[mask]
    X = df[feats].copy()
    y = df[target_column].copy()

    # Replace non-finite values so downstream imputer can handle NaNs.
    X = X.replace([np.inf, -np.inf], np.nan)
    y = y.replace([np.inf, -np.inf], np.nan)

    def _count_non_finite(frame: pd.DataFrame | pd.Series) -> int:
        try:
            arr = frame.to_numpy(dtype=np.float64, copy=False)
        except Exception:  # noqa: BLE001
            # Fallback: coerce to numeric; non-numeric becomes NaN.
            arr = pd.DataFrame(frame).apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64, copy=False)
        return int((~np.isfinite(arr)).sum())

    non_finite_counts = {
        "X_non_finite_total": _count_non_finite(X),
        "y_non_finite_total": _count_non_finite(y),
    }

    # Keep only rows where target is finite; features may still contain NaNs (imputed later).
    try:
        y_arr = y.to_numpy(dtype=np.float64, copy=False)
    except Exception:  # noqa: BLE001
        y_arr = pd.to_numeric(y, errors="coerce").to_numpy(dtype=np.float64, copy=False)
    finite_y_mask = y.notna() & pd.Series(np.isfinite(y_arr), index=y.index)
    X = X.loc[finite_y_mask]
    y = y.loc[finite_y_mask]

    if len(X) == 0:
        raise ValueError(
            "No finite training rows remain after cleaning X/y non-finite values. "
            f"Counts before filtering: {non_finite_counts}."
        )

    idx = df.index
    time_ordered = isinstance(idx, pd.DatetimeIndex) and (
        idx.is_monotonic_increasing or idx.is_monotonic_decreasing
    )
    if time_ordered and len(df) >= 5:
        split_idx = max(1, int(len(df) * (1 - test_size)))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state
        )

    base = factories[key](random_state)
    pipe = _build_pipeline(base)

    tune_ignored = False
    param_dist = _param_distributions().get(key)

    if tune_hyperparameters and param_dist is None:
        tune_ignored = True
        tune_hyperparameters = False

    if tune_hyperparameters and param_dist is not None:
        search = RandomizedSearchCV(
            pipe,
            param_distributions=param_dist,
            n_iter=max(4, tuning_iter),
            cv=max(2, cv_folds),
            random_state=random_state,
            n_jobs=-1,
            scoring="r2",
        )
        search.fit(X_train, y_train)
        fitted = search.best_estimator_
        best_params = _jsonify_params(dict(search.best_params_))
        best_cv_r2 = float(search.best_score_)
    else:
        fitted = pipe
        fitted.fit(X_train, y_train)
        best_params = {}
        best_cv_r2 = None

    pred_tr = fitted.predict(X_train)
    pred_te = fitted.predict(X_test)
    train_r2 = float(r2_score(y_train, pred_tr))
    test_r2 = float(r2_score(y_test, pred_te))
    test_rmse = float(np.sqrt(mean_squared_error(y_test, pred_te)))

    result = {
        "model": key,
        "executed_model_display": _model_display_name(key),
        "executed_model_key": key,
        "requested_model_name": requested_model_name,
        "target_derived_from_price": derived_from,
        "target_prediction_horizon": _infer_target_horizon(target_column, derived_from),
        "time_ordered_split": bool(time_ordered and len(df) >= 5),
        "tune_hyperparameters": bool(tune_hyperparameters),
        "tune_ignored": tune_ignored,
        "tune_note": "OLS has no hyperparameters; used fixed LinearRegression."
        if tune_ignored and key in ("linear_regression", "lr", "ols")
        else None,
        "feature_columns": feats,
        "target_column": target_column,
        "train_r2": train_r2,
        "test_r2": test_r2,
        "test_rmse": test_rmse,
        "best_cv_r2": best_cv_r2,
        "best_params": best_params,
        "data_path": data_path,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "non_finite_counts_after_cleanup": non_finite_counts,
        "spec_deviated": False,
        "spec_deviation_reason": None,
    }

    if requested_model_name is not None:
        requested_key = _canonical_model_key_for_spec(requested_model_name)
        result["requested_model_key"] = requested_key
        if requested_key is not None and requested_key != key:
            result["spec_deviated"] = True
            result["spec_deviation_reason"] = (
                f"Requested model family {_model_display_name(requested_key)} "
                f"but executed {_model_display_name(key)}."
            )
            if workspace is not None:
                workspace.save_json(
                    "spec_deviation_warning",
                    {
                        "tool": "train_model",
                        "requested_model_name": requested_model_name,
                        "requested_model_key": requested_key,
                        "executed_model_key": key,
                        "spec_deviated": True,
                        "reason": result["spec_deviation_reason"],
                    },
                    description="Spec-deviation warning: requested vs executed model mismatch.",
                )
        else:
            result["spec_deviated"] = False
            result["spec_deviation_reason"] = None
            # Optional: keep a trace artifact when the request was explicit and matched.
            if workspace is not None and requested_key is not None:
                workspace.save_json(
                    "spec_requested_executed_model",
                    {
                        "tool": "train_model",
                        "requested_model_name": requested_model_name,
                        "requested_model_key": requested_key,
                        "executed_model_key": key,
                        "spec_deviated": False,
                        "reason": None,
                    },
                    description="Requested vs executed model (explicit match record).",
                )

    if workspace is not None:
        workspace.save_json(
            "model_output",
            result,
            description=f"Training results for {key} model",
        )
        result["workspace_artifact"] = "model_output"

    return result
