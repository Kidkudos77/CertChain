"""
TF-IDF + Logistic Regression floor on Stage 3 residual.
Measures whether a simple text baseline can find signal in the residual
that deterministic stages couldn't resolve.

Uses leave-one-course-out (GroupKFold with group = institution+code).
"""
import pandas as pd
import numpy as np
import json
import sys
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, precision_recall_fscore_support, accuracy_score
from sklearn.model_selection import LeaveOneGroupOut, GroupKFold
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cascade import Cascade

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Load labels
df = pd.read_csv(PROJECT_DIR / "data" / "labels" / "test_set_pass1.csv")

# Load config and run cascade to identify Stage 3 residual
with open(PROJECT_DIR / "src" / "config.yaml") as f:
    config = yaml.safe_load(f)

cascade = Cascade(config)

# Tag each pair with its cascade stage
stages = []
for _, row in df.iterrows():
    course = {
        "sending_institution": row["sending_institution"],
        "sending_course_code": row["sending_course_code"],
        "sending_course_name": row["sending_course_name"],
        "sending_credits": str(row["sending_credits"]),
    }
    result = cascade.resolve(course, row["requirement_id"])
    stages.append(result.stage)

df["cascade_stage"] = stages

# Filter to Stage 3 residual only
residual = df[df["cascade_stage"] == 3].copy()
print(f"Stage 3 residual: {len(residual)} pairs, {int(residual['label'].sum())} positives ({residual['label'].mean()*100:.1f}%)")
print()

# Build text features (same as certchain-eligibility design: course name + credits + requirement)
# The model sees: sending_course_name | sending_credits | requirement_name
req_names = {
    "R1": "Digital Forensics",
    "R2": "Introduction to Computer Security",
    "R3": "Applied Security",
    "R4": "Network Security",
    "R5": "Database Management Systems",
    "prerequisite": "Fundamentals of Programming",
}

residual["text"] = (
    residual["sending_course_name"].fillna("") + " | " +
    residual["sending_credits"].astype(str) + " credits | " +
    residual["requirement_id"].map(req_names).fillna("")
)

# Group key for leave-one-course-out
residual["group"] = residual["sending_institution"] + "|||" + residual["sending_course_code"]

texts = residual["text"].tolist()
labels = residual["label"].tolist()
groups = residual["group"].tolist()

# GroupKFold (3 folds, same as config)
n_folds = 3
gkf = GroupKFold(n_splits=n_folds)

all_preds = []
all_true = []

for fold, (train_idx, test_idx) in enumerate(gkf.split(texts, labels, groups)):
    train_texts = [texts[i] for i in train_idx]
    test_texts = [texts[i] for i in test_idx]
    train_labels = [labels[i] for i in train_idx]
    test_labels = [labels[i] for i in test_idx]

    tfidf = TfidfVectorizer(max_features=3000, ngram_range=(1, 2), sublinear_tf=True)
    X_train = tfidf.fit_transform(train_texts)
    X_test = tfidf.transform(test_texts)

    lr = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced", random_state=42)
    lr.fit(X_train, train_labels)
    preds = lr.predict(X_test)

    all_preds.extend(preds)
    all_true.extend(test_labels)

# Results
print("=" * 60)
print("TF-IDF + LOGISTIC REGRESSION FLOOR (Stage 3 residual)")
print("Split: GroupKFold(n=3) on (institution, course_code)")
print("=" * 60)
print()

acc = accuracy_score(all_true, all_preds)
p, r, f1, sup = precision_recall_fscore_support(all_true, all_preds, average="binary")
print(f"Accuracy:  {acc:.4f}")
print(f"Precision: {p:.4f}")
print(f"Recall:    {r:.4f}")
print(f"F1:        {f1:.4f}")
print()
print(classification_report(all_true, all_preds, target_names=["negative", "positive"]))

# Also report: what does "always predict 0" get?
majority_acc = 1 - np.mean(all_true)
print(f"Majority baseline (always 0): accuracy={majority_acc:.4f}")
print(f"TF-IDF lift over majority: +{(acc - majority_acc)*100:.1f} percentage points")

# Save
output = {
    "tfidf_floor_stage3": {
        "n_pairs": len(residual),
        "n_positives": int(residual["label"].sum()),
        "positive_rate": float(residual["label"].mean()),
        "accuracy": float(acc),
        "precision": float(p),
        "recall": float(r),
        "f1": float(f1),
        "majority_baseline_accuracy": float(majority_acc),
        "lift_over_majority_pct": float((acc - majority_acc) * 100),
        "method": "TF-IDF(3000 features, 1-2 ngrams) + LogisticRegression(balanced), GroupKFold(3)",
    }
}
results_dir = PROJECT_DIR / "results"
with open(results_dir / "tfidf_floor.json", "w") as f:
    json.dump(output, f, indent=2)
print(f"\nSaved to {results_dir / 'tfidf_floor.json'}")
