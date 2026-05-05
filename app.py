# app.py  —  Flask application factory
# Usage:
#   pip install flask flask-sqlalchemy flask-login werkzeug pymysql
#   python app.py

import os
import joblib
import pandas as pd
import numpy as np

from flask import Flask, redirect, url_for
from sqlalchemy import inspect, text
from models import db


# ─────────────────────────────────────────────
# ML MODEL — load once at startup
# Replace the path below with your actual .pkl / .joblib file
# ─────────────────────────────────────────────
MODEL_PATH = os.environ.get("MODEL_PATH", "model/best_dropout_model.pkl")

dropout_model = None  # populated in create_app()


def load_model(MODEL_PATH):
    """Load the trained sklearn model. Returns None if file not found."""
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            print(f"[ML] Model loaded from {MODEL_PATH}")
            return model
        except Exception as e:
            print(f"[ML] ERROR: failed to load model from {MODEL_PATH}: {e}")
            return None
    else:
        print(f"[ML] WARNING: model file not found at {MODEL_PATH}. "
              "Place your .pkl/.joblib file there before running predictions.")
        return None


def get_dropout_model():
    """Return the loaded ML model, trying to load it once if missing."""
    global dropout_model
    if dropout_model is None:
        dropout_model = load_model(MODEL_PATH)
    return dropout_model


# ─────────────────────────────────────────────
# APP FACTORY
# ─────────────────────────────────────────────

def ensure_schema(app):
    """Add missing columns for existing databases so the app can run after model changes."""
    with app.app_context():
        inspector = inspect(db.engine)

        if "teachers" in inspector.get_table_names():
            teacher_cols = {col["name"] for col in inspector.get_columns("teachers")}
            if "account_status" not in teacher_cols:
                with db.engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE teachers "
                        "ADD COLUMN account_status ENUM('pending','active','disabled') NOT NULL DEFAULT 'pending'"
                    ))
                    conn.commit()

        if "local_leaders" in inspector.get_table_names():
            leader_cols = {col["name"] for col in inspector.get_columns("local_leaders")}
            with db.engine.connect() as conn:
                if "requested_school_name" not in leader_cols:
                    conn.execute(text(
                        "ALTER TABLE local_leaders ADD COLUMN requested_school_name VARCHAR(250) NULL"
                    ))
                if "approved_school_names" not in leader_cols:
                    conn.execute(text(
                        "ALTER TABLE local_leaders ADD COLUMN approved_school_names VARCHAR(250) NULL"
                    ))
                if "requested_class_name" not in leader_cols:
                    conn.execute(text(
                        "ALTER TABLE local_leaders ADD COLUMN requested_class_name VARCHAR(50) NULL"
                    ))
                if "access_status" not in leader_cols:
                    conn.execute(text(
                        "ALTER TABLE local_leaders "
                        "ADD COLUMN access_status ENUM('pending','approved','denied') NOT NULL DEFAULT 'pending'"
                    ))
                conn.commit()


def create_app():
    app = Flask(__name__)

    # ── Database config (MySQL via PyMySQL) ──────────────────
    # Set DB_URL in environment or edit directly below
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DB_URL",
        "mysql+pymysql://root:Twizeyeyesu%4007@localhost/dropout_db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")

    # ── Upload config ─────────────────────────────────────────
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload

    # ── Init extensions ───────────────────────────────────────
    db.init_app(app)

    # ── Load ML model ─────────────────────────────────────────
    global dropout_model
    with app.app_context():
        dropout_model = load_model(MODEL_PATH)
        db.create_all()   # creates tables if they don't exist yet
        ensure_schema(app)
        print("[DB] Tables ready.")

    # ── Register blueprints (add as you build each feature) ───
    from auth import auth_bp
    from teacher import teacher_bp
    from principal import principal_bp
    from leader import leader_bp
    # from routes.predict import predict_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(teacher_bp, url_prefix="/teacher")
    app.register_blueprint(principal_bp, url_prefix="/principal")
    app.register_blueprint(leader_bp, url_prefix="/leader")
    # app.register_blueprint(predict_bp,  url_prefix="/predict")

    @app.route("/")
    def index():
        return redirect(url_for("auth.login"))

    return app


# ─────────────────────────────────────────────
# PREDICTION HELPER
# Call this from your predict route after building
# the general file (70% weighted average of versions).
# ─────────────────────────────────────────────

