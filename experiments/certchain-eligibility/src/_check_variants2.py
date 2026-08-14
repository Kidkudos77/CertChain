"""Check name variants more carefully — isolate the parsing issue."""
import json
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).resolve().parent.parent
catalog = PROJECT_DIR / "data" / "raw" / "equivalencies.jsonl"

# Load unique courses (first name seen per institution+code)
first_seen = {}
all_names = defaultdict(set)

with open(catalog, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        r = json.loads(line)
        key = (r.get("sending_institution", ""), r.get("sending_course_code", ""))
        name = r.get("sending_course_name", "").strip()
        all_names[key].add(name)
        if key not in first_seen:
            first_seen[key] = name

# Check for truly different names (not just concatenation artifacts)
print(f"Total unique (institution, code) pairs: {len(first_seen)}")
print()

# The sending_course_name should be clean from the harvester.
# Check a few samples for concatenation issues.
print("SAMPLE SENDING COURSE NAMES (first 20):")
for i, ((inst, code), name) in enumerate(sorted(first_seen.items())[:20]):
    print(f"  {inst} / {code}: [{len(name)} chars] {name[:80]}")

print()
print("NAMES LONGER THAN 60 CHARS (likely concatenation artifacts):")
long_names = [(k, n) for k, n in first_seen.items() if len(n) > 60]
print(f"  Count: {len(long_names)} / {len(first_seen)}")
for (inst, code), name in sorted(long_names)[:10]:
    print(f"  {inst} / {code}: {name[:100]}...")

print()
print("CODES WITH MULTIPLE DISTINCT NAMES (after truncating at 50 chars):")
multi = {}
for key, names in all_names.items():
    # Truncate to first 50 chars to ignore concatenation junk
    short_names = set(n[:50] for n in names)
    if len(short_names) > 1:
        multi[key] = short_names

print(f"  Count: {len(multi)}")
for (inst, code), names in sorted(multi.items())[:15]:
    print(f"  {inst} / {code}:")
    for n in sorted(names):
        print(f"    - {n}")
