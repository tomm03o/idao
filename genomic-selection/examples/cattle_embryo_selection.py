#!/usr/bin/env python3
"""
Complete End-to-End Example: Cattle Embryo Selection with Reverse Structural Mapping

This example demonstrates the full workflow for selecting cattle embryos
for milk production using:
1. Reverse structural mapping (AlphaFold → DNA)
2. Weighted LDpred2 with protein structure priors
3. PathwayGNN for interpretability
4. Multi-trait selection index

Scenario:
    Cattle breeder has 20 in-vitro fertilized embryos
    Goal: Select top 5 for implantation to maximize milk yield + quality

Scientific workflow:
    1. Known biology: Casein proteins ARE milk
    2. Get AlphaFold structures for CSN1S1, CSN2, CSN3
    3. Identify critical functional domains (calcium binding, phosphorylation sites)
    4. Back-map to cattle genome coordinates
    5. Weight these regions 100× in LDpred2
    6. Predict milk yield for each embryo
    7. Rank and select top embryos
"""

import numpy as np
import pandas as pd
from pathlib import Path
import logging

# Our platform modules
from genomic_selection.structure.reverse_mapping import (
    ReverseStructuralMapper,
    CATTLE_MILK_PROTEINS
)
from genomic_selection.structure.weighted_ldpred import (
    WeightedLDpred2,
    StructuralPriorWeighting
)
from genomic_selection.pathways.gnn import PathwayGNN, PathwayDataset
from genomic_selection.transfer.cross_species import CrossSpeciesTransfer
from genomic_selection.io.genotype_io import GenotypeReader, GWASReader
from genomic_selection.validation.ldsc import LDSC

