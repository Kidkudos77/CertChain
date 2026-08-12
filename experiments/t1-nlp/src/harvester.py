"""
T1-NLP Harvester: MassTransfer Course Equivalency Database

Standalone script — no imports from Stage 2 or Stage 3.
Fetches course equivalency data from:
    https://www.mass.edu/masstransfer/equivalencies/PublicList.asp

Writes append-only JSONL with SHA-256 integrity hashes and UTC timestamps.
Resumes from checkpoint on restart. Rate-limited with configurable delay.

Usage:
    python harvester.py [--config harvest_config.yaml]
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent  # experiments/t1-nlp/

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_config(config_path: Path) -> dict:
    """Load YAML configuration file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def sha256_record(record: dict) -> str:
    """Compute SHA-256 of a record's canonical JSON (excluding meta fields)."""
    filtered = {k: v for k, v in record.items() if not k.startswith("_")}
    canonical = json.dumps(filtered, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_existing_hashes(output_path: Path) -> set:
    """Load SHA-256 hashes of all records already in the output file."""
    hashes = set()
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    h = record.get("_sha256", "")
                    if h:
                        hashes.add(h)
                except json.JSONDecodeError:
                    continue
    return hashes


def load_checkpoint(checkpoint_path: Path) -> dict:
    """Load checkpoint or return empty state."""
    if checkpoint_path.exists():
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_institutions": [], "rows_harvested": 0}


def save_checkpoint(checkpoint_path: Path, state: dict) -> None:
    """Atomically write checkpoint file."""
    tmp = checkpoint_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    tmp.replace(checkpoint_path)


def update_manifest(manifest_path: Path, output_path: Path) -> None:
    """Write SHA-256 of the entire output file to manifest."""
    h = hashlib.sha256()
    with open(output_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(f"{h.hexdigest()}  {output_path.name}\n")


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


class RateLimitedSession:
    """HTTP session with configurable delay between requests."""

    def __init__(self, config: dict):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config["user_agent"]})
        self.delay = config["delay_seconds"]
        self.timeout = config["timeout_seconds"]
        self.max_retries = config["max_retries"]
        self.backoff_factor = config["retry_backoff_factor"]
        self._last_request_time = 0.0

    def _wait(self) -> None:
        """Enforce rate limit between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            sleep_time = self.delay - elapsed
            logging.debug(f"Rate limit: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with rate limiting and retries."""
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """POST with rate limiting and retries."""
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Execute request with rate limiting, retries, and exponential backoff."""
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(self.max_retries + 1):
            self._wait()
            self._last_request_time = time.time()

            try:
                logging.info(f"{method} {url} (attempt {attempt + 1})")
                resp = self.session.request(method, url, **kwargs)
                logging.info(f"  -> {resp.status_code} ({len(resp.content)} bytes)")

                if resp.status_code == 200:
                    return resp
                elif resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        wait = self.backoff_factor ** attempt
                        logging.warning(
                            f"  Retryable {resp.status_code}, waiting {wait:.1f}s"
                        )
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                else:
                    resp.raise_for_status()

            except requests.exceptions.Timeout:
                if attempt < self.max_retries:
                    wait = self.backoff_factor ** attempt
                    logging.warning(f"  Timeout, retrying in {wait:.1f}s")
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError(f"All {self.max_retries + 1} attempts failed for {url}")


# ---------------------------------------------------------------------------
# Page Discovery
# ---------------------------------------------------------------------------


def discover_institutions(session: RateLimitedSession, base_url: str) -> list[dict]:
    """
    Fetch the search page and extract sending institutions from the
    PriInstID dropdown.
    """
    url = f"{base_url}/PublicList.asp"
    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "lxml")

    select = soup.find("select", {"name": "PriInstID"})
    if not select:
        logging.error("Could not find PriInstID dropdown on page.")
        return []

    institutions = []
    for option in select.find_all("option"):
        value = option.get("value", "").strip()
        text = option.get_text(strip=True)
        # Skip headers and "select" placeholder options
        if value and value != "0" and text and "-----" not in text and "Select" not in text:
            institutions.append({"id": value, "name": text})

    logging.info(f"Discovered {len(institutions)} sending institutions")
    return institutions


# ---------------------------------------------------------------------------
# Equivalency Fetching & Parsing
# ---------------------------------------------------------------------------

# Column indices based on observed table structure:
# 0: FROM institution
# 1: Course Code (sending)
# 2: Course Name (sending)
# 3: Credits (sending)
# 4: Gen Ed Requirement
# 5: (spacer/empty)
# 6: To institution
# 7: Course Code (receiving)
# 8: Course Name (receiving)
# 9: Credits Transferred
# 10: Note

COL_FROM = 0
COL_SEND_CODE = 1
COL_SEND_NAME = 2
COL_SEND_CREDITS = 3
COL_GEN_ED = 4
COL_TO = 6
COL_RECV_CODE = 7
COL_RECV_NAME = 8
COL_CREDITS_TRANSFERRED = 9
COL_NOTE = 10


def fetch_institution_equivalencies(
    session: RateLimitedSession,
    base_url: str,
    institution_id: str,
    department: str = "",
    include_discontinued: bool = True,
) -> list[dict]:
    """
    Submit the search form for a given institution and optional department filter.
    If department is empty, fetches all departments (large response).
    """
    url = f"{base_url}/PublicList.asp"

    form_data = {
        "dir": "from",
        "PriInstID": institution_id,
        "Department": department,
        "CourseID": "0",           # Any course
        "SecInstID": "0",          # Any receiving school
        "cmdList": "List course equivalencies",
    }
    if include_discontinued:
        form_data["chkIncludeOld"] = "-1"

    resp = session.post(url, data=form_data)
    if resp.status_code != 200:
        logging.warning(f"  Non-200 response ({resp.status_code}) for institution {institution_id}")
        return []

    return parse_results_table(resp.text, institution_id)


def parse_results_table(html: str, institution_id: str) -> list[dict]:
    """
    Parse the HTML results page. The equivalency data is in a table whose
    first header row contains: FROM, Course Code, Course Name, Credits, ...
    """
    soup = BeautifulSoup(html, "lxml")
    records = []

    # Find the results table by looking for a table with header "FROM"
    tables = soup.find_all("table")
    result_table = None

    for table in tables:
        first_row = table.find("tr")
        if not first_row:
            continue
        cells = first_row.find_all(["th", "td"])
        header_text = " ".join(c.get_text(strip=True).lower() for c in cells)
        if "from" in header_text and "course" in header_text:
            result_table = table
            break

    if not result_table:
        logging.debug(f"  No results table found for institution {institution_id}")
        return records

    # Parse all data rows (skip header)
    data_rows = result_table.find_all("tr")[1:]
    logging.info(f"  Found {len(data_rows)} data rows in results table")

    for row in data_rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 8:
            continue

        cell_texts = [c.get_text(strip=True) for c in cells]

        record = _extract_record(cell_texts, institution_id)
        if record:
            records.append(record)

    return records


def _extract_record(cells: list[str], institution_id: str) -> dict[str, Any] | None:
    """Extract a structured record from a row's cell texts."""

    def safe_get(idx: int) -> str:
        if 0 <= idx < len(cells):
            return cells[idx]
        return ""

    sending_code = safe_get(COL_SEND_CODE)
    sending_name = safe_get(COL_SEND_NAME)
    receiving_code = safe_get(COL_RECV_CODE)
    receiving_name = safe_get(COL_RECV_NAME)

    # Skip rows that are clearly empty
    if not sending_code and not sending_name and not receiving_name:
        return None

    record = {
        "sending_institution": safe_get(COL_FROM),
        "sending_course_code": sending_code,
        "sending_course_name": sending_name,
        "sending_credits": safe_get(COL_SEND_CREDITS),
        "gen_ed_requirement": safe_get(COL_GEN_ED),
        "receiving_institution": safe_get(COL_TO),
        "receiving_course_code": receiving_code,
        "receiving_course_name": receiving_name,
        "credits_transferred": safe_get(COL_CREDITS_TRANSFERRED),
        "note": safe_get(COL_NOTE),
        "_query_institution_id": institution_id,
    }

    return record


