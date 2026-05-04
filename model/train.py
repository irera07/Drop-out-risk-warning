# model/train.py
# Full ML pipeline for Student Dropout Prediction
# Usage: python model/train.py
# Output: model/dropout_model.joblib  +  model/preprocessor.joblib

import os
import json
import warnings
import numpy  as np
import pandas as pd
import joblib

from sklearn.model_selection  import train_test_split, StratifiedKFold, cross_val_score
from sklearn.preprocessing    import LabelEncoder, StandardScaler
from sklearn.pipeline         import Pipeline
from sklearn.compose          import ColumnTransformer
from sklearn.preprocessing    import OneHotEncoder
from sklearn.ensemble         import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model     import LogisticRegression
from sklearn.metrics          import (classification_report, confusion_matrix,
                                      roc_auc_score, accuracy_score, f1_score)

warnings.filterwarnings("ignore")
os.makedirs("model", exist_ok=True)


# ══════════════════════════════════════════════════════════════
# 1. LOAD & CLEAN DATA
# ══════════════════════════════════════════════════════════════

print("=" * 60)
print("STEP 1 — Loading and cleaning data")
print("=" * 60)

df = pd.read_csv("/mnt/user-data/uploads/dataset.csv")

# Fix column names — strip outer whitespace, collapse spaces/underscores
import re
df.columns = [re.sub(r'[_\s]+', '_', c.strip()) for c in df.columns]

# Canonical feature names after cleaning
FEATURE_COLS = [
    "Child_Age", "Child_Gender",
    "Lack_of_School_Material", "Lack_of_School_Fees",
    "Job_opportunity", "Pregnancy", "Family_conflicts",
    "Drug_abuse", "Lack_of_motivation", "Illness",
    "Absenteism", "Bad_Discipline",
    "Performance", "Social_activity", "Year_of_Study",
]
TARGET = "Dropped_out"

print(f"Dataset shape: {df.shape}")
print(f"Target distribution:\n{df[TARGET].value_counts()}")
print(f"Class balance: {df[TARGET].mean()*100:.1f}% dropout")

X = df[FEATURE_COLS].copy()
y = df[TARGET].copy()


# ══════════════════════════════════════════════════════════════
# 2. DEFINE FEATURE TYPES
# ══════════════════════════════════════════════════════════════

# Categorical columns → OneHotEncoder
CAT_COLS = ["Child_Age", "Child_Gender", "Performance",
            "Social_activity", "Year_of_Study"]

# Binary / numeric columns → pass through (already 0/1)
NUM_COLS = [c for c in FEATURE_COLS if c not in CAT_COLS]

print(f"\nCategorical features ({len(CAT_COLS)}): {CAT_COLS}")
print(f"Numeric features    ({len(NUM_COLS)}): {NUM_COLS}")


# ══════════════════════════════════════════════════════════════
# 3. BUILD PREPROCESSOR
# ══════════════════════════════════════════════════════════════

preprocessor = ColumnTransformer(transformers=[
    ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CAT_COLS),
    ("num", StandardScaler(), NUM_COLS),
], remainder="drop")


# ══════════════════════════════════════════════════════════════
# 4. TRAIN / TEST SPLIT
# ══════════════════════════════════════════════════════════════

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
print(f"\nTrain size: {len(X_train)} | Test size: {len(X_test)}")


# ══════════════════════════════════════════════════════════════
# 5. COMPARE THREE MODELS  (class_weight handles imbalance)
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("STEP 2 — Comparing models")
print("=" * 60)

candidates = {
    "Random Forest": Pipeline([
        ("pre", preprocessor),
        ("clf", RandomForestClassifier(
            n_estimators=200, max_depth=10,
            class_weight="balanced", random_state=42, n_jobs=-1
        )),
    ]),
    "Gradient Boosting": Pipeline([
        ("pre", preprocessor),
        ("clf", GradientBoostingClassifier(
            n_estimators=200, max_depth=5,
            learning_rate=0.05, random_state=42
        )),
    ]),
    "Logistic Regression": Pipeline([
        ("pre", preprocessor),
        ("clf", LogisticRegression(
            max_iter=1000, class_weight="balanced",
            random_state=42
        )),
    ]),
}

