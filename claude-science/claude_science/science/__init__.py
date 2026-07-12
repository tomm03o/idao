"""Validated scientific computing layer.

These modules are the real engine under Claude Science's environments and are
usable directly (independently of the agent harness) as a scientific library:

* :mod:`claude_science.science.chem`   -- cheminformatics (RDKit)
* :mod:`claude_science.science.pk`     -- pharmacokinetics / dose-response (scipy)
* :mod:`claude_science.science.seq`    -- sequence bioinformatics (numpy)
* :mod:`claude_science.science.struct` -- 3D modelling / MMFF94 (RDKit)
* :mod:`claude_science.science.perception` -- multi-level molecule/sequence views
"""

from . import chem, pk, seq, struct, perception

__all__ = ["chem", "pk", "seq", "struct", "perception"]
