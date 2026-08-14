"""
Dump all 24 misparsed rows (name > 60 chars) with EVERY field visible.
Check whether sending_credits and other columns are intact or shifted.
"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).resolve().parent.parent
catalog = PROJECT_DIR / "data" / "raw" / "equivalencies.jsonl"
OUTPUT = PROJECT_DIR / "scratch" / "misparsed_output.txt"

# Artifact patterns (same as canonicalization rule)
ARTIFACT_PATTERNS = [
    r"This course",
    r"Students may",
    r"Special Requirement",
    r"\d+-[A-Z]",
]

def has_artifact(name):
    for p in ARTIFACT_PATTERNS:
        if re.search(p, name):
            return True
    return False

# Redirect all output to file
import io
out = io.StringIO()

def p(s=""):
    out.write(s + "\n")

# Load ALL records (not deduplicated) that have the artifact in name
# Group by (institution, code) to get first occurrence
first_seen = {}
with open(catalog, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        r = json.loads(line)
        key = (r.get("sending_institution", ""), r.get("sending_course_code", ""))
        name = r.get("sending_course_name", "")
        if key not in first_seen and has_artifact(name):
            first_seen[key] = r

p(f"Misparsed courses (artifact in sending_course_name): {len(first_seen)}")
p()
p("=" * 90)

for (inst, code), r in sorted(first_seen.items()):
    name = r.get("sending_course_name", "")
    credits = r.get("sending_credits", "")
    recv_inst = r.get("receiving_institution", "")
    recv_code = r.get("receiving_course_code", "")
    recv_name = r.get("receiving_course_name", "")
    credits_trans = r.get("credits_transferred", "")
    gen_ed = r.get("gen_ed_requirement", "")
    note = r.get("note", "")

    p(f"  INSTITUTION:        {inst}")
    p(f"  CODE:               {code}")
    p(f"  NAME (raw):         {name[:120]}")
    p(f"  SENDING_CREDITS:    '{credits}'")
    p(f"  GEN_ED:             '{gen_ed}'")
    p(f"  RECEIVING_INST:     '{recv_inst}'")
    p(f"  RECEIVING_CODE:     '{recv_code}'")
    p(f"  RECEIVING_NAME:     '{recv_name[:80]}'")
    p(f"  CREDITS_TRANSFERRED:'{credits_trans}'")
    p(f"  NOTE:               '{note[:80]}'")
    p()

    for pat in ARTIFACT_PATTERNS:
        m = re.search(pat, name)
        if m:
            clean_name = name[:m.start()].strip()
            tail = name[m.start():]
            p(f"  CLEAN NAME:         '{clean_name}'")
            p(f"  TAIL (artifact):    '{tail[:80]}'")
            break
    p(f"  {'-'*80}")
    p()

OUTPUT.write_text(out.getvalue(), encoding="utf-8")
print(f"Written to {OUTPUT}")
