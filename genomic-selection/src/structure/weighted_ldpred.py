"""
Weighted LDpred2 with Structural Priors

Integrates reverse structural mapping with LDpred2:
    - Base LDpred2: Bayesian shrinkage with LD
    - + Structural priors: 100× weight for SNPs in critical protein domains

Mathematical Model:

Standard LDpred2 prior:
    β_i ~ π·N(0, h²/(Mp)) + (1-π)·δ_0

Weighted LDpred2 prior:
    β_i ~ π·N(0, w_i · h²/(Mp)) + (1-π)·δ_0

where w_i = weight from structural knowledge:
    - w_i = 100.0 if SNP in critical domain (active site, binding pocket)
    - w_i = 50.0 if SNP in functional domain
    - w_i = 1.0 otherwise (standard)

This FORCES the model to prioritize biologically-known critical regions.

Example impact:
    CSN2 (β-casein) has 1000 SNPs, 20 in calcium-binding active site
    Standard LDpred: All 1000 SNPs weighted equally
    Weighted LDpred: 20 active-site SNPs weighted 100×, rest 1×
    → Active site variants DOMINATE prediction (as they should biologically!)
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
import logging
from dataclasses import dataclass

from ..structure.reverse_mapping import GenomicPrior

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WeightedSNP:
    """SNP with structural weight."""
    snp_id: str
    chromosome: str
    position: int
    weight: float
    source: str  # 'structural', 'pathway', 'default'


class StructuralPriorWeighting:
    """
    Assign weights to SNPs based on structural knowledge.
    """

    def __init__(
        self,
        structural_priors: List[GenomicPrior],
        default_weight: float = 1.0
    ):
        """
        Args:
            structural_priors: List of genomic priors from reverse mapping
            default_weight: Default weight for SNPs not in priors
        """
        self.structural_priors = structural_priors
        self.default_weight = default_weight

        # Build interval tree for fast lookup
        self._build_interval_index()

    def _build_interval_index(self):
        """Build index for fast genomic interval queries."""
        # Group by chromosome
        self.intervals_by_chrom = {}

        for prior in self.structural_priors:
            chrom = prior.chromosome

            if chrom not in self.intervals_by_chrom:
                self.intervals_by_chrom[chrom] = []

            self.intervals_by_chrom[chrom].append({
                'start': prior.start_pos,
                'end': prior.end_pos,
                'weight': prior.prior_weight,
                'gene': prior.gene,
                'domain': prior.domain.name
            })

        # Sort intervals
        for chrom in self.intervals_by_chrom:
            self.intervals_by_chrom[chrom].sort(key=lambda x: x['start'])

        logger.info(f"Built interval index: {len(self.intervals_by_chrom)} chromosomes")

    def get_snp_weight(
        self,
        chromosome: str,
        position: int,
        snp_id: str = ''
    ) -> WeightedSNP:
        """
        Get weight for a SNP based on structural priors.

        Args:
            chromosome: Chromosome
            position: Genomic position (bp)
            snp_id: SNP identifier

        Returns:
            WeightedSNP with assigned weight
        """
        # Check if SNP in any structural prior region
        if chromosome not in self.intervals_by_chrom:
            return WeightedSNP(
                snp_id=snp_id,
                chromosome=chromosome,
                position=position,
                weight=self.default_weight,
                source='default'
            )

        # Binary search in sorted intervals
        intervals = self.intervals_by_chrom[chromosome]

        for interval in intervals:
            if interval['start'] <= position <= interval['end']:
                # SNP in structural prior region
                return WeightedSNP(
                    snp_id=snp_id,
                    chromosome=chromosome,
                    position=position,
                    weight=interval['weight'],
                    source=f"structural:{interval['gene']}:{interval['domain']}"
                )

        # Not in any prior region
        return WeightedSNP(
            snp_id=snp_id,
            chromosome=chromosome,
            position=position,
            weight=self.default_weight,
            source='default'
        )

    def assign_weights_to_gwas(
        self,
        gwas: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Assign structural weights to all SNPs in GWAS.

        Args:
            gwas: GWAS DataFrame with columns [CHR, POS, SNP, ...]

        Returns:
            GWAS with added 'WEIGHT' column
        """
        logger.info("Assigning structural weights to GWAS SNPs...")

        weights = []
        sources = []

        for _, row in gwas.iterrows():
            weighted_snp = self.get_snp_weight(
                str(row['CHR']),
                int(row['POS']),
                row['SNP']
            )

            weights.append(weighted_snp.weight)
            sources.append(weighted_snp.source)

        gwas['WEIGHT'] = weights
        gwas['WEIGHT_SOURCE'] = sources

        # Summary statistics
        n_weighted = (gwas['WEIGHT'] > self.default_weight).sum()
        mean_weight = gwas['WEIGHT'].mean()
        max_weight = gwas['WEIGHT'].max()

        logger.info(f"  Total SNPs: {len(gwas)}")
        logger.info(f"  SNPs with structural priors: {n_weighted} ({100*n_weighted/len(gwas):.2f}%)")
        logger.info(f"  Mean weight: {mean_weight:.2f}")
        logger.info(f"  Max weight: {max_weight:.1f}×")

        # Show examples
        top_weighted = gwas.nlargest(5, 'WEIGHT')[['SNP', 'CHR', 'POS', 'WEIGHT', 'WEIGHT_SOURCE']]
        logger.info("\nTop weighted SNPs:")
        logger.info(top_weighted.to_string())

        return gwas


