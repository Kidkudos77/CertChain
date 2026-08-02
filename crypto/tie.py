"""
CertChain — TIE (Testable Inner-product/Equality) primitive
================================================================
Transcribed directly from Hahn's paper, Section IV-A (KeyGen/EncL/EncR/Dec),
per the roadmap's equation-verification pass. This is the base primitive
MORES (crypto/mores_core.py) is built on top of — see that module for the
digit-decomposition ORE construction and the actual KGen/Enc/TGen/Cmp
interface CertChain calls.

Correctness, verified algebraically here (not just transcribed) before
writing code against it:

    e(L_t, R0)   = e(g1,g2) ^ ((H(k1,m_t)+k3)*k2*r * k2^-1*r')
                 = e(g1,g2) ^ ((H(k1,m_t)+k3)*r*r')
    e(L_{N+1}, R_{N+1}) = e(g1,g2) ^ (k3^2*r * k3^-1*r') = e(g1,g2) ^ (k3*r*r')
    => e(L_t,R0) / e(L_{N+1},R_{N+1}) = e(g1,g2) ^ (H(k1,m_t)*r*r')

    e(L0, R_u) = e(g1,g2) ^ (r * H(k1,m'_u)*r') = e(g1,g2) ^ (H(k1,m'_u)*r*r')

So the Dec equality test holds iff H(k1,m_t) == H(k1,m'_u) (mod p), i.e. iff
m_t == m'_u (H is a keyed PRF into Zp, collision resistance assumed) —
without either side ever learning m_t or m'_u themselves. This matches the
paper's own correctness claim (Section IV-A, "2) Correctness").

Still recommended before this protects real FERPA data: an independent
cryptographic read-through beyond this transcription+algebra check — see
the roadmap, Phase 7, item 3. This module is safe to build and test against
now; it is not yet independently peer-reviewed.

Message vectors are plain 0-indexed Python lists here (list position k
represents the paper's 1-indexed m_{k+1}), so Dec's returned pairs are
already 0-indexed and can be used directly by callers without an off-by-one
translation.
"""
import hashlib
import secrets

from py_ecc.bls12_381 import G1, G2, add, curve_order, multiply, pairing

Zp = curve_order


def _rand_scalar():
    return secrets.randbelow(Zp - 1) + 1  # nonzero element of Zp


def _inv(x, mod=Zp):
    return pow(x, mod - 2, mod)


def H(k1: int, m: int) -> int:
    """Keyed PRF into Zp. HMAC-SHA256(k1, m) reduced mod p — instantiation
    choice explicitly left to the implementer by the roadmap spec.
    """
    key = k1.to_bytes(32, "big")
    msg = int(m).to_bytes(32, "big", signed=False) if m >= 0 else (int(m) % (2**256)).to_bytes(32, "big")
    digest = hashlib.sha256(key + b"|H|" + msg).digest()
    return int.from_bytes(digest, "big") % Zp


def keygen():
    """TIE.KeyGen(lambda) -> (kL, kR)."""
    k1 = _rand_scalar()
    k2 = _rand_scalar()
    k3 = _rand_scalar()
    rho1 = multiply(G2, _inv(k2))
    rho2 = multiply(G2, _inv(k3))
    kL = (k1, k2, k3)
    kR = (k1, rho1, rho2)
    return kL, kR


def enc_l(kL, M):
    """TIE.EncL(kL, M=(m_1,...,m_N)) -> ctL = (L0, L1..LN, L_{N+1})."""
    k1, k2, k3 = kL
    r = _rand_scalar()
    L0 = multiply(G1, r)
    Ls = [multiply(G1, ((H(k1, m) + k3) * k2 * r) % Zp) for m in M]
    Ln1 = multiply(G1, (pow(k3, 2, Zp) * r) % Zp)
    return (L0, Ls, Ln1)


def enc_r(kR, Mp):
    """TIE.EncR(kR, M'=(m'_1,...,m'_N)) -> ctR = (R0, R1..RN, R_{N+1})."""
    k1, rho1, rho2 = kR
    rp = _rand_scalar()
    R0 = multiply(rho1, rp)
    Rs = [multiply(G2, (H(k1, m) * rp) % Zp) for m in Mp]
    Rn1 = multiply(rho2, rp)
    return (R0, Rs, Rn1)


def _e(g1_point, g2_point):
    """e(P, Q) with P in G1, Q in G2 — py_ecc's pairing() takes (G2, G1)."""
    return pairing(g2_point, g1_point)


def dec(ctL, ctR):
    """TIE.Dec(ctL, ctR) -> S, a set of 0-indexed (t, u) pairs where ctL's
    t-th message component equals ctR's u-th message component.
    """
    L0, Ls, Ln1 = ctL
    R0, Rs, Rn1 = ctR
    denom = _e(Ln1, Rn1)
    denom_inv = denom.inv()  # FQ12's own field inverse — `** -1` segfaults in this environment, see tie_selftest.py notes
    # Each e(L_t,R0) and e(L0,R_u) is computed once (N+N pairings total, plus
    # the one denom pairing) rather than once per (t,u) pair — an N^2 nested
    # loop over pairing() calls would be the same math but ~N times slower
    # for no reason, and pairings are already the bottleneck (~3.5s each,
    # see roadmap Phase 7's performance finding).
    lhs_vals = [_e(Lt, R0) * denom_inv for Lt in Ls]
    rhs_vals = [_e(L0, Ru) for Ru in Rs]
    S = set()
    for t, lhs in enumerate(lhs_vals):
        for u, rhs in enumerate(rhs_vals):
            if lhs == rhs:
                S.add((t, u))
    return S
