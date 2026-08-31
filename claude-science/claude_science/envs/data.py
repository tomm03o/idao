"""Small curated data used by environments: real approved-drug SMILES and a
reference gene fragment. Kept intentionally tiny and public-domain (canonical
textbook structures) so the package stays self-contained.
"""

from __future__ import annotations

# (name, SMILES) -- canonical structures of well-known small-molecule drugs.
DRUGS = [
    ("aspirin", "CC(=O)Oc1ccccc1C(=O)O"),
    ("ibuprofen", "CC(C)Cc1ccc(cc1)C(C)C(=O)O"),
    ("paracetamol", "CC(=O)Nc1ccc(O)cc1"),
    ("caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"),
    ("naproxen", "COc1ccc2cc(ccc2c1)C(C)C(=O)O"),
    ("diclofenac", "O=C(O)Cc1ccccc1Nc1c(Cl)cccc1Cl"),
    ("ketoprofen", "CC(C(=O)O)c1cccc(c1)C(=O)c1ccccc1"),
    ("celecoxib", "Cc1ccc(cc1)-c1cc(C(F)(F)F)nn1-c1ccc(cc1)S(N)(=O)=O"),
    ("atorvastatin", "CC(C)c1c(C(=O)Nc2ccccc2)c(-c2ccccc2)c(-c2ccc(F)cc2)n1CCC(O)CC(O)CC(=O)O"),
    ("metformin", "CN(C)C(=N)N=C(N)N"),
    ("gefitinib", "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1"),
    ("imatinib", "Cc1ccc(cc1Nc1nccc(n1)-c1cccnc1)NC(=O)c1ccc(CN2CCN(C)CC2)cc1"),
    ("sildenafil", "CCCc1nn(C)c2c1nc([nH]c2=O)-c1cc(ccc1OCC)S(=O)(=O)N1CCN(C)CC1"),
    ("warfarin", "CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O"),
    ("fluoxetine", "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1"),
    ("diphenhydramine", "CN(C)CCOC(c1ccccc1)c1ccccc1"),
    ("propranolol", "CC(C)NCC(O)COc1cccc2ccccc12"),
    ("amoxicillin", "CC1(C)SC2C(NC(=O)C(N)c3ccc(O)cc3)C(=O)N2C1C(=O)O"),
    ("ciprofloxacin", "OC(=O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O"),
    ("loratadine", "CCOC(=O)N1CCC(=C2c3ccc(Cl)cc3CCc3cccnc23)CC1"),
    ("omeprazole", "COc1ccc2[nH]c(S(=O)Cc3ncc(C)c(OC)c3C)nc2c1"),
    ("simvastatin", "CCC(C)(C)C(=O)OC1CC(C)C=C2C=CC(C)C(CCC3CC(O)CC(=O)O3)C12"),
    ("losartan", "CCCCc1nc(Cl)c(CO)n1Cc1ccc(cc1)-c1ccccc1-c1nnn[nH]1"),
    ("nicotine", "CN1CCCC1c1cccnc1"),
    ("morphine", "CN1CCC23C=CC(O)C4Oc5c(O)ccc(c5C24)CC1C3"),
]

# a handful of non-drug-like / problematic decoys (alerts, MW, logP outliers)
DECOYS = [
    ("michael_decoy", "C=CC(=O)c1ccccc1"),
    ("quinone_decoy", "O=C1C=CC(=O)C=C1"),
    ("greasy_decoy", "CCCCCCCCCCCCCCCCCCCC"),
    ("nitro_decoy", "O=[N+]([O-])c1ccccc1"),
]

# reference coding sequence (fragment of a kinase-like ORF, ATG..stop) used by
# the variant-calling environment. Public synthetic sequence.
REF_CDS = (
    "ATGGCAGAAGATCCTGAAGTGCTGAAGCGTATTGGCGATTTTGGCCTGGCAACCGAAAAA"
    "AGCCGTTGGAGCGGCAGCCATCAGTTTGAACAGCTGAGCGGCAGCATTCTGTGGATGGCA"
    "CCGGAAGTGATTCGTATGCAGGATAACAACCCGTTTAGCTTTCAGAGCGATGTGTATAGC"
    "TATGGCATTGTGCTGTATGAACTGATGACCGGCTAA"
)
