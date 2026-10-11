"""Analytic complementary coefficients for source-only SUP unit tests.

This quadratic fixture exercises the solver contract and A/B symmetry. It is
not a replacement for the owned executable's table, and makes no equality claim
about game coefficients. Corpus equality audits remain separate private data.
"""
import numpy as np


def complementary_coefficients():
    t = np.arange(16, dtype=float) / 16
    return np.stack(((1-t)**2, t**2, 2*t*(1-t)), axis=1)