# ---------------------------------------------------------------------------
# Main Harvest Loop
# ---------------------------------------------------------------------------


def harvest(config: dict) -> None:
    """Main harvest loop: discover institutions → iterate → fetch → write."""
    base_url = config["base_url"]
    output_path = PROJECT_DIR / config["output_path"]
    checkpoint_path = PROJECT_DIR / config["checkpoint_path"]
    manifest_path = PROJECT_DIR / config["manifest_path"]
    include_discontinued = config.get("include_discontinued", True)
    department = config.get("department", "")

    # Ensure output directories exist
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load state
    existing_hashes = load_existing_hashes(output_path)
    checkpoint = load_checkpoint(checkpoint_path)
    completed_institutions = set(checkpoint.get("completed_institutions", []))
    rows_harvested = checkpoint.get("rows_harvested", 0)

    logging.info(f"Loaded checkpoint: {len(completed_institutions)} institutions done, {rows_harvested} rows total")
    logging.info(f"Existing unique hashes in output: {len(existing_hashes)}")

    session = RateLimitedSession(config)

    # Step 1: Discover institutions
    institutions = discover_institutions(session, base_url)
    if not institutions:
        logging.error("No institutions discovered. Exiting.")
        sys.exit(1)

    logging.info(f"Will harvest from {len(institutions)} institutions (department={department or 'ALL'})")

    # Step 2: Iterate over institutions
    new_records = 0
    duplicate_records = 0

    for inst in institutions:
        inst_id = inst["id"]
        inst_name = inst["name"]

        # Skip if already completed
        if inst_id in completed_institutions:
            logging.info(f"Skipping completed institution: {inst_name} ({inst_id})")
            continue

        logging.info(f"Fetching all equivalencies for: {inst_name} ({inst_id})")

        try:
            records = fetch_institution_equivalencies(
                session, base_url, inst_id, department, include_discontinued
            )
        except Exception as e:
            logging.error(f"  ERROR fetching {inst_name}: {e}")
            save_checkpoint(checkpoint_path, {
                "completed_institutions": list(completed_institutions),
                "rows_harvested": rows_harvested,
                "last_error": f"{inst_name}: {str(e)}",
            })
            continue

        # Write records (append-only, deduplicated)
        inst_new = 0
        inst_dup = 0
        with open(output_path, "a", encoding="utf-8") as f:
            for record in records:
                record_hash = sha256_record(record)
                record["_sha256"] = record_hash
                record["_accessed_utc"] = datetime.now(timezone.utc).isoformat()

                if record_hash in existing_hashes:
                    inst_dup += 1
                    duplicate_records += 1
                    continue

                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                existing_hashes.add(record_hash)
                inst_new += 1
                new_records += 1
                rows_harvested += 1

        # Mark institution as completed
        completed_institutions.add(inst_id)
        save_checkpoint(checkpoint_path, {
            "completed_institutions": list(completed_institutions),
            "rows_harvested": rows_harvested,
        })

        logging.info(
            f"  -> {len(records)} parsed, {inst_new} new, {inst_dup} duplicates"
        )

    # Final manifest update
    if output_path.exists() and output_path.stat().st_size > 0:
        update_manifest(manifest_path, output_path)

    logging.info("=" * 60)
    logging.info("HARVEST COMPLETE")
    logging.info(f"  Total rows harvested: {rows_harvested}")
    logging.info(f"  New records this run: {new_records}")
    logging.info(f"  Duplicates skipped: {duplicate_records}")
    logging.info(f"  Institutions processed: {len(completed_institutions)}")
    logging.info(f"  Output: {output_path}")
    logging.info(f"  Manifest: {manifest_path}")
    logging.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Harvest MassTransfer Course Equivalency Database"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(SCRIPT_DIR / "harvest_config.yaml"),
        help="Path to harvest configuration YAML file",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)

    # Ensure log directory exists
    log_dir = PROJECT_DIR / "data" / "raw"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Setup logging
    log_level = getattr(logging, config.get("log_level", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                log_dir / "harvest.log",
                mode="a",
                encoding="utf-8",
            ),
        ],
    )

    logging.info("=" * 60)
    logging.info("MassTransfer Course Equivalency Harvester")
    logging.info(f"Config: {config_path}")
    logging.info(f"Rate limit: {config['delay_seconds']}s between requests")
    logging.info(f"Output: {PROJECT_DIR / config['output_path']}")
    logging.info("=" * 60)

    harvest(config)


if __name__ == "__main__":
    main()