def run_prediction(df, default_class_level=""):
    """
    df: a pandas DataFrame with one row per student,
        columns matching what your model was trained on.
    default_class_level: fallback class value to use when class_level is missing.

    Returns a list of dicts with per-student results,
    plus summary counters ready to store in the DB.
    """
    import re

    def normalize_name(col):
        c = str(col).strip()
        # normalize spaces around underscores, then collapse spaces to underscore
        c = re.sub(r"\s*_\s*", "_", c)
        c = re.sub(r"\s+", "_", c)
        c = re.sub(r"_+", "_", c).strip("_")
        return c

    model = get_dropout_model()
    if model is None:
        raise RuntimeError("ML model is not loaded. Check MODEL_PATH.")

    # Normalize input column names
    df = df.rename(columns={c: normalize_name(c) for c in df.columns})

    # Ensure gender and class_level exist in df (from input or create default)
    if "gender" not in df.columns:
        # Try to find gender column by normalized name variations
        gender_col = next((c for c in df.columns if normalize_name(c) == "gender"), None)
        if gender_col:
            df = df.rename(columns={gender_col: "gender"})
        else:
            df["gender"] = "unknown"

    if "class_level" not in df.columns:
        # Try to find class_level column by normalized name variations
        class_col = next((c for c in df.columns if "class" in normalize_name(c).lower()), None)
        if class_col:
            df = df.rename(columns={class_col: "class_level"})
        else:
            df["class_level"] = default_class_level or ""

    # Remove sidecar columns that are not model features
    extra_wrap = [c for c in ["name", "gender", "class_level"] if c in df.columns]
    X = df.drop(columns=extra_wrap)

    # Ensure model feature ordering and exact names when available
    if hasattr(model, "feature_names_in_"):
        expected_raw = list(model.feature_names_in_)
        expected_norm = [normalize_name(c) for c in expected_raw]

        # Map normalized input names to actual available columns
        input_norm_to_col = {normalize_name(c): c for c in X.columns}

        missing = [raw for raw, norm in zip(expected_raw, expected_norm) if norm not in input_norm_to_col]
        if missing:
            raise RuntimeError(
                "Feature names mismatch. Missing expected columns: " + ", ".join(missing)
            )

        # Rebuild matrix with model-expected names (including original spaces style)
        X = X[[input_norm_to_col[norm] for norm in expected_norm]]
        X.columns = expected_raw

        extra = [c for c in X.columns if normalize_name(c) not in expected_norm]
        if extra:
            raise RuntimeError(
                "Unexpected input columns after mapping: " + ", ".join(extra)
            )

    # Get top influencing features
    top_factors = []
    if hasattr(model, 'feature_importances_'):
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1][:2]  # top 2
        top_factors = [expected_raw[i] for i in indices]
    else:
        top_factors = ["Feature analysis not available"]

    # Convert model inputs to numeric where possible
    X = X.apply(lambda s: pd.to_numeric(s, errors="coerce"))

    if X.isna().any().any():
        # Fill unknown numeric values with 0; adjust if a better strategy is needed.
        X = X.fillna(0)

    predictions   = model.predict(X)
    probabilities = model.predict_proba(X)
    dropout_probs = probabilities[:, 1]

    # ── 2. Assign risk level ──────────────────────────────────
    def risk_level(prob):
        if prob >= 0.70:  return "high"
        if prob >= 0.40:  return "medium"
        return "low"

    # ── 3. Build per-student result rows ─────────────────────
    results = []
    for i, row in df.iterrows():
        prob = float(dropout_probs[i])
        results.append({
            "name":              row.get("name", f"Student {i+1}"),
            "gender":            row.get("gender", "unknown"),
            "class_level":       row.get("class_level") or default_class_level or "",
            "dropout_predicted": bool(predictions[i]),
            "dropout_probability": round(prob, 4),
            "risk_level":        risk_level(prob),
            "reason":            f"Top factors: {', '.join(top_factors)}",
        })

    # ── 4. Summary counters ─────────────────────────────────
    summary = {
        "total_students": len(results),
         "dropout_count":  sum(1 for r in results if r["dropout_predicted"]),
        "non_dropout":    sum(1 for r in results if not r["dropout_predicted"]),
        "high_risk":      sum(1 for r in results if r["risk_level"] == "high"),
        "medium_risk":    sum(1 for r in results if r["risk_level"] == "medium"),
        "low_risk":       sum(1 for r in results if r["risk_level"] == "low"),
        "male_count":     sum(1 for r in results if r["gender"].lower() == "male"),
        "female_count":   sum(1 for r in results if r["gender"].lower() == "female"),
    }

    return results, summary


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
