"""
CertChain — MORES Key Management Plumbing (Phase 7 scaffolding)
====================================================================
Storage/distribution workflow for MORES key material, decided and built
now even though KGen() itself is still a stub (crypto/mores_service.py).
Nothing here depends on which pairing equations eventually back KGen —
only on where keys live and who gets which one.

Decision: piggyback on the existing wallet storage location
(wallet/store/), not a new secure channel. wallet/store/ already holds
each identity's X.509 credentials under a gitignored, locally-trusted
directory (see wallet/wallet_setup.js) — MORES key material gets its own
subdirectory there (wallet/store/mores/) rather than a parallel storage
system. This is a storage-location decision, not a claim that msk/qk are
X.509 certificates; the *trust model* (local filesystem, one file per
identity, never committed) is what's being reused.

  msk (master secret key) — one per institution, stays local to that
    institution. Used by Enc() at credential issuance time.
  qk  (query key) — one per authorized verifier, distributed out from the
    issuing institution. Used by TGen()/Cmp() at query time.
"""
import json
import os

from crypto.mores_service import KGen

STORE_DIR = os.path.join(os.path.dirname(__file__), '..', 'wallet', 'store', 'mores')


def _path_for(kind, identity_id):
    if kind not in ('msk', 'qk'):
        raise ValueError("kind must be 'msk' or 'qk'")
    return os.path.join(STORE_DIR, f'{identity_id}.{kind}.json')


def _ensure_store_dir():
    os.makedirs(STORE_DIR, exist_ok=True, mode=0o700)


def issue_institution_keys(institution_id):
    """Run KGen() for an institution, store its msk locally, and return
    the qk half so it can be distributed to verifiers.

    KGen() (crypto/mores_service.py) returns {'msk': ..., 'qk': ...} —
    both halves already JSON-serialized (see crypto/mores_serialize.py),
    not a raw (msk, qk) tuple. An earlier version of this function did
    `msk, qk = KGen()`, which would have silently unpacked the dict's KEY
    STRINGS ('msk', 'qk') instead of their values — a bug that was never
    caught while KGen() was a stub raising NotImplementedError before any
    unpacking happened. Caught here once KGen() actually returned data.
    """
    keys = KGen()
    msk, qk = keys['msk'], keys['qk']
    _ensure_store_dir()
    with open(_path_for('msk', institution_id), 'w') as f:
        json.dump({'institutionId': institution_id, 'msk': msk}, f)
    return qk


def distribute_qk(verifier_id, qk):
    """Store a query key for a verifier who has been granted range-query
    access. Distribution channel: the same trusted local storage as the
    institution's own msk — see module docstring for why.
    """
    _ensure_store_dir()
    with open(_path_for('qk', verifier_id), 'w') as f:
        json.dump({'verifierId': verifier_id, 'qk': qk}, f)


def load_msk(institution_id):
    path = _path_for('msk', institution_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f'No msk stored for institution {institution_id}.')
    with open(path) as f:
        return json.load(f)['msk']


def load_qk(verifier_id):
    path = _path_for('qk', verifier_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f'No qk stored for verifier {verifier_id}.')
    with open(path) as f:
        return json.load(f)['qk']
