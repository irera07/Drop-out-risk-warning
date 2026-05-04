# model/predictor.py
# Drop-in prediction module for Flask.
# Import and call predict_dataframe(df) from your route.

import re
import json
import os
import numpy  as np
import pandas as pd
import joblib

# ── Paths ─────────────────────────────────────────────────────
_BASE      = os.path.dirname(__file__)
MODEL_PATH = os.path.join(_BASE, "dropout_model.joblib")
META_PATH  = os.path.join(_BASE, "model_metadata.json")

# ── Load once at import time ──────────────────────────────────
_pipeline = joblib.load(MODEL_PATH)

with open(META_PATH) as f:
    _meta = json.load(f)

FEATURE_COLS = _meta["feature_cols"]
CAT_COLS     = _meta["cat_cols"]
NUM_COLS     = _meta["num_cols"]

print(f"[ML] Loaded {_meta['model_name']}  "
      f"(AUC={_meta['roc_auc']}, Acc={_meta['accuracy']})")


# ── Column name normaliser (mirrors train.py) ─────────────────

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip spaces and collapse underscores in column names."""
    df = df.copy()
    df.columns = [re.sub(r'[_\s]+', '_', c.strip()) for c in df.columns]
    return df


# ── Human-readable reason engine ─────────────────────────────

# Priority order for explaining dropout risk
_RISK_FACTORS = [
    ("Job_opportunity",          "Has a job opportunity pulling them away from school"),
    ("Pregnancy",                "Pregnancy is a significant dropout risk factor"),
    ("Family_conflicts",         "Family conflicts are affecting school attendance"),
    ("Drug_abuse",               "Drug abuse is impacting school engagement"),
    ("Absenteism",               "High absenteeism recorded"),
    ("Lack_of_School_Fees",      "Unable to pay school fees"),
    ("Lack_of_School_Material",  "Lacks necessary school materials"),
    ("Bad_Discipline",           "Discipline issues noted"),
    ("Lack_of_motivation",       "Low motivation to continue schooling"),
    ("Illness",                  "Health/illness issues affecting attendance"),
]

_PROTECT_FACTORS = [
    ("Job_opportunity",          "No job opportunity distracting from school"),
    ("Pregnancy",                "No pregnancy-related risk"),
    ("Family_conflicts",         "Stable family environment"),
    ("Drug_abuse",               "No drug abuse reported"),
    ("Absenteism",               "Good attendance record"),
    ("Lack_of_School_Fees",      "School fees are covered"),
    ("Lack_of_School_Material",  "Has adequate school materials"),
    ("Bad_Discipline",           "Good disciplinary record"),
    ("Lack_of_motivation",       "Shows motivation to continue"),
    ("Illness",                  "No significant illness reported"),
]


def _build_reason(row: pd.Series, dropout_predicted: bool, prob: float) -> str:
    """
    Generate a plain-English reason from the student's feature values.
    Uses the top triggered risk/protective factors.
    """
    active_risks     = [msg for col, msg in _RISK_FACTORS     if row.get(col, 0) == 1]
    active_protects  = [msg for col, msg in _PROTECT_FACTORS  if row.get(col, 0) == 0
                        and col in [c for c, _ in _RISK_FACTORS]]

    if dropout_predicted:
        if active_risks:
            reasons = "; ".join(active_risks[:3])
            return f"Dropout risk driven by: {reasons}."
        return f"Multiple combined risk factors (probability {prob*100:.0f}%)."
    else:
        if active_protects:
            reasons = "; ".join(active_protects[:3])
            return f"Low dropout risk. Protective factors: {reasons}."
        return f"No major dropout risk factors detected (probability {prob*100:.0f}%)."


def _risk_level(prob: float, dropout_predicted: bool) -> str:
    if not dropout_predicted:
        return "none"
    if prob >= 0.70: return "high"
    if prob >= 0.40: return "medium"
    return "low"


# ══════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════

def predict_dataframe(df: pd.DataFrame) -> tuple[list[dict], dict]:
    """
    Run dropout prediction on a DataFrame of students.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain the 15 feature columns (column names may have
        spaces — they will be normalised automatically).
        May also contain 'name', 'gender', 'class_level' for display.

    Returns
    -------
    results : list[dict]
        One dict per student with prediction fields.
    summary : dict
        Aggregate counts for the KPI dashboard.
    """
    df = _normalise_columns(df)

    # Validate required columns exist
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    X = df[FEATURE_COLS]

    probs   = _pipeline.predict_proba(X)[:, 1]
    preds   = _pipeline.predict(X)

    results = []
    for i, (_, row) in enumerate(df.iterrows()):
        prob    = float(probs[i])
        dropout = bool(preds[i])
        results.append({
            "names":                row.get("names", row.get("Names", row.get("name", f"Student {i+1}"))),
            "gender":              row.get("gender",       row.get("Child_Gender", "unknown")),
            "class_level":         row.get("class_level",  row.get("Year_of_Study", "")),
            "dropout_predicted":   dropout,
            "dropout_probability": round(prob, 4),
            "risk_level":          _risk_level(prob, dropout),
            "reason":              _build_reason(row, dropout, prob),
        })

    total = len(results)
    summary = {
        "total_students": total,
        "dropout_count":  sum(1 for r in results if r["dropout_predicted"]),
        "non_dropout":    sum(1 for r in results if not r["dropout_predicted"]),
        "high_risk":      sum(1 for r in results if r["risk_level"] == "high"),
        "medium_risk":    sum(1 for r in results if r["risk_level"] == "medium"),
        "low_risk":       sum(1 for r in results if r["risk_level"] == "low"),
        "male_count":     sum(1 for r in results
                              if str(r["gender"]).strip().lower() == "male"),
        "female_count":   sum(1 for r in results
                              if str(r["gender"]).strip().lower() == "female"),
    }

    return results, summary
