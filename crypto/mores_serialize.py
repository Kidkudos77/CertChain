"""
CertChain — JSON serialization for MORES/TIE key and ciphertext material
=============================================================================
py_ecc's G1/G2 points and Zp scalars aren't directly JSON-serializable
(field elements, and integers well beyond JS's safe-integer range), and the
HTTP sidecar (mores_service.py) needs to pass msk/qk/ctx/ty across an HTTP
boundary as JSON. This module is pure plumbing — it does not touch any of
the actual cryptographic computation in tie.py/mores_core.py, only encodes
and decodes the data structures they produce. Every large integer is
encoded as a decimal string (JSON numbers aren't safe for 255+ bit values).
"""
from py_ecc.fields import bls12_381_FQ as FQ
from py_ecc.fields import bls12_381_FQ2 as FQ2


def _ser_g1(point):
    x, y = point
    return [str(int(x.n)), str(int(y.n))]


def _deser_g1(data):
    x, y = data
    return (FQ(int(x)), FQ(int(y)))


def _ser_g2(point):
    x, y = point
    return [[str(int(x.coeffs[0])), str(int(x.coeffs[1]))], [str(int(y.coeffs[0])), str(int(y.coeffs[1]))]]


def _deser_g2(data):
    x, y = data
    x_re = FQ2([int(x[0]), int(x[1])])
    y_re = FQ2([int(y[0]), int(y[1])])
    return (x_re, y_re)


def ser_kL(kL):
    k1, k2, k3 = kL
    return {"k1": str(k1), "k2": str(k2), "k3": str(k3)}


def deser_kL(data):
    return (int(data["k1"]), int(data["k2"]), int(data["k3"]))


def ser_kR(kR):
    k1, rho1, rho2 = kR
    return {"k1": str(k1), "rho1": _ser_g2(rho1), "rho2": _ser_g2(rho2)}


def deser_kR(data):
    return (int(data["k1"]), _deser_g2(data["rho1"]), _deser_g2(data["rho2"]))


def ser_ctx(ctL):
    """Serialize a TIE.EncL / MORES.Enc output (all G1 points)."""
    L0, Ls, Ln1 = ctL
    return {"L0": _ser_g1(L0), "Ls": [_ser_g1(L) for L in Ls], "Ln1": _ser_g1(Ln1)}


def deser_ctx(data):
    return (_deser_g1(data["L0"]), [_deser_g1(L) for L in data["Ls"]], _deser_g1(data["Ln1"]))


def ser_ty(ctR):
    """Serialize a TIE.EncR / MORES.TGen output (all G2 points)."""
    R0, Rs, Rn1 = ctR
    return {"R0": _ser_g2(R0), "Rs": [_ser_g2(R) for R in Rs], "Rn1": _ser_g2(Rn1)}


def deser_ty(data):
    return (_deser_g2(data["R0"]), [_deser_g2(R) for R in data["Rs"]], _deser_g2(data["Rn1"]))