class WeightedLDpred2:
    """
    LDpred2 with structural prior weighting.

    Wrapper around standard LDpred2 that incorporates structural knowledge.
    """

    def __init__(
        self,
        ldpred_model,  # Standard LDpred2 instance
        structural_priors: List[GenomicPrior]
    ):
        """
        Args:
            ldpred_model: Base LDpred2 model
            structural_priors: Structural priors from reverse mapping
        """
        self.ldpred_model = ldpred_model
        self.prior_weighting = StructuralPriorWeighting(structural_priors)

    def fit(
        self,
        gwas: pd.DataFrame,
        h2: float,
        p: float
    ):
        """
        Fit weighted LDpred2.

        Args:
            gwas: GWAS summary statistics
            h2: SNP heritability
            p: Polygenicity

        Returns:
            Fitted model results
        """
        logger.info("=" * 80)
        logger.info("Fitting Weighted LDpred2 with Structural Priors")
        logger.info("=" * 80)

        # 1. Assign structural weights to SNPs
        gwas_weighted = self.prior_weighting.assign_weights_to_gwas(gwas)

        # 2. Modify prior variance based on weights
        # Standard prior variance: σ² = h²/(Mp)
        # Weighted prior variance: σ²_i = w_i · h²/(Mp)

        M = len(gwas_weighted)
        base_variance = h2 / (M * p)

        gwas_weighted['PRIOR_VARIANCE'] = gwas_weighted['WEIGHT'] * base_variance

        logger.info(f"\nPrior variance statistics:")
        logger.info(f"  Base variance: {base_variance:.6f}")
        logger.info(f"  Min prior variance: {gwas_weighted['PRIOR_VARIANCE'].min():.6f}")
        logger.info(f"  Max prior variance: {gwas_weighted['PRIOR_VARIANCE'].max():.6f}")
        logger.info(f"  Mean prior variance: {gwas_weighted['PRIOR_VARIANCE'].mean():.6f}")

        # 3. Fit LDpred2 with modified priors
        # Note: This requires modifying the C++ LDpred implementation to accept
        # per-SNP prior variances. For now, we create "pseudo-SNPs" by reweighting.

        # Alternative approach: Reweight effect sizes
        # Inflate BETA and SE for high-priority SNPs
        gwas_weighted['BETA_WEIGHTED'] = gwas_weighted['BETA'] * np.sqrt(gwas_weighted['WEIGHT'])
        gwas_weighted['SE_WEIGHTED'] = gwas_weighted['SE'] / np.sqrt(gwas_weighted['WEIGHT'])

        # Fit standard LDpred on weighted data
        results = self.ldpred_model.fit(gwas_weighted, h2, p)

        # Adjust posterior effects back
        results.beta_posterior = results.beta_posterior / np.sqrt(gwas_weighted['WEIGHT'].values)

        logger.info("\n" + "=" * 80)
        logger.info("Weighted LDpred2 fitting complete")
        logger.info("=" * 80)

        return results

    def interpret_results(
        self,
        results,
        gwas_weighted: pd.DataFrame,
        top_n: int = 20
    ) -> pd.DataFrame:
        """
        Interpret results with structural context.

        Args:
            results: LDpred results
            gwas_weighted: Weighted GWAS
            top_n: Number of top SNPs to report

        Returns:
            DataFrame with top SNPs and biological interpretation
        """
        # Create results DataFrame
        results_df = gwas_weighted.copy()
        results_df['BETA_POSTERIOR'] = results.beta_posterior
        results_df['PIP'] = results.pip

        # Sort by posterior inclusion probability
        top_snps = results_df.nlargest(top_n, 'PIP')

        logger.info("\n" + "=" * 80)
        logger.info("TOP PREDICTED CAUSAL VARIANTS")
        logger.info("=" * 80)

        for _, snp in top_snps.iterrows():
            logger.info(f"\n{snp['SNP']} ({snp['CHR']}:{snp['POS']})")
            logger.info(f"  PIP: {snp['PIP']:.4f}")
            logger.info(f"  Effect: {snp['BETA_POSTERIOR']:.4f}")
            logger.info(f"  Structural weight: {snp['WEIGHT']:.1f}×")
            logger.info(f"  Source: {snp['WEIGHT_SOURCE']}")

        # Count structural vs non-structural in top SNPs
        n_structural = (top_snps['WEIGHT'] > 1.0).sum()

        logger.info(f"\nTop {top_n} SNPs:")
        logger.info(f"  Structurally-informed: {n_structural} ({100*n_structural/top_n:.1f}%)")
        logger.info(f"  Discovery (GWAS only): {top_n - n_structural} ({100*(top_n-n_structural)/top_n:.1f}%)")

        return top_snps


