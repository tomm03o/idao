"""Live connectors to public biological & chemical databases.

* :mod:`pubchem` -- compounds & properties (NCBI PUG-REST)
* :mod:`chembl`  -- bioactivities, drugs, QSAR data (EMBL-EBI)
* :mod:`uniprot` -- protein sequence/annotation + RCSB PDB structures

All are cached on disk (see :mod:`claude_science.data_sources.http`) so an agent
can query them repeatedly for free and reproduce runs offline. They are also
exposed to agents as harness tools via
:func:`claude_science.data_sources.tools.database_tools`.
"""

from . import chembl, pubchem, uniprot, web
from .tools import database_tools

__all__ = ["chembl", "pubchem", "uniprot", "web", "database_tools"]
