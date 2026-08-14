"""
Full canonicalization sweep across all 178 courses.
1. Apply canonicalization to every name
2. Flag any residual artifacts (digit+capital, institution names, keywords)
3. Print all names that were truncated and confirm no legitimate content lost
4. Identify the 24 vs 23 discrepancy
"""
import json
import re
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).resolve().parent.parent
catalog = PROJECT_DIR / "data" / "raw" / "equivalencies.jsonl"
OUTPUT = PROJECT_DIR / "scratch" / "full_canon_sweep.txt"

ARTIFACT_PATTERNS = [
    r"This course",
    r"Students may",
    r"Special Requirement",
    r"\d+-[A-Z]",
]

INSTITUTION_NAMES = [
    "Berkshire", "Bristol", "Bunker Hill", "Cape Cod", "Greenfield",
    "Holyoke", "Massasoit", "MassBay", "Middlesex", "Mount Wachusett",
    "North Shore", "Northern Essex", "Quinsigamond", "Roxbury", "Springfield",
    "Bridgewater", "Fitchburg", "Framingham", "MCLA", "Salem",
    "Westfield", "Worcester", "UMass",
]

SUSPICIOUS_KEYWORDS = ["credit", "offered", "prerequisite", "not open to", "cross-listed"]


def canonicalize(name):
    for pattern in ARTIFACT_PATTERNS:
        match = re.search(pattern, name)
        if match:
            return name[:match.start()].strip(), name[match.start():]
    return name.strip(), None


# Load unique courses
first_seen = {}
with open(catalog, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        r = json.loads(line)
        key = (r.get("sending_institution", ""), r.get("sending_course_code", ""))
        if key not in first_seen:
            first_seen[key] = r.get("sending_course_name", "")

out = []
out.append(f"Total unique courses: {len(first_seen)}")
out.append("")

# Apply canonicalization to all
truncated = []
clean_names = {}
for (inst, code), raw_name in sorted(first_seen.items()):
    clean, tail = canonicalize(raw_name)
    clean_names[(inst, code)] = clean
    if tail:
        truncated.append((inst, code, clean, tail))

out.append(f"Names truncated by canonicalization: {len(truncated)}")
out.append("")

# List ALL truncated names
out.append("=" * 80)
out.append("ALL TRUNCATED NAMES (confirm no legitimate content lost)")
out.append("=" * 80)
for inst, code, clean, tail in truncated:
    out.append(f"  {inst} / {code}")
    out.append(f"    CLEAN: '{clean}'")
    out.append(f"    TAIL:  '{tail[:80]}'")
    out.append("")

# Now check all 178 CLEAN names for residual artifacts
out.append("=" * 80)
out.append("RESIDUAL ARTIFACT CHECK (on canonicalized names)")
out.append("=" * 80)

# Check 1: digit immediately followed by capital letter
digit_cap = []
for (inst, code), name in sorted(clean_names.items()):
    if re.search(r"\d[A-Z]", name):
        digit_cap.append((inst, code, name))

out.append(f"\nDigit+Capital in clean name: {len(digit_cap)}")
for inst, code, name in digit_cap:
    out.append(f"  {inst} / {code}: {name}")

# Check 2: embedded institution name
embedded_inst = []
for (inst, code), name in sorted(clean_names.items()):
    for iname in INSTITUTION_NAMES:
        if iname.lower() in name.lower() and iname.lower() not in inst.lower():
            embedded_inst.append((inst, code, name, iname))
            break

out.append(f"\nEmbedded institution name in clean name: {len(embedded_inst)}")
for inst, code, name, found in embedded_inst:
    out.append(f"  {inst} / {code}: '{name}' contains '{found}'")

# Check 3: suspicious keywords
keyword_hits = []
for (inst, code), name in sorted(clean_names.items()):
    for kw in SUSPICIOUS_KEYWORDS:
        if kw.lower() in name.lower():
            keyword_hits.append((inst, code, name, kw))
            break

out.append(f"\nSuspicious keywords in clean name: {len(keyword_hits)}")
for inst, code, name, kw in keyword_hits:
    out.append(f"  {inst} / {code}: '{name}' contains '{kw}'")

# Discrepancy check: 24 (>60 chars raw) vs 23 (artifact pattern match)
out.append("")
out.append("=" * 80)
out.append("24 vs 23 DISCREPANCY")
out.append("=" * 80)

long_names = [(k, v) for k, v in first_seen.items() if len(v) > 60]
artifact_names = [(k, v) for k, v in first_seen.items()
                  if any(re.search(p, v) for p in ARTIFACT_PATTERNS)]

out.append(f"Names > 60 chars: {len(long_names)}")
out.append(f"Names matching artifact patterns: {len(artifact_names)}")

# Find the one in long but not in artifact
long_set = set(k for k, _ in long_names)
art_set = set(k for k, _ in artifact_names)
in_long_not_art = long_set - art_set
in_art_not_long = art_set - long_set

out.append(f"\nIn >60 but NOT matching artifact pattern: {len(in_long_not_art)}")
for k in in_long_not_art:
    out.append(f"  {k[0]} / {k[1]}: '{first_seen[k][:100]}'")

out.append(f"\nMatching artifact but <= 60 chars: {len(in_art_not_long)}")
for k in in_art_not_long:
    out.append(f"  {k[0]} / {k[1]}: '{first_seen[k]}'")

OUTPUT.write_text("\n".join(out), encoding="utf-8")
print(f"Written to {OUTPUT}")
