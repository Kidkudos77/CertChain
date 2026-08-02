"""
CertChain — MORES (Multi-client Order-Revealing Encryption Scheme)
=======================================================================
Transcribed directly from Hahn's paper, Section IV-B, per the roadmap's
equation-verification pass. Built on TIE (crypto/tie.py) exactly as the
paper specifies: MORES's KeyGen/Enc/TGen literally construct a message
vector and hand it to TIE.EncL/EncR; Cmp interprets TIE.Dec's output.

Two instantiation choices the spec explicitly leaves open (roadmap: "Both
need to be instantiated consistently... this is an implementation decision
within the spec, not a deviation from it"):
  - F, the PRF used for prefix-masking: HMAC-SHA256 keyed by msk/qk's shared
    k1 (the same key TIE's own H already uses — kL and kR both start with
    k1, so both Enc and TGen have access to it without a separate key).
  - lambda (the modulus 2^lambda for u_i/v_i arithmetic): defaults to 128
    (DEFAULT_LAMBDA below), independent of n. This must be large — it's a
    collision-avoidance security parameter for the masked u_i/v_i values,
    not related to how many bits the plaintext needs. An earlier version
    of this module defaulted lambda to n, which is wrong (see
    DEFAULT_LAMBDA's comment for the concrete failure this caused).

Honest discrepancy worth flagging, not smoothing over: the paper's own
Table I gives MORES's Cmp cost as (n+2) pairings. Implementing Dec's
literal double loop as specified here (every L_t paired with R0 once,
every L0 paired with every R_u once, each pairing computed once and
reused rather than recomputed per (t,u) pair) comes out to 2N+1 pairings,
where N = n+1 is TIE's own vector length once MORES's position-0 slot is
included — i.e. 2n+3, not n+2. This transcription doesn't include Table
I's cost-derivation section, so there may be a batching/amortization
detail in the paper this implementation doesn't capture. Correctness was
verified independently here (see the algebra in tie.py and the
known-answer tests in mores_selftest.py); the exact pairing count was
not independently re-derived against the paper's complexity proof, only
against what the transcribed Dec algorithm literally requires. Treat
"2n+3 pairings" as this implementation's measured cost, not a confirmed
match to the paper's stated (n+2).

Values being compared (x, y) are encoded as n-bit unsigned integers,
MSB-first (x_1 = most significant bit ... x_n = least significant bit) —
the standard prefix/digit-decomposition ORE convention. n is a per-call
parameter, not hardcoded, because the actual bit-width (and therefore the
(n+2)-pairing cost per Cmp — see the roadmap's performance finding) is a
deployment decision, not part of the cryptographic spec itself.

STILL PENDING (see roadmap, Phase 7, item 3): an independent
cryptographic read-through by someone other than the person who wrote
this transcription, before this protects real FERPA data. This module
is tested against known-answer cases (equal / less-than / greater-than)
in mores_selftest.py, which gives empirical confidence the transcription
and implementation agree with each other — it is not a substitute for
that independent review.
"""
import hashlib
import secrets

import tie


def _prf_f(k1: int, i: int, prefix_bits) -> int:
    """F(i, prefix) keyed by k1 -- see module docstring for the
    instantiation choice. prefix_bits is an iterable of 0/1 ints, always
    length n regardless of i (real bits followed by zero-padding), matching
    the paper's "x1...x(i-1) || 0^(n-i+1)" construction.
    """
    key = k1.to_bytes(32, "big")
    prefix_bytes = bytes(prefix_bits)
    msg = i.to_bytes(4, "big") + prefix_bytes
    digest = hashlib.sha256(key + b"|F|" + msg).digest()
    return int.from_bytes(digest, "big")


def _bits_msb_first(x: int, n: int):
    if not (0 <= x < (1 << n)):
        raise ValueError(f"value {x} does not fit in {n} bits")
    return [(x >> (n - 1 - i)) & 1 for i in range(n)]


def _prefix_for(bits, i, n):
    """bits[0 : i-1] followed by zero-padding, total length n (1-indexed i)."""
    real = bits[: i - 1]
    return real + [0] * (n - len(real))


def _permute(values):
    """Random permutation of a list, returned as a new list (Fisher-Yates)."""
    out = list(values)
    for i in range(len(out) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        out[i], out[j] = out[j], out[i]
    return out


# Security parameter for the u_i/v_i masking modulus (2^lambda). This is NOT
# the plaintext bit-width n — it must be large enough that two unrelated
# masked values collide only with cryptographically negligible probability
# (~1/2^lambda per unrelated position pair). Defaulting it to n (as an
# earlier version of this module did) is wrong: at n=3 the modulus is only
# 8, giving an ~1/8 accidental-collision rate per position, which produced
# an actual wrong Cmp result in mores_selftest.py's x>y case before this
# was caught by testing. 128 bits keeps collisions negligible regardless of
# how small n is for a given deployment.
DEFAULT_LAMBDA = 128


def keygen():
    """MORES.KeyGen(lambda) -> (msk, qk)."""
    kL, kR = tie.keygen()
    return kL, kR  # msk = kL, qk = kR


def enc(msk, x: int, n: int, lam: int = None):
    """MORES.Enc(msk, x) for an n-bit value x. Returns ctx (opaque to callers
    other than dec/cmp — do not inspect its internal structure)."""
    lam = lam or DEFAULT_LAMBDA
    modulus = 1 << lam
    k1 = msk[0]
    bits = _bits_msb_first(x, n)
    u = []
    for i in range(1, n + 1):
        prefix = _prefix_for(bits, i, n)
        xi = bits[i - 1]
        u.append((_prf_f(k1, i, prefix) + xi) % modulus)
    X_hat = [x] + _permute(u)
    return tie.enc_l(msk, X_hat)


def tgen(qk, y: int, n: int, lam: int = None):
    """MORES.TGen(qk, y) for an n-bit value y. Returns ty."""
    lam = lam or DEFAULT_LAMBDA
    modulus = 1 << lam
    k1 = qk[0]
    bits = _bits_msb_first(y, n)
    v = []
    for i in range(1, n + 1):
        prefix = _prefix_for(bits, i, n)
        yi = bits[i - 1]
        v.append((_prf_f(k1, i, prefix) + yi - 1) % modulus)
    Y_hat = [y] + _permute(v)
    return tie.enc_r(qk, Y_hat)


def cmp(ctx, ty):
    """MORES.Cmp(ctx, ty) -> 0 (x == y), 1 (x < y), or None (x > y, the
    paper's bottom/'undefined' symbol)."""
    S = tie.dec(ctx, ty)
    if (0, 0) in S:
        return 0
    if any(i >= 1 and j >= 1 for (i, j) in S):
        return 1
    return None
