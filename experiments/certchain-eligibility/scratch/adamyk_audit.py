"""
T2 Anchor Audit: Adamyk et al. (2025) DeFi Risk Assessment
Journal of Risk and Financial Management, 18(1), 38.

Two checks:
1. Utility recomputation: U = a*exp(-b*epsilon) + c*exp(-d*R)
2. Partial eta-squared recheck: eta_p^2 = (df_effect * F) / (df_effect * F + df_error)

Values extracted directly from the published paper (Tables 2 and 3).
"""
import json
import numpy as np
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "results" / "adamyk_audit.json"

# ============================================================================
# 1. UTILITY RECOMPUTATION
# ============================================================================
# U(epsilon, R) = a * exp(-b * epsilon) + c * exp(-d * R)
# From Table 3 (page 21):

platforms = [
    {"platform": "Chainalysis", "epsilon": 0.05, "R": 3, "a": 0.7, "b": None, "c": 0.3, "d": 1.0, "reported_U": 0.648},
    {"platform": "Elliptic",    "epsilon": 0.08, "R": 2, "a": 0.6, "b": 2.0,  "c": 0.4, "d": 1.2, "reported_U": 0.547},
    {"platform": "Nansen",      "epsilon": 0.01, "R": 1, "a": 0.5, "b": 1.5,  "c": 0.5, "d": 1.5, "reported_U": 0.542},
    {"platform": "Dune Analytics", "epsilon": 0.12, "R": 4, "a": 0.8, "b": 1.8, "c": 0.2, "d": 1.1, "reported_U": 0.647},
    {"platform": "DeBank",      "epsilon": 0.15, "R": 2, "a": 0.4, "b": 1.2,  "c": 0.6, "d": 1.4, "reported_U": 0.371},
    {"platform": "Etherscan",   "epsilon": 0.07, "R": 3, "a": 0.6, "b": 1.7,  "c": 0.4, "d": 1.3, "reported_U": 0.541},
]

print("=" * 70)
print("ADAMYK et al. (2025) AUDIT — UTILITY RECOMPUTATION")
print("U(epsilon, R) = a * exp(-b * epsilon) + c * exp(-d * R)")
print("=" * 70)
print()

utility_results = []
for p in platforms:
    if p["b"] is None:
        print(f"  {p['platform']}: MISSING PARAMETER b in Table 3.")
        print(f"    Cannot compute utility. This is a reporting defect in the paper.")
        print(f"    Reported U = {p['reported_U']}")
        utility_results.append({
            "platform": p["platform"],
            "computed_U": None,
            "reported_U": p["reported_U"],
            "discrepancy": None,
            "match": None,
            "finding": "Parameter b not reported in Table 3. Utility cannot be verified.",
        })
        print()
        continue

    computed_U = p["a"] * np.exp(-p["b"] * p["epsilon"]) + p["c"] * np.exp(-p["d"] * p["R"])
    diff = abs(computed_U - p["reported_U"])
    match = diff < 0.005

    print(f"  {p['platform']}:")
    print(f"    Parameters: a={p['a']}, b={p['b']}, c={p['c']}, d={p['d']}, eps={p['epsilon']}, R={p['R']}")
    print(f"    Computed U = {computed_U:.6f}")
    print(f"    Reported U = {p['reported_U']}")
    print(f"    Difference = {diff:.6f} -> {'MATCH' if match else 'DISCREPANCY'}")
    print()

    utility_results.append({
        "platform": p["platform"],
        "computed_U": round(float(computed_U), 6),
        "reported_U": p["reported_U"],
        "discrepancy": round(float(diff), 6),
        "match": bool(match),
    })

# ============================================================================
# 2. PARTIAL ETA-SQUARED RECHECK
# ============================================================================
# eta_p^2 = (df_effect * F) / (df_effect * F + df_error)
# From Table 2 (page 19): N=138, 6 platforms, df_between=5, df_within=132

print("=" * 70)
print("ADAMYK et al. (2025) AUDIT — PARTIAL ETA-SQUARED RECHECK")
print("eta_p^2 = (df_effect * F) / (df_effect * F + df_error)")
print("=" * 70)
print()

anova_rows = [
    {"criterion": "Data Accuracy",          "F": 12.43, "df_effect": 5, "df_error": 132, "reported_eta_p2": 0.29},
    {"criterion": "Real-Time Monitoring",   "F": 10.11, "df_effect": 5, "df_error": 132, "reported_eta_p2": 0.22},
    {"criterion": "Advanced Analytics",     "F": 11.22, "df_effect": 5, "df_error": 132, "reported_eta_p2": 0.23},
    {"criterion": "Compliance Features",    "F": 14.01, "df_effect": 5, "df_error": 132, "reported_eta_p2": 0.31},
    {"criterion": "Usability",              "F": 8.71,  "df_effect": 5, "df_error": 132, "reported_eta_p2": 0.17},
    {"criterion": "Overall Effectiveness",  "F": 11.78, "df_effect": 5, "df_error": 132, "reported_eta_p2": 0.27},
]

