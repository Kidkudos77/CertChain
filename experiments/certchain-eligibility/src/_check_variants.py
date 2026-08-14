"""
Check for course codes with multiple name variants.
Also confirm prerequisite handling.
"""
import json
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).resolve().parent.parent
catalog = PROJECT_DIR / "data" / "raw" / "equivalencies.jsonl"

# Build: (institution, code) -> set of names
code_names = defaultdict(set)
with open(catalog, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        r = json.loads(line)
        key = (r.get("sending_institution", ""), r.get("sending_course_code", ""))
        name = r.get("sending_course_name", "").strip()
        if name:
            code_names[key].add(name)

# Find codes with multiple names
print("=" * 70)
print("COURSE CODES WITH MULTIPLE NAME VARIANTS")
print("=" * 70)
multi = {k: v for k, v in code_names.items() if len(v) > 1}
print(f"\nTotal unique (institution, code) pairs: {len(code_names)}")
print(f"Pairs with multiple name variants: {len(multi)}")
print()

for (inst, code), names in sorted(multi.items()):
    print(f"  {inst} / {code}:")
    for n in sorted(names):
        print(f"    - {n}")
    print()

# Confirm prerequisite
print("=" * 70)
print("PREREQUISITE CHECK")
print("=" * 70)
import yaml
req_path = PROJECT_DIR / "src" / "requirements.yaml"
with open(req_path) as f:
    reqs = yaml.safe_load(f)

prereq = reqs.get("prerequisite", {})
print(f"\nPrerequisite: {prereq.get('code')} — {prereq.get('name')}")
print(f"Note: {prereq.get('note', '').strip()}")
print(f"\nRequirements (denominator): {len(reqs.get('requirements', []))}")
for r in reqs.get("requirements", []):
    print(f"  {r['id']}: {r['code']} — {r['name']}")
print(f"\ncourse_completion denominator = {len(reqs['requirements'])} (prerequisite excluded)")
