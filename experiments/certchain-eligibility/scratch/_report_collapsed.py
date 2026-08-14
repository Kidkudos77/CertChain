"""Report which codes collapsed during dedup (status suffix stripped)."""
import json, re
from pathlib import Path
from collections import defaultdict

catalog = Path(__file__).resolve().parent.parent / "data" / "raw" / "equivalencies.jsonl"

def parse_code(raw):
    m = re.search(r"#\(", raw)
    if not m:
        return raw.strip(), "active"
    base = raw[:m.start()].strip()
    suffix = raw[m.start():].lower()
    if "replaced" in suffix: return base, "replaced"
    elif "disc" in suffix: return base, "discontinued"
    return base, "inactive"

# Group by (institution, base_code)
groups = defaultdict(list)
seen_raw = set()
with open(catalog, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip(): continue
        r = json.loads(line)
        raw_code = r.get("sending_course_code", "")
        inst = r.get("sending_institution", "")
        key = (inst, raw_code)
        if key in seen_raw: continue
        seen_raw.add(key)
        base, status = parse_code(raw_code)
        groups[(inst, base)].append((raw_code, status))

collapsed = {k: v for k, v in groups.items() if len(v) > 1}
out = Path(__file__).resolve().parent.parent / "scratch" / "collapsed_codes.txt"
lines = [f"Codes that collapsed (same base, different status): {len(collapsed)}", ""]
for (inst, base), variants in sorted(collapsed.items()):
    lines.append(f"  {inst} / {base}:")
    for raw, status in variants:
        lines.append(f"    {raw} -> {status}")
    lines.append("")
lines.append(f"Total raw codes: {len(seen_raw)}")
lines.append(f"After dedup: {len(groups)}")
lines.append(f"Collapsed: {len(seen_raw) - len(groups)}")
out.write_text("\n".join(lines), encoding="utf-8")
print(f"Written to {out}")
