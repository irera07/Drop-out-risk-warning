# model/test_pipeline.py
# Generates synthetic student data and tests the full pipeline.
# Run: python model/test_pipeline.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy  as np
import pandas as pd

# ── Import the predictor ──────────────────────────────────────
from model.predictor import predict_dataframe

print("=" * 60)
print("END-TO-END PIPELINE TEST")
print("=" * 60)


# ══════════════════════════════════════════════════════════════
# GENERATE SAMPLE CLASS DATA
# 30 students — realistic mix of risk levels
# ══════════════════════════════════════════════════════════════

np.random.seed(7)
N = 30

def make_students(n):
    ages         = np.random.choice(["13-Jun","14 - 16","17 - 19","20 - 21"], n)
    genders      = np.random.choice(["Male","Female"], n, p=[0.7, 0.3])
    performance  = np.random.choice(["0-40","41-50","51-60","61-70","71-100"], n)
    social       = np.random.choice(["Other","Sport","Dance"], n)
    year         = np.random.choice(["Primary","Lower  Secondary","Upper  Secondary"], n)

    # Binary risk factors (biased toward realistic distribution)
    def binary(p): return np.random.binomial(1, p, n)

    return pd.DataFrame({
        "name":                    [f"Student {i+1}" for i in range(n)],
        "Child_Age":               ages,
        "Child_Gender":            genders,
        "Lack_of_School_Material": binary(0.45),
        "Lack_of_School_Fees":     binary(0.35),
        "Job_opportunity":         binary(0.30),
        "Pregnancy":               binary(0.10),
        "Family_conflicts":        binary(0.40),
        "Drug_abuse":              binary(0.20),
        "Lack_of_motivation":      binary(0.35),
        "Illness":                 binary(0.25),
        "Absenteism":              binary(0.40),
        "Bad_Discipline":          binary(0.30),
        "Performance":             performance,
        "Social_activity":         social,
        "Year_of_Study":           year,
        "gender":                  genders,       # display alias
        "class_level":             year,          # display alias
    })

df_sample = make_students(N)
print(f"\nGenerated {N} sample students")
print(df_sample[["name","Child_Gender","Year_of_Study","Absenteism","Job_opportunity"]].head(8).to_string())


# ══════════════════════════════════════════════════════════════
# RUN PREDICTION
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("Running prediction...")
print("=" * 60)

results, summary = predict_dataframe(df_sample)

print(f"\n{'':=<60}")
print(f"  Total students : {summary['total_students']}")
print(f"  Dropout risk   : {summary['dropout_count']}  ({summary['dropout_count']/summary['total_students']*100:.0f}%)")
print(f"  Not at risk    : {summary['non_dropout']}")
print(f"  High risk      : {summary['high_risk']}")
print(f"  Medium risk    : {summary['medium_risk']}")
print(f"  Low risk       : {summary['low_risk']}")
print(f"  Male / Female  : {summary['male_count']} / {summary['female_count']}")
print(f"{'':=<60}")

print("\nPer-student results:")
print(f"{'#':<4} {'Name':<12} {'Gender':<8} {'Dropout':<10} {'Risk':<8} {'Prob':<7} Reason")
print("-" * 100)
for i, r in enumerate(results, 1):
    dropout_label = "YES ⚠" if r["dropout_predicted"] else "no"
    risk_label    = {"high":"🔴 high","medium":"🟡 medium","low":"🟢 low","none":"⚪ none"}[r["risk_level"]]
    print(f"{i:<4} {r['names']:<12} {r['gender']:<8} {dropout_label:<10} {risk_label:<14} "
          f"{r['dropout_probability']*100:4.0f}%  {r['reason'][:60]}")

print("\n✅ Test passed — predictor.py is ready for Flask integration.")
