"""
CertChain — DERE (Delegable Equality-Revealing Encryption)
================================================================
Transcribed from Kwon & Hahn, Section 3 — the building block UNIQUE
(crypto/unique_core.py, not yet built — see that module's docstring) is
constructed on top of. Per the roadmap's equation-verification pass.

Correctness, verified algebraically here before writing code against it —
this transcription went through a real correction first (see git history /
the roadmap): the original pass had TokGen's second token as
`pk(v)^(α(u)/β(u))` (division), which does not cancel in Test and would
make equality-revealing fail even for equal messages. Re-checked directly
against the source PDF: the paper states `α(u)·β(u)` (product). With the
product form:

    Writing H(m) = g1^k(m) (the paper's own device for this derivation —
    the real H below is an ordinary hash-to-G1, not a literal discrete log):

    c0(u) = g1^((r(u)*beta(u) + k(u)) * alpha(u))      [Enc]
    c1(u) = g1^(r(u))
    t0(v->u) = g2^(alpha(v))                            [TokGen, corrected]
    t1(v->u) = g2^(alpha(v) * alpha(u) * beta(u))

    e(c0(u), t0(v->u)) = e(g1,g2) ^ ((r(u)*beta(u)+k(u)) * alpha(u)*alpha(v))
    e(c1(u), t1(v->u)) = e(g1,g2) ^ (r(u) * alpha(v)*alpha(u)*beta(u))

    d0 = e(c0(u),t0(v->u)) / e(c1(u),t1(v->u))
       = e(g1,g2) ^ (k(u) * alpha(u) * alpha(v))          <- r(u)*beta(u) term cancels exactly

Symmetrically d1 = e(g1,g2)^(k(v)*alpha(v)*alpha(u)). Since alpha(u)*alpha(v)
== alpha(v)*alpha(u), d0 == d1 iff k(u) == k(v) iff m(u) == m(v) (H
collision-resistant). This matches the paper's own stated result and is
what DERE.Test below is actually built against — not the uncorrected
division form.

Still pending, same as MORES/TIE: an independent cryptographic
read-through before this protects real FERPA data.
"""
import hashlib
import secrets

from py_ecc.bls12_381 import G1, G2, add, curve_order, multiply, pairing

Zp = curve_order


def _rand_scalar():
    return secrets.randbelow(Zp - 1) + 1  # nonzero element of Zp*


def _hash_to_g1(m) -> tuple:
    """H: {0,1}* -> G1, via hash-to-scalar then exponentiate g1. This is the
    concrete instantiation of the paper's H(m) = g1^k(m) device."""
    digest = hashlib.sha256(b"DERE|H|" + str(m).encode("utf-8")).digest()
    k = int.from_bytes(digest, "big") % Zp
    return multiply(G1, k)


def _e(g1_point, g2_point):
    """e(P, Q) with P in G1, Q in G2 — py_ecc's pairing() takes (G2, G1)."""
    return pairing(g2_point, g1_point)


def keygen():
    """DERE.KeyGen(pp) -> (sk, pk) for one client. sk = (alpha, beta), pk = g2^alpha."""
    alpha = _rand_scalar()
    beta = _rand_scalar()
    pk = multiply(G2, alpha)
    return (alpha, beta), pk


def enc(m, sk):
    """DERE.Enc(m, sk) -> ct = (c0, c1)."""
    alpha, beta = sk
    r = _rand_scalar()
    h_m = _hash_to_g1(m)
    inner = multiply(G1, (r * beta) % Zp)
    base = add(inner, h_m)  # g1^(r*beta) * H(m)
    c0 = multiply(base, alpha)
    c1 = multiply(G1, r)
    return (c0, c1)


def tokgen(sk_u, pk_v):
    """DERE.TokGen(sk^(u), pk^(v)) -> tok_{v->u} = (t0, t1).
    t1 uses the corrected product exponent alpha(u)*beta(u) (see module docstring).
    """
    alpha_u, beta_u = sk_u
    t0 = pk_v
    t1 = multiply(pk_v, (alpha_u * beta_u) % Zp)
    return (t0, t1)


def test(ct_u, ct_v, tok_v_to_u, tok_u_to_v):
    """DERE.Test(ct^(u), ct^(v), tok_{v->u}, tok_{u->v}) -> True iff the two
    encrypted messages are equal. Needs a token from EACH side (bidirectional
    — this cost is exactly what UNIQUE's one-way token exists to avoid, see
    crypto/unique_core.py)."""
    c0_u, c1_u = ct_u
    c0_v, c1_v = ct_v
    t0_vu, t1_vu = tok_v_to_u
    t0_uv, t1_uv = tok_u_to_v

    d0 = _e(c0_u, t0_vu) * _e(c1_u, t1_vu).inv()
    d1 = _e(c0_v, t0_uv) * _e(c1_v, t1_uv).inv()
    return d0 == d1