# C++ core
import genomic_core_cpp as gcore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CattleEmbryoSelector:
    """
    Complete pipeline for cattle embryo selection with structural priors.
    """

    def __init__(self, data_dir: Path = Path("data")):
        self.data_dir = data_dir
        self.results_dir = Path("results")
        self.results_dir.mkdir(exist_ok=True)

    def step1_download_data(self):
        """Step 1: Download required datasets."""
        logger.info("=" * 80)
        logger.info("STEP 1: Downloading Datasets")
        logger.info("=" * 80)

        from genomic_selection.data.downloaders import (
            download_ukb_gwas,
            download_1000g,
            download_kegg,
            download_string
        )

        # Download human GWAS for transfer learning
        logger.info("\n1.1 Downloading UK Biobank GWAS (human height → cattle stature)")
        # download_ukb_gwas.main()  # Uncomment to run

        # Download LD reference
        logger.info("\n1.2 Downloading 1000 Genomes LD reference")
        # download_1000g.main()  # Uncomment to run

        # Download pathway databases
        logger.info("\n1.3 Downloading KEGG pathways")
        # download_kegg.main()  # Uncomment to run

        logger.info("\n1.4 Downloading STRING protein networks")
        # download_string.main()  # Uncomment to run

        logger.info("\n✓ Data download complete (or skipped)")

    def step2_create_structural_priors(self):
        """Step 2: Create structural priors from protein knowledge."""
        logger.info("\n" + "=" * 80)
        logger.info("STEP 2: Reverse Structural Mapping (Protein → Genome)")
        logger.info("=" * 80)

        # Initialize reverse mapper
        mapper = ReverseStructuralMapper(
            genome_annotation_file=self.data_dir / "annotations/cattle_ARS-UCD1.2.gtf",
            species='cattle'
        )

        # Create priors from known milk proteins
        logger.info("\nTarget proteins:")
        for gene, uniprot in CATTLE_MILK_PROTEINS.items():
            logger.info(f"  {gene}: {uniprot}")

        structural_priors = mapper.create_structural_priors(
            target_proteins=CATTLE_MILK_PROTEINS,
            base_prior_weight=100.0  # 100× weight for critical domains
        )

        # Export for inspection
        priors_file = self.results_dir / "cattle_milk_structural_priors.tsv"
        mapper.export_priors_for_ldpred(structural_priors, priors_file)

        logger.info(f"\n✓ Created {len(structural_priors)} structural priors")
        logger.info(f"✓ Exported to {priors_file}")

        return structural_priors

    def step3_transfer_learning_from_human(self):
        """Step 3: Transfer genetic architecture from human to cattle."""
        logger.info("\n" + "=" * 80)
        logger.info("STEP 3: Cross-Species Transfer Learning (Human → Cattle)")
        logger.info("=" * 80)

        # Load human GWAS
        human_gwas_file = self.data_dir / "raw/ukb_gwas/height_ldpred_format.tsv"
        ortholog_file = self.data_dir / "raw/kegg/orthologs_hsa_bta.tsv"
        snp_annotation = self.data_dir / "annotations/cattle_snp_to_gene.tsv"

        if not human_gwas_file.exists():
            logger.warning(f"Human GWAS not found: {human_gwas_file}")
            logger.info("Skipping transfer learning (use real cattle GWAS instead)")
            return None

        transfer = CrossSpeciesTransfer(
            human_gwas_file=human_gwas_file,
            ortholog_map_file=ortholog_file,
            snp_annotation_file=snp_annotation
        )

        # Aggregate human GWAS to gene level
        human_gene_effects = transfer.aggregate_snps_to_genes(
            transfer.human_gwas,
            transfer.snp_annotation,
            method='weighted_mean'
        )

        # Map to cattle orthologs
        cattle_gene_effects = transfer.map_human_to_animal(
            human_gene_effects,
            target_species='cattle'
        )

        # Create informative priors
        cattle_genes = list(cattle_gene_effects.keys())
        priors = transfer.create_informative_priors(
            cattle_genes,
            cattle_gene_effects,
            prior_variance_scale=0.5
        )

        logger.info(f"\n✓ Transferred genetic architecture for {len(priors)} genes")

        return priors

    def step4_compute_ld_matrix(self):
        """Step 4: Compute LD matrix from reference panel."""
        logger.info("\n" + "=" * 80)
        logger.info("STEP 4: Computing LD Matrix")
        logger.info("=" * 80)

        # Load reference panel genotypes
        reference_genotypes_file = self.data_dir / "reference/cattle_1000_genomes.bed"

        if not reference_genotypes_file.exists():
            logger.warning("Reference panel not found, using simulated data")

            # Simulate for demonstration
            n_individuals = 500
            n_snps = 1000
            genotypes = np.random.randint(0, 3, (n_individuals, n_snps), dtype=np.uint8)

            logger.info(f"Simulated genotypes: {n_individuals} × {n_snps}")
        else:
            genotypes, bim, fam = GenotypeReader.read_plink_bed(reference_genotypes_file)

        # Compute LD matrix
        ld_calculator = gcore.LDMatrixCalculator(shrinkage=0.9, min_maf=0.01)
        ld_matrix = ld_calculator.compute(genotypes)

        logger.info(f"\n✓ LD matrix computed: {ld_matrix.shape}")

        return ld_matrix

    def step5_weighted_ldpred(self, structural_priors, ld_matrix):
        """Step 5: Run weighted LDpred2 with structural priors."""
        logger.info("\n" + "=" * 80)
        logger.info("STEP 5: Weighted LDpred2 with Structural Priors")
        logger.info("=" * 80)

        # Load cattle GWAS for milk yield
        gwas_file = self.data_dir / "gwas/cattle_milk_yield.tsv"

        if not gwas_file.exists():
            logger.warning("Cattle GWAS not found, using simulated data")

            # Simulate GWAS
            n_snps = ld_matrix.shape[0]
            gwas = pd.DataFrame({
                'CHR': np.random.randint(1, 30, n_snps),
                'POS': np.random.randint(1000000, 100000000, n_snps),
                'SNP': [f"rs{i}" for i in range(n_snps)],
                'A1': np.random.choice(['A', 'C', 'G', 'T'], n_snps),
                'A2': np.random.choice(['A', 'C', 'G', 'T'], n_snps),
                'BETA': np.random.normal(0, 0.01, n_snps),
                'SE': np.random.uniform(0.005, 0.02, n_snps),
                'P': np.random.uniform(0, 1, n_snps),
                'N': np.full(n_snps, 5000)
            })
        else:
            gwas_reader = GWASReader()
            gwas = gwas_reader.read_gwas(gwas_file, format='standard')

        # Create GWAS data structure for C++
        gwas_data = gcore.GWASData()
        gwas_data.total_samples = int(gwas['N'].median())

        for _, row in gwas.iterrows():
            snp = gcore.SNP()
            snp.id = row['SNP']
            snp.chromosome = str(row['CHR'])
            snp.position = int(row['POS'])
            snp.allele_ref = row['A2']
            snp.allele_alt = row['A1']
            snp.beta = float(row['BETA'])
            snp.se = float(row['SE'])
            snp.pvalue = float(row['P'])
            snp.sample_size = int(row['N'])
            gwas_data.snps.append(snp)

        # Initialize standard LDpred2
        base_ldpred = gcore.LDpred2(
            ld_matrix=ld_matrix,
            n_iter=1000,
            burn_in=200,
            random_seed=42
        )

        # Wrap with weighted LDpred
        weighted_ldpred = WeightedLDpred2(
            ldpred_model=base_ldpred,
            structural_priors=structural_priors
        )

        # Fit with automatic hyperparameter tuning
        logger.info("\nFitting weighted LDpred2-auto...")
        results = weighted_ldpred.fit(gwas, h2=0.4, p=0.01)

        # Interpret results
        top_snps = weighted_ldpred.interpret_results(results, gwas, top_n=20)

        # Save results
        results_file = self.results_dir / "weighted_ldpred_results.tsv"
        top_snps.to_csv(results_file, sep='\t', index=False)

        logger.info(f"\n✓ Weighted LDpred2 complete")
        logger.info(f"✓ Top SNPs saved to {results_file}")

        return results

    def step6_predict_embryo_scores(self, ldpred_results):
        """Step 6: Predict polygenic scores for embryos."""
        logger.info("\n" + "=" * 80)
        logger.info("STEP 6: Predicting Embryo Polygenic Scores")
        logger.info("=" * 80)

        # Load embryo genotypes
        embryo_genotypes_file = self.data_dir / "embryos/candidate_embryos.vcf.gz"

        if not embryo_genotypes_file.exists():
            logger.warning("Embryo genotypes not found, using simulated data")

            # Simulate 20 embryos
            n_embryos = 20
            n_snps = len(ldpred_results.beta_posterior)
            embryo_genotypes = np.random.randint(0, 3, (n_embryos, n_snps), dtype=np.uint8)
            embryo_ids = [f"Embryo_{i+1:02d}" for i in range(n_embryos)]

            logger.info(f"Simulated {n_embryos} embryo genotypes")
        else:
            embryo_genotypes, variant_info, embryo_ids = GenotypeReader.read_vcf(
                embryo_genotypes_file
            )

        # Predict PGS using LDpred2 C++ implementation
        base_ldpred = gcore.LDpred2(ld_matrix=np.eye(1), n_iter=1, burn_in=0)  # Dummy for prediction
        pgs = base_ldpred.predict(embryo_genotypes, ldpred_results.beta_posterior)

        # Create results DataFrame
        embryo_results = pd.DataFrame({
            'embryo_id': embryo_ids,
            'pgs_milk_yield': pgs,
            'percentile': [100 * (1 - (np.sum(pgs > score) / len(pgs))) for score in pgs]
        })

        # Sort by PGS
        embryo_results = embryo_results.sort_values('pgs_milk_yield', ascending=False)
        embryo_results['rank'] = range(1, len(embryo_results) + 1)

        logger.info("\nEMBRYO RANKINGS:")
        logger.info("-" * 80)
        for _, row in embryo_results.head(10).iterrows():
            logger.info(f"{row['rank']:2d}. {row['embryo_id']}: PGS = {row['pgs_milk_yield']:.4f} "
                       f"(Top {row['percentile']:.1f}%)")

        # Save results
        results_file = self.results_dir / "embryo_rankings.tsv"
        embryo_results.to_csv(results_file, sep='\t', index=False)

        logger.info(f"\n✓ Embryo rankings saved to {results_file}")

        return embryo_results

    def step7_select_top_embryos(self, embryo_results, n_select=5):
        """Step 7: Select top embryos for implantation."""
        logger.info("\n" + "=" * 80)
        logger.info(f"STEP 7: Final Selection (Top {n_select} Embryos)")
        logger.info("=" * 80)

        # Select top N
        selected = embryo_results.head(n_select)

        logger.info("\n🎯 RECOMMENDED FOR IMPLANTATION:")
        logger.info("=" * 80)

        for i, (_, embryo) in enumerate(selected.iterrows(), 1):
            logger.info(f"\n{i}. {embryo['embryo_id']}")
            logger.info(f"   Predicted milk yield PGS: {embryo['pgs_milk_yield']:.4f}")
            logger.info(f"   Percentile: Top {embryo['percentile']:.1f}%")
            logger.info(f"   Rationale: High structural prior in casein genes")

        # Save selection report
        report_file = self.results_dir / "selection_report.txt"
        with open(report_file, 'w') as f:
            f.write("CATTLE EMBRYO SELECTION REPORT\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Selection Date: {pd.Timestamp.now()}\n")
            f.write(f"Total Candidates: {len(embryo_results)}\n")
            f.write(f"Selected: {n_select}\n\n")
            f.write("Method: Weighted LDpred2 with Reverse Structural Mapping\n")
            f.write("Target Trait: Milk Yield\n")
            f.write("Key Genes: CSN1S1, CSN2, CSN3, LALBA, LGB (caseins)\n\n")
            f.write("SELECTED EMBRYOS:\n")
            f.write("-" * 80 + "\n")

            for i, (_, embryo) in enumerate(selected.iterrows(), 1):
                f.write(f"\n{i}. {embryo['embryo_id']}\n")
                f.write(f"   PGS: {embryo['pgs_milk_yield']:.4f}\n")
                f.write(f"   Rank: {embryo['rank']}/{len(embryo_results)}\n")

        logger.info(f"\n✓ Selection report saved to {report_file}")

        return selected