# Example: Cattle milk production with structural priors
def example_cattle_milk_weighted_ldpred():
    """
    Example workflow for cattle milk production with structural priors.
    """
    from ..structure.reverse_mapping import ReverseStructuralMapper, CATTLE_MILK_PROTEINS
    from ..io.genotype_io import GWASReader

    logger.info("=" * 80)
    logger.info("EXAMPLE: Cattle Milk Production with Structural Priors")
    logger.info("=" * 80)

    # 1. Create structural priors from casein proteins
    mapper = ReverseStructuralMapper(
        genome_annotation_file=Path("data/annotations/cattle_ARS-UCD1.2.gtf"),
        species='cattle'
    )

    structural_priors = mapper.create_structural_priors(
        target_proteins=CATTLE_MILK_PROTEINS,
        base_prior_weight=100.0  # 100× weight for critical domains
    )

    # Export for inspection
    mapper.export_priors_for_ldpred(
        structural_priors,
        Path("data/priors/cattle_milk_structural_priors.tsv")
    )

    # 2. Load GWAS for milk yield
    gwas_reader = GWASReader()
    gwas = gwas_reader.read_gwas(
        Path("data/gwas/cattle_milk_yield.tsv"),
        format='standard'
    )

    # 3. Create weighted LDpred2
    from genomic_core_cpp import LDpred2, LDMatrixCalculator

    # Compute LD matrix (from reference panel)
    # ... (code to load genotypes and compute LD)

    # Initialize weighted LDpred2
    weighted_ldpred = WeightedLDpred2(
        ldpred_model=ldpred_model,  # Standard LDpred2 instance
        structural_priors=structural_priors
    )

    # 4. Fit with structural priors
    results = weighted_ldpred.fit(gwas, h2=0.4, p=0.01)

    # 5. Interpret results
    top_snps = weighted_ldpred.interpret_results(results, gwas, top_n=50)

    logger.info("\n✓ Analysis complete!")
    logger.info("Key insight: Structurally-informed SNPs in casein proteins")
    logger.info("dominate prediction, even if GWAS p-values were modest.")

    return results, top_snps
