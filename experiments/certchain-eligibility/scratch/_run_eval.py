"""Quick stats + cascade run on labeled data."""
import pandas as pd
import numpy as np
import json
import time
import re
from pathlib import Path
import yaml
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cascade import Cascade

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Load labels
df = pd.read_csv(PROJECT_DIR / "data" / "labels" / "test_set_pass1.csv")
print(f"Total pairs: {len(df)}")
print(f"Unique courses: {df.groupby(['sending_institution','sending_course_code']).ngroups}")
print(f"Positives: {int(df['label'].sum())} ({df['label'].mean()*100:.1f}%)")
print()
print("Per requirement:")
print(df.groupby('requirement_id')['label'].agg(['sum','count','mean']).to_string())
print()

# Load config and run cascade
with open(PROJECT_DIR / "src" / "config.yaml") as f:
    config = yaml.safe_load(f)

cascade = Cascade(config)

# Run cascade on all labeled pairs
results = []
for _, row in df.iterrows():
    course = {
        "sending_institution": row["sending_institution"],
        "sending_course_code": row["sending_course_code"],
        "sending_course_name": row["sending_course_name"],
        "sending_credits": str(row["sending_credits"]),
    }
    result = cascade.resolve(course, row["requirement_id"])
    results.append({
        "stage": result.stage,
        "tier": result.tier,
        "confidence": result.confidence,
        "latency_ms": result.latency_ms,
        "label": row["label"],
        "requirement_id": row["requirement_id"],
    })

results_df = pd.DataFrame(results)

# Cascade resolution rates
print("=" * 60)
print("CASCADE RESOLUTION RATES")
print("=" * 60)
for stage in [0, 1, 2, 3]:
    subset = results_df[results_df["stage"] == stage]
    n = len(subset)
    rate = n / len(results_df) * 100
    positives = subset["label"].sum()
    print(f"  Stage {stage}: {n} pairs ({rate:.1f}%), {int(positives)} positives")
print()

# Per-stage latency
print("PER-STAGE LATENCY:")
for stage in [0, 1, 2, 3]:
    lats = results_df[results_df["stage"] == stage]["latency_ms"]
    if len(lats) > 0:
        print(f"  Stage {stage}: mean={lats.mean():.3f}ms, std={lats.std():.3f}ms")
print()

# Stage 2 matches (the interesting ones)
stage2 = results_df[results_df["stage"] == 2]
if len(stage2) > 0:
    print("STAGE 2 MATCHES (normalized title):")
    stage2_with_info = df.iloc[stage2.index]
    for _, row in stage2_with_info.iterrows():
        print(f"  {row['sending_institution']}/{row['sending_course_code']}: "
              f"{row['sending_course_name']} -> {row['requirement_id']} "
              f"(label={row['label']})")
print()

# Stage 3 residual analysis
stage3 = results_df[results_df["stage"] == 3]
print("=" * 60)
print("STAGE 3 RESIDUAL (BERT would serve this population)")
print("=" * 60)
print(f"  Total Stage 3 pairs: {len(stage3)}")
print(f"  Positives in Stage 3: {int(stage3['label'].sum())} ({stage3['label'].mean()*100:.1f}%)")
print()
print("  Per requirement in Stage 3:")
for req in sorted(stage3["requirement_id"].unique()):
    sub = stage3[stage3["requirement_id"] == req]
    print(f"    {req}: {len(sub)} pairs, {int(sub['label'].sum())} positives ({sub['label'].mean()*100:.1f}%)")

# Tier distribution
print()
print("=" * 60)
print("TIER DISTRIBUTION")
print("=" * 60)
tier_counts = results_df["tier"].value_counts()
for tier, count in tier_counts.items():
    print(f"  Tier {tier}: {count} ({count/len(results_df)*100:.1f}%)")

# Save results
output = {
    "dataset": {
        "total_pairs": len(df),
        "unique_courses": int(df.groupby(['sending_institution','sending_course_code']).ngroups),
        "positive_rate": float(df['label'].mean()),
        "positives": int(df['label'].sum()),
    },
    "cascade": cascade.get_stats(),
    "stage3_residual": {
        "total": len(stage3),
        "positives": int(stage3['label'].sum()),
        "positive_rate": float(stage3['label'].mean()) if len(stage3) > 0 else 0,
    },
    "note": "Partial labeling (subset of full 156-course pool). Intra-rater reliability pending.",
}

results_dir = PROJECT_DIR / "results"
results_dir.mkdir(exist_ok=True)
with open(results_dir / "cascade_stats.json", "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nSaved to {results_dir / 'cascade_stats.json'}")
