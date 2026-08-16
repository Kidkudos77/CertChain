"""
T2 Anchor Audit: Adamyk et al. DeFi Risk Assessment

Two checks:
1. Utility recomputation: U = a*exp(-b*epsilon) + c*exp(-d*R)
   Using their published parameters, recompute utility for each platform
   and flag any that don't match their reported rankings.

2. Partial eta-squared recheck: eta_p^2 = (df_effect * F) / (df_effect * F + df_error)
   For each reported F-statistic in their Table 2, compute eta_p^2 and compare
   against their reported effect sizes.

Source: Adamyk et al. reported parameters and statistics from the published paper.
"""
import json
import numpy as np
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "results" / "adamyk_audit.json"

# ============================================================================
# 1. UTILITY RECOMPUTATION
# ============================================================================
# U = a * exp(-b * epsilon) + c * exp(-d * R)
# where epsilon = error rate, R = responsiveness
#
# Published parameter values from Adamyk et al. (Table 1 / parameter set)
# These are the values reported in their paper for ranking DeFi platforms.
#
# NOTE: If the paper does not publish exact a, b, c, d values per platform,
# this section documents that gap. Replace with actual values if available.

# Placeholder structure — fill with actual published values from the paper:
# Format: {"platform": name, "epsilon": error_rate, "R": responsiveness,
#          "reported_U": their_reported_utility}
platforms = [
    # Example structure — replace with Adamyk's actual published data:
    # {"platform": "Aave", "epsilon": 0.02, "R": 0.85, "a": 1.0, "b": 2.0, "c": 1.0, "d": 1.5, "reported_U": None},
    # {"platform": "Compound", ...},
    # {"platform": "Nansen", ...},
]

# Parameters for the utility function (from their methods section)
# If they use a single parameter set:
# a, b, c, d = (values from paper)

print("=" * 60)
print("ADAMYK et al. AUDIT — UTILITY RECOMPUTATION")
print("=" * 60)

if not platforms:
    print("\n  STATUS: Parameter values not yet extracted from paper.")
    print("  Need: a, b, c, d coefficients and per-platform epsilon, R values")
    print("  from their Table 1 or methods section.")
    print("  Script structure is ready — fill in values and rerun.")
else:
    for p in platforms:
        computed_U = p["a"] * np.exp(-p["b"] * p["epsilon"]) + p["c"] * np.exp(-p["d"] * p["R"])
        match = abs(computed_U - p["reported_U"]) < 0.01 if p["reported_U"] else "not reported"
        print(f"  {p['platform']}: computed U={computed_U:.4f}, reported={p['reported_U']}, match={match}")

# ============================================================================
# 2. PARTIAL ETA-SQUARED RECHECK
# ============================================================================
# eta_p^2 = (df_effect * F) / (df_effect * F + df_error)
#
# From their ANOVA / Table 2:
# They report F-statistics and effect sizes. We recompute eta_p^2 from F and df
# and check if it matches their reported values.

print("\n" + "=" * 60)
print("ADAMYK et al. AUDIT — PARTIAL ETA-SQUARED RECHECK")
print("=" * 60)

# Format: {"variable": name, "F": F_statistic, "df_effect": between-groups df,
#          "df_error": within-groups df, "reported_eta_p2": their value}
# From their Table 2 (ANOVA results):
anova_rows = [
    # Replace with actual values from their Table 2:
    # {"variable": "Security Score", "F": 4.23, "df_effect": 5, "df_error": 132, "reported_eta_p2": 0.138},
    # {"variable": "Responsiveness", "F": 3.87, "df_effect": 5, "df_error": 132, "reported_eta_p2": 0.128},
]

if not anova_rows:
    print("\n  STATUS: F-statistics and df values not yet extracted from paper.")
    print("  Need: F, df_effect, df_error, and reported eta_p^2 from Table 2.")
    print("  Script structure is ready — fill in values and rerun.")
    print()
    print("  Formula: eta_p^2 = (df_effect * F) / (df_effect * F + df_error)")
    print("  Example: if F=4.23, df_effect=5, df_error=132:")
    computed_example = (5 * 4.23) / (5 * 4.23 + 132)
    print(f"           eta_p^2 = (5*4.23)/(5*4.23 + 132) = {computed_example:.4f}")
else:
    discrepancies = []
    for row in anova_rows:
        computed = (row["df_effect"] * row["F"]) / (row["df_effect"] * row["F"] + row["df_error"])
        reported = row["reported_eta_p2"]
        diff = abs(computed - reported)
        status = "MATCH" if diff < 0.005 else f"DISCREPANCY (diff={diff:.4f})"
        print(f"  {row['variable']}: F={row['F']}, computed eta_p^2={computed:.4f}, "
              f"reported={reported:.4f} -> {status}")
        if diff >= 0.005:
            discrepancies.append(row["variable"])

    if discrepancies:
        print(f"\n  FINDING: {len(discrepancies)} discrepancies found.")
        print(f"  Variables: {', '.join(discrepancies)}")
    else:
        print(f"\n  All {len(anova_rows)} rows match within tolerance.")

# ============================================================================
# SAVE
# ============================================================================
result = {
    "adamyk_audit": {
        "status": "script_ready" if not platforms and not anova_rows else "computed",
        "utility_recomputation": {
            "method": "U = a*exp(-b*epsilon) + c*exp(-d*R)",
            "platforms_checked": len(platforms),
            "note": "Parameter extraction from paper pending" if not platforms else "Computed",
        },
        "eta_squared_recheck": {
            "method": "eta_p^2 = (df_effect * F) / (df_effect * F + df_error)",
            "rows_checked": len(anova_rows),
            "note": "Value extraction from Table 2 pending" if not anova_rows else "Computed",
        },
        "finding": (
            "Script structure complete. Requires manual extraction of parameter values "
            "and F-statistics from the published paper to produce numerical results. "
            "The audit methodology is: (1) recompute utility from published parameters "
            "and flag ranking inconsistencies, (2) recompute eta_p^2 from F and df and "
            "flag discrepancies with reported effect sizes."
        ),
    }
}

OUTPUT.parent.mkdir(exist_ok=True)
with open(OUTPUT, "w") as f:
    json.dump(result, f, indent=2)
print(f"\nSaved to {OUTPUT}")