cv      = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
results = {}

for name, pipe in candidates.items():
    scores = cross_val_score(pipe, X_train, y_train,
                             cv=cv, scoring="roc_auc", n_jobs=-1)
    results[name] = scores
    print(f"  {name:<25}  AUC = {scores.mean():.4f} ± {scores.std():.4f}")

best_name = max(results, key=lambda n: results[n].mean())
print(f"\n✓ Best model: {best_name}")


# ══════════════════════════════════════════════════════════════
# 6. TRAIN BEST MODEL ON FULL TRAIN SET
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("STEP 3 — Training best model on full training set")
print("=" * 60)

best_pipe = candidates[best_name]
best_pipe.fit(X_train, y_train)


# ══════════════════════════════════════════════════════════════
# 7. EVALUATE ON HELD-OUT TEST SET
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("STEP 4 — Test set evaluation")
print("=" * 60)

y_pred      = best_pipe.predict(X_test)
y_prob      = best_pipe.predict_proba(X_test)[:, 1]

acc   = accuracy_score(y_test, y_pred)
f1    = f1_score(y_test, y_pred)
auc   = roc_auc_score(y_test, y_prob)
cm    = confusion_matrix(y_test, y_pred)
report = classification_report(y_test, y_pred,
                                target_names=["Not dropout", "Dropout"])

print(f"\nAccuracy : {acc*100:.2f}%")
print(f"F1 Score : {f1:.4f}")
print(f"ROC-AUC  : {auc:.4f}")
print(f"\nConfusion matrix:\n{cm}")
print(f"\nClassification report:\n{report}")


# ══════════════════════════════════════════════════════════════
# 8. FEATURE IMPORTANCE  (for Random Forest / GB)
# ══════════════════════════════════════════════════════════════

print("=" * 60)
print("STEP 5 — Feature importance")
print("=" * 60)

clf = best_pipe.named_steps["clf"]
pre = best_pipe.named_steps["pre"]

# Get feature names from the fitted preprocessor
cat_names = pre.named_transformers_["cat"].get_feature_names_out(CAT_COLS).tolist()
all_feat_names = cat_names + NUM_COLS

if hasattr(clf, "feature_importances_"):
    importances = clf.feature_importances_
    feat_df = (pd.DataFrame({"feature": all_feat_names, "importance": importances})
               .sort_values("importance", ascending=False)
               .head(15))
    print("\nTop 15 features:")
    for _, row in feat_df.iterrows():
        bar = "█" * int(row["importance"] * 200)
        print(f"  {row['feature']:<40} {row['importance']:.4f}  {bar}")

    # Save importance for use in the reason engine
    feat_df.to_csv("model/feature_importance.csv", index=False)
    print("\n✓ Saved: model/feature_importance.csv")
else:
    print("(Logistic Regression — using coefficients instead)")
    coefs = np.abs(clf.coef_[0])
    feat_df = (pd.DataFrame({"feature": all_feat_names, "importance": coefs})
               .sort_values("importance", ascending=False)
               .head(15))
    feat_df.to_csv("model/feature_importance.csv", index=False)


# ══════════════════════════════════════════════════════════════
# 9. SAVE MODEL + METADATA
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("STEP 6 — Saving model")
print("=" * 60)

joblib.dump(best_pipe, "model/dropout_model.joblib")
print("✓ Saved: model/dropout_model.joblib")

# Save metadata so Flask can validate incoming data
metadata = {
    "model_name":    best_name,
    "feature_cols":  FEATURE_COLS,
    "cat_cols":      CAT_COLS,
    "num_cols":      NUM_COLS,
    "target":        TARGET,
    "accuracy":      round(acc, 4),
    "f1_score":      round(f1, 4),
    "roc_auc":       round(auc, 4),
    "train_size":    len(X_train),
    "test_size":     len(X_test),
    "cat_values": {
        col: sorted(X[col].unique().tolist()) for col in CAT_COLS
    },
}
with open("model/model_metadata.json", "w") as f:
    json.dump(metadata, f, indent=2)
print("✓ Saved: model/model_metadata.json")

print("\n" + "=" * 60)
print("✅  Pipeline complete. Model ready for Flask integration.")
print("=" * 60)