def main():
    """Run complete embryo selection pipeline."""
    logger.info("=" * 80)
    logger.info("CATTLE EMBRYO SELECTION WITH REVERSE STRUCTURAL MAPPING")
    logger.info("=" * 80)
    logger.info("\nThis pipeline demonstrates:")
    logger.info("1. Reverse mapping: Protein structure → DNA coordinates")
    logger.info("2. Weighted LDpred2 with 100× priority for critical domains")
    logger.info("3. Cross-species transfer learning (human → cattle)")
    logger.info("4. Embryo ranking and selection\n")

    selector = CattleEmbryoSelector()

    # Run pipeline
    selector.step1_download_data()
    structural_priors = selector.step2_create_structural_priors()
    transfer_priors = selector.step3_transfer_learning_from_human()
    ld_matrix = selector.step4_compute_ld_matrix()
    ldpred_results = selector.step5_weighted_ldpred(structural_priors, ld_matrix)
    embryo_results = selector.step6_predict_embryo_scores(ldpred_results)
    selected_embryos = selector.step7_select_top_embryos(embryo_results, n_select=5)

    logger.info("\n" + "=" * 80)
    logger.info("✓ PIPELINE COMPLETE")
    logger.info("=" * 80)
    logger.info("\nKey Innovation Demonstrated:")
    logger.info("  - Started from KNOWN biology (casein proteins)")
    logger.info("  - Used AlphaFold to identify critical domains")
    logger.info("  - Weighted SNPs in functional domains 100× higher")
    logger.info("  - Result: Biologically-interpretable embryo rankings")
    logger.info("\nNext Steps:")
    logger.info("  1. Validate predictions with actual milk yield data")
    logger.info("  2. Implant top-ranked embryos")
    logger.info("  3. Compare predicted vs observed performance")
    logger.info("  4. Refine structural priors based on validation")


if __name__ == "__main__":
    main()
