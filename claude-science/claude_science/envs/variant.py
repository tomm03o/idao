"""Variant-calling environment (real sequence alignment + translation).

Given a reference coding sequence and a mutated variant, the agent must call the
resulting single amino-acid substitution in HGVS-like protein notation (e.g.
``p.E12K``). It has real tools: pairwise alignment, translation, reverse
complement. Probes bioinformatics reasoning over sequence data.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Environment
from .data import REF_CDS
from ..science import seq

_AA3 = {
    "A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "E": "Glu",
    "Q": "Gln", "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys",
    "M": "Met", "F": "Phe", "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp",
    "Y": "Tyr", "V": "Val", "*": "Ter",
}


class VariantEnv(Environment):
    key = "variant"
    title = "Variant calling: identify a coding mutation"
    capability = "bioinformatics"

    def _build(self) -> None:
        r = self.rng
        self.ref_cds = REF_CDS
        self.ref_protein = seq.translate(REF_CDS).rstrip("*")
        # choose a codon to mutate to a different amino acid (missense)
        n_codons = len(self.ref_protein)
        for _ in range(200):
            pos = r.randrange(n_codons)
            codon_start = pos * 3
            orig_codon = REF_CDS[codon_start:codon_start + 3]
            new_codon = self._random_missense(orig_codon, r)
            if new_codon:
                break
        self.var_pos = pos + 1  # 1-based protein position
        self.ref_aa = self.ref_protein[pos]
        self.var_aa = seq.CODON_TABLE[new_codon]
        self.variant_cds = (
            REF_CDS[:codon_start] + new_codon + REF_CDS[codon_start + 3:]
        )
        self.answer = f"p.{self.ref_aa}{self.var_pos}{self.var_aa}"
        self._register_domain_tools()

    @staticmethod
    def _random_missense(codon: str, r) -> str | None:
        orig_aa = seq.CODON_TABLE.get(codon)
        bases = "ACGT"
        options = []
        for i in range(3):
            for b in bases:
                if b == codon[i]:
                    continue
                cand = codon[:i] + b + codon[i + 1:]
                aa = seq.CODON_TABLE.get(cand)
                if aa and aa != "*" and aa != orig_aa:
                    options.append(cand)
        return r.choice(options) if options else None

    def _register_domain_tools(self) -> None:
        def align(seq1: str, seq2: str) -> Dict[str, Any]:
            self._record("align", None)
            return seq.needleman_wunsch(seq1, seq2)

        def translate(dna: str) -> Dict[str, Any]:
            self._record("translate", None)
            return {"protein": seq.translate(dna)}

        self._registry.add(
            name="align_sequences",
            description="Global (Needleman-Wunsch) alignment of two sequences.",
            parameters={
                "type": "object",
                "properties": {"seq1": {"type": "string"}, "seq2": {"type": "string"}},
                "required": ["seq1", "seq2"],
            },
            handler=align,
        )
        self._registry.add(
            name="translate",
            description="Translate a DNA coding sequence to protein (1-letter).",
            parameters={
                "type": "object",
                "properties": {"dna": {"type": "string"}},
                "required": ["dna"],
            },
            handler=translate,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "variant": {
                    "type": "string",
                    "description": "Protein change in HGVS-like form, e.g. p.E12K.",
                }
            },
            "required": ["variant"],
        }

    def task_prompt(self) -> str:
        return (
            "A reference coding sequence and a mutated variant are given. Call the "
            "resulting single amino-acid substitution in HGVS-like protein "
            "notation, e.g. `p.E12K` (1-based protein position). Use `translate` "
            "and `align_sequences`, then `submit`.\n\n"
            f"Reference CDS:\n{self.ref_cds}\n\nVariant CDS:\n{self.variant_cds}"
        )

    def score(self, payload: Dict[str, Any]) -> float:
        got = str(payload.get("variant", "")).strip().replace(" ", "")
        norm = got.lower().lstrip("p.").replace("(", "").replace(")", "")
        target = self.answer.lower().lstrip("p.")
        # accept 1- or 3-letter codes and optional 'p.' prefix
        three = f"{_AA3[self.ref_aa]}{self.var_pos}{_AA3[self.var_aa]}".lower()
        return 1.0 if norm in {target, three} else 0.0

    def reference_policy(self) -> List[Dict[str, Any]]:
        return [
            {"tool": "translate", "args": {"dna": self.ref_cds}},
            {"tool": "translate", "args": {"dna": self.variant_cds}},
            {"tool": "submit", "args": {"variant": self.answer}},
        ]
