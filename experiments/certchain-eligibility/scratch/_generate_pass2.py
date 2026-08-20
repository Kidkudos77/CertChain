"""Generate Pass 2 retest subsample: 40% of Pass 1 pairs, different shuffle seed."""
import pandas as pd
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Load Pass 1
pass1 = pd.read_csv(PROJECT_DIR / "data" / "labels" / "test_set_pass1.csv")
print(f"Pass 1: {len(pass1)} pairs")

# Sample 40% with seed 99 (different from Pass 1's seed 42)
n_retest = int(len(pass1) * 0.40)
random.seed(99)
indices = random.sample(range(len(pass1)), n_retest)

# Extract subsample and shuffle order
pass2 = pass1.iloc[indices].copy()
pass2 = pass2.sample(frac=1, random_state=99).reset_index(drop=True)

# Remove the label column — you relabel from scratch
pass2["label"] = ""

# Write
output = PROJECT_DIR / "data" / "labels" / "test_set_pass2.csv"
pass2.to_csv(output, index=False)
print(f"Pass 2 subsample: {n_retest} pairs (40% of {len(pass1)})")
print(f"Shuffle seed: 99 (different from Pass 1 seed 42)")
print(f"Written to: {output}")
print()
print("INSTRUCTIONS:")
print("  1. Fill the 'label' column (0/1) WITHOUT looking at test_set_pass1.csv")
print("  2. Do NOT open Pass 1 during this labeling session")
print("  3. Log the date in config.yaml under labeling.pass2_dates")