eta_results = []
discrepancies = []

for row in anova_rows:
    computed_eta = (row["df_effect"] * row["F"]) / (row["df_effect"] * row["F"] + row["df_error"])
    # Alternative: omega squared = df_effect*(F-1) / (df_effect*(F-1) + N)
    N = 138
    computed_omega = (row["df_effect"] * (row["F"] - 1)) / (row["df_effect"] * (row["F"] - 1) + N)
    reported = row["reported_eta_p2"]

    diff_eta = abs(computed_eta - reported)
    diff_omega = abs(computed_omega - reported)
    match_eta = diff_eta < 0.01
    match_omega = diff_omega < 0.015

    status_eta = "MATCH" if match_eta else "DISCREPANCY"
    if not match_eta:
        discrepancies.append(row["criterion"])

    print(f"  {row['criterion']}:")
    print(f"    F={row['F']}, df_effect={row['df_effect']}, df_error={row['df_error']}")
    print(f"    Computed partial eta^2 = {computed_eta:.4f}")
    print(f"    Computed omega^2       = {computed_omega:.4f}")
    print(f"    Reported               = {reported}")
    print(f"    Diff (eta^2)  = {diff_eta:.4f} -> {status_eta}")
    print(f"    Diff (omega^2)= {diff_omega:.4f} -> {'CLOSER' if diff_omega < diff_eta else 'NOT CLOSER'}")
    print()

    eta_results.append({
        "criterion": row["criterion"],
        "F": row["F"],
        "computed_partial_eta_p2": round(float(computed_eta), 4),
        "computed_omega_squared": round(float(computed_omega), 4),
        "reported": reported,
        "diff_eta_p2": round(float(diff_eta), 4),
        "diff_omega_sq": round(float(diff_omega), 4),
        "match_eta_p2": bool(match_eta),
        "omega_closer": bool(diff_omega < diff_eta),
    })

print("=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"  Utility: Chainalysis missing parameter b (cannot verify)")
n_utility_checked = sum(1 for r in utility_results if r["computed_U"] is not None)
n_utility_match = sum(1 for r in utility_results if r.get("match") == True)
print(f"  Utility: {n_utility_match}/{n_utility_checked} platforms match within 0.005")
print(f"  Eta-squared: {len(discrepancies)}/6 rows inconsistent with partial eta^2")
n_omega_closer = sum(1 for r in eta_results if r.get("omega_closer"))
print(f"  Omega-squared closer on {n_omega_closer}/6 rows (but does not reproduce all)")
if discrepancies:
    print(f"  Discrepant criteria: {', '.join(discrepancies)}")
print()
print("  CONCLUSION: Reported values are inconsistent with partial eta^2 as defined")
print("  by the paper's own F statistics and degrees of freedom. They sit systematically")
print("  closer to omega^2, suggesting a mislabeled estimator rather than arbitrary")
print("  numbers, but no single standard estimator reproduces all six rows.")

# ============================================================================
# SAVE
# ============================================================================
result = {
    "adamyk_audit": {
        "paper": "Adamyk et al. (2025). Risk Management in DeFi. JRFM 18(1), 38.",
        "utility_recomputation": {
            "formula": "U = a*exp(-b*epsilon) + c*exp(-d*R)",
            "source": "Table 3, page 21",
            "findings": utility_results,
            "missing_parameter": "Chainalysis b value not reported in Table 3",
        },
        "eta_squared_recheck": {
            "formula_partial_eta": "eta_p^2 = (df_effect * F) / (df_effect * F + df_error)",
            "formula_omega": "omega^2 = df_effect*(F-1) / (df_effect*(F-1) + N)",
            "source": "Table 2, page 19",
            "N": 138,
            "findings": eta_results,
            "n_discrepancies_vs_partial_eta": len(discrepancies),
            "discrepant_criteria": discrepancies,
            "omega_closer_count": n_omega_closer,
            "conclusion": (
                "Reported values are inconsistent with partial eta^2 as defined by the "
                "paper's own F statistics and degrees of freedom. They sit systematically "
                "closer to omega^2, suggesting a mislabeled estimator rather than arbitrary "
                "numbers, but no single standard estimator reproduces all six rows."
            ),
        },
    }
}

OUTPUT.parent.mkdir(exist_ok=True)
with open(OUTPUT, "w") as f:
    json.dump(result, f, indent=2, default=str)
print(f"\nSaved to {OUTPUT}")
