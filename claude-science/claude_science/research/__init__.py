"""Research: novel algorithms formulated and empirically validated in-repo.

Currently:

* :mod:`adaptive_design` -- sequential D-optimal experimental design for IC50
  estimation, which beats fixed log-spaced sampling in the wide-range /
  small-budget screening regime. Reproduce with
  ``python -m claude_science.research.validate_adaptive_design``.
"""

from . import adaptive_design, molecular_bo, molecular_design

__all__ = ["adaptive_design", "molecular_bo", "molecular_design"]
