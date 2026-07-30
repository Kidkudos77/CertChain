"""
CertChain — MMR Batch Anchoring
==================================
Selects credentials not yet folded into a Merkle Mountain Range batch,
anchors their MMR root on-chain (chaincode: anchorMMRRoot), and can
round-trip an inclusion proof through verification as a smoke test.

This does not touch the existing per-credential CRED~<hash> scheme or the
existing /verify/:hash endpoint — it is a separate, additive integrity
layer (see chaincode/mmr.js and the anchorMMRRoot doc comment in
chaincode/certchain.js). Run it on whatever cadence fits the deployment
(daily cron, weekly cron, after each institution's issuance run, etc.) —
each run picks a batchId and anchors everything selected into it.

Usage:
  # Anchor everything issued since a given time into an explicit batch
  python integration/mmr_anchor.py --since 2026-07-30T00:00:00Z --batch-id famu-2026-07-30

  # Anchor everything not yet batched (batchId auto-generated as famu-<UTC date>)
  python integration/mmr_anchor.py

  # Anchor, then round-trip a proof for one credential as a smoke test
  python integration/mmr_anchor.py --verify <credHash>

Auth: requires an institution or admin account. Set CERTCHAIN_USER /
CERTCHAIN_PASSWORD, or pass --user / --password.
"""

import argparse, json, logging, os, sys
from datetime import datetime, timezone

import requests

log = logging.getLogger('CertChain')
logging.basicConfig(level=logging.INFO, format='%(levelname)s | %(message)s')

API_BASE = os.getenv('CERTCHAIN_API', 'http://localhost:3000')


def login(user_id: str, password: str) -> str:
    r = requests.post(f'{API_BASE}/auth/login', json={'userID': user_id, 'password': password}, timeout=15)
    result = r.json()
    if not result.get('ok'):
        raise RuntimeError(f"Login failed: {result.get('error', 'unknown error')}")
    return result['token']


def auth_headers(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def anchor_batch(token: str, batch_id: str, since: str = None) -> dict:
    r = requests.get(f'{API_BASE}/mmr/unanchored', params={'since': since or ''},
                      headers=auth_headers(token), timeout=30)
    r.raise_for_status()
    unanchored = r.json()
    cred_hashes = [c['credHash'] for c in unanchored['credentials']]

    if not cred_hashes:
        log.info('No unanchored credentials found — nothing to batch.')
        return {'anchored': False, 'reason': 'no unanchored credentials'}

    log.info(f'Batching {len(cred_hashes)} credential(s) into batch "{batch_id}"...')
    r = requests.post(f'{API_BASE}/mmr/anchor',
                       json={'batchId': batch_id, 'credHashes': cred_hashes},
                       headers=auth_headers(token), timeout=30)
    result = r.json()

    if r.status_code != 201:
        raise RuntimeError(f'Anchoring failed: {result.get("error", result)}')

    log.info(f'Anchored batch "{batch_id}" — root {result["root"][:16]}... '
             f'({result["leafCount"]} credentials)')
    return {'anchored': True, 'batchId': batch_id, 'credHashes': cred_hashes, **result}


def verify_round_trip(token: str, batch_id: str, cred_hash: str) -> bool:
    r = requests.get(f'{API_BASE}/mmr/proof/{batch_id}/{cred_hash}', headers=auth_headers(token), timeout=15)
    r.raise_for_status()
    proof = r.json()['proof']

    r = requests.post(f'{API_BASE}/mmr/verify',
                       json={'credHash': cred_hash, 'batchId': batch_id, 'proof': proof},
                       headers=auth_headers(token), timeout=15)
    result = r.json()
    is_valid = result.get('isValid', False)
    log.info(f'Inclusion proof for {cred_hash[:16]}... in batch "{batch_id}": '
             f'{"VALID" if is_valid else "INVALID"}')
    return is_valid


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--since', type=str, default=None,
                    help='ISO8601 timestamp — only batch credentials issued at/after this time.')
    p.add_argument('--batch-id', type=str, default=None,
                    help='Batch ID to anchor under. Defaults to famu-<UTC date>.')
    p.add_argument('--verify', type=str, default=None,
                    help='After anchoring, fetch + verify an inclusion proof for this credHash.')
    p.add_argument('--user', type=str, default=os.getenv('CERTCHAIN_USER'))
    p.add_argument('--password', type=str, default=os.getenv('CERTCHAIN_PASSWORD'))
    args = p.parse_args()

    if not args.user or not args.password:
        log.error('Missing credentials. Set CERTCHAIN_USER/CERTCHAIN_PASSWORD or pass --user/--password.')
        sys.exit(1)

    batch_id = args.batch_id or f'famu-{datetime.now(timezone.utc).strftime("%Y-%m-%d")}'

    try:
        token  = login(args.user, args.password)
        result = anchor_batch(token, batch_id, since=args.since)

        if args.verify and result.get('anchored'):
            if args.verify not in result['credHashes']:
                log.warning(f'{args.verify} was not part of this batch — skipping verification.')
            else:
                verify_round_trip(token, batch_id, args.verify)

        print(json.dumps(result, indent=2))
    except requests.exceptions.ConnectionError:
        log.error(f'Could not reach API at {API_BASE}. Is the server running?')
        sys.exit(1)
    except Exception as e:
        log.error(str(e))
        sys.exit(1)
