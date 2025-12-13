"""
LD Score Regression (LDSC) for heritability estimation and validation.

LDSC is the gold standard for estimating SNP heritability from GWAS summary statistics.

Key equations:
    E[χ²] = N × h²/M × ℓ + 1

where:
    χ² = GWAS test statistics
    N = sample size
    h² = SNP heritability
    M = number of SNPs
    ℓ = LD score (sum of r² with other SNPs)

Reference: Bulik-Sullivan et al. (2015) Nature Genetics
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple, Dict, Optional
from scipy import stats
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LDSC:
    """LD Score Regression for heritability estimation."""

    def __init__(self, ld_scores_file: Optional[Path] = None):
        """
        Args:
            ld_scores_file: Precomputed LD scores (optional, can compute on-the-fly)
        """
        self.ld_scores = None
        if ld_scores_file:
            self.ld_scores = pd.read_csv(ld_scores_file, sep='\t')
            logger.info(f"Loaded LD scores: {len(self.ld_scores)} SNPs")

    def compute_ld_scores(
        self,
        genotypes: np.ndarray,
        variant_ids: list,
        window_size: int = 1000
    ) -> pd.DataFrame:
        """
        Compute LD scores from genotype data.

        LD score for SNP i: ℓ_i = Σ_j r²_ij

        Args:
            genotypes: Genotype matrix (n_samples × n_variants)
            variant_ids: Variant IDs
            window_size: Number of nearby SNPs to include (default: 1000)

        Returns:
            DataFrame with columns [SNP, LD_SCORE]
        """
        logger.info("Computing LD scores...")

        n_samples, n_variants = genotypes.shape

        # Standardize genotypes
        genotypes_std = (genotypes - genotypes.mean(axis=0)) / (genotypes.std(axis=0) + 1e-10)

        ld_scores = np.zeros(n_variants)

        for i in range(n_variants):
            if i % 1000 == 0:
                logger.info(f"  Processing SNP {i}/{n_variants}")

            # Define window
            start = max(0, i - window_size // 2)
            end = min(n_variants, i + window_size // 2)

            # Compute r² with SNPs in window
            g_i = genotypes_std[:, i]

            for j in range(start, end):
                if i == j:
                    continue

                g_j = genotypes_std[:, j]

                # Pearson correlation
                r = np.dot(g_i, g_j) / n_samples
                r_squared = r ** 2

                ld_scores[i] += r_squared

        df = pd.DataFrame({
            'SNP': variant_ids,
            'LD_SCORE': ld_scores
        })

        logger.info(f"  Mean LD score: {ld_scores.mean():.2f}")
        logger.info(f"  Median LD score: {np.median(ld_scores):.2f}")

        self.ld_scores = df

        return df

    def estimate_heritability(
        self,
        gwas: pd.DataFrame,
        ld_scores: Optional[pd.DataFrame] = None,
        n_blocks: int = 200
    ) -> Dict[str, float]:
        """
        Estimate SNP heritability using LD score regression.

        Regression model:
            χ² = α + β × ℓ + ε

        where β = N × h²/M

        Args:
            gwas: GWAS summary statistics (columns: SNP, BETA, SE, P, N)
            ld_scores: LD scores (optional, uses self.ld_scores if None)
            n_blocks: Number of blocks for jackknife standard error

        Returns:
            Dictionary with h2, h2_se, intercept, intercept_se
        """
        logger.info("Estimating heritability with LDSC...")

        if ld_scores is None:
            ld_scores = self.ld_scores

        if ld_scores is None:
            raise ValueError("LD scores not provided and not precomputed")

        # Merge GWAS with LD scores
        merged = gwas.merge(ld_scores, on='SNP', how='inner')

        logger.info(f"  Overlapping SNPs: {len(merged)}")

        # Compute chi-square statistics
        merged['Z'] = merged['BETA'] / merged['SE']
        merged['CHISQ'] = merged['Z'] ** 2

        # Filter out extreme chi-square values (likely errors)
        chisq_max = max(merged['CHISQ'].quantile(0.999), 80)
        merged = merged[merged['CHISQ'] < chisq_max]

        logger.info(f"  After filtering: {len(merged)} SNPs")

        # Extract variables for regression
        chisq = merged['CHISQ'].values
        ld_score = merged['LD_SCORE'].values
        n_samples = merged['N'].median()  # Use median sample size

        # Weighted least squares regression
        # Weight by LD score to account for heteroskedasticity
        weights = 1.0 / (ld_score + 1.0)

        # Add intercept
        X = np.column_stack([np.ones(len(ld_score)), ld_score])
        y = chisq

        # Weighted regression
        W = np.diag(weights)
        XtWX_inv = np.linalg.inv(X.T @ W @ X)
        beta_hat = XtWX_inv @ X.T @ W @ y

        intercept = beta_hat[0]
        slope = beta_hat[1]

        # Estimate heritability
        # slope = N × h² / M
        M = len(merged)
        h2 = slope * M / n_samples

        # Jackknife standard error
        h2_se = self._jackknife_se(
            X, y, weights, n_blocks, n_samples, M
        )

        # Intercept standard error
        residuals = y - X @ beta_hat
        sigma2 = np.sum(weights * residuals ** 2) / (len(y) - 2)
        intercept_se = np.sqrt(sigma2 * XtWX_inv[0, 0])

        # Constrain heritability to [0, 1]
        h2 = max(0.0, min(1.0, h2))

        results = {
            'h2': h2,
            'h2_se': h2_se,
            'intercept': intercept,
            'intercept_se': intercept_se,
            'n_snps': M,
            'n_samples': n_samples,
            'mean_chisq': chisq.mean()
        }

        logger.info("\nLDSC Results:")
        logger.info(f"  h² = {h2:.4f} (SE = {h2_se:.4f})")
        logger.info(f"  Intercept = {intercept:.4f} (SE = {intercept_se:.4f})")
        logger.info(f"  Mean χ² = {chisq.mean():.4f}")
        logger.info(f"  λ_GC (genomic inflation) = {chisq.median() / 0.455:.4f}")

        # Check for inflation
        if intercept > 1.1:
            logger.warning("⚠️  High intercept suggests population stratification or confounding")

        if chisq.mean() > 1.5 and intercept < 1.1:
            logger.info("✓ Polygenicity detected (mean χ² > 1 but intercept ≈ 1)")

        return results

    def _jackknife_se(
        self,
        X: np.ndarray,
        y: np.ndarray,
        weights: np.ndarray,
        n_blocks: int,
        n_samples: float,
        M: int
    ) -> float:
        """
        Compute jackknife standard error for heritability estimate.

        Args:
            X: Design matrix
            y: Response variable (chi-square)
            weights: Regression weights
            n_blocks: Number of jackknife blocks
            n_samples: GWAS sample size
            M: Number of SNPs

        Returns:
            Standard error of h²
        """
        n = len(y)
        block_size = n // n_blocks

        h2_pseudovalues = []

        for block in range(n_blocks):
            # Exclude block
            start = block * block_size
            end = start + block_size if block < n_blocks - 1 else n

            mask = np.ones(n, dtype=bool)
            mask[start:end] = False

            X_block = X[mask]
            y_block = y[mask]
            w_block = weights[mask]

            # Weighted regression on block
            W = np.diag(w_block)
            try:
                XtWX_inv = np.linalg.inv(X_block.T @ W @ X_block)
                beta_block = XtWX_inv @ X_block.T @ W @ y_block

                slope_block = beta_block[1]
                h2_block = slope_block * M / n_samples

                h2_pseudovalues.append(h2_block)
            except:
                continue

        # Jackknife standard error
        h2_se = np.std(h2_pseudovalues) * np.sqrt(n_blocks)

        return h2_se

    def genetic_correlation(
        self,
        gwas1: pd.DataFrame,
        gwas2: pd.DataFrame,
        ld_scores: Optional[pd.DataFrame] = None
    ) -> Dict[str, float]:
        """
        Estimate genetic correlation between two traits using LDSC.

        Useful for:
        - Multi-trait analysis
        - Pleiotropy detection
        - Cross-species validation

        Args:
            gwas1: GWAS for trait 1
            gwas2: GWAS for trait 2
            ld_scores: LD scores

        Returns:
            Dictionary with rg (genetic correlation), rg_se
        """
        logger.info("Estimating genetic correlation...")

        if ld_scores is None:
            ld_scores = self.ld_scores

        # Merge both GWAS with LD scores
        merged = gwas1.merge(gwas2, on='SNP', suffixes=('_1', '_2'))
        merged = merged.merge(ld_scores, on='SNP')

        logger.info(f"  Overlapping SNPs: {len(merged)}")

        # Compute product of Z-scores
        merged['Z1'] = merged['BETA_1'] / merged['SE_1']
        merged['Z2'] = merged['BETA_2'] / merged['SE_2']
        merged['Z_PROD'] = merged['Z1'] * merged['Z2']

        # Regression: E[Z1 × Z2] = sqrt(N1 × N2) × rg/M × ℓ
        ld_score = merged['LD_SCORE'].values
        z_prod = merged['Z_PROD'].values

        n1 = merged['N_1'].median()
        n2 = merged['N_2'].median()
        M = len(merged)

        # Weighted regression
        weights = 1.0 / (ld_score + 1.0)
        X = np.column_stack([np.ones(len(ld_score)), ld_score])

        W = np.diag(weights)
        XtWX_inv = np.linalg.inv(X.T @ W @ X)
        beta_hat = XtWX_inv @ X.T @ W @ z_prod

        slope = beta_hat[1]

        # Genetic correlation
        rg = slope * M / np.sqrt(n1 * n2)

        # Standard error (simplified)
        residuals = z_prod - X @ beta_hat
        sigma2 = np.sum(weights * residuals ** 2) / (len(z_prod) - 2)
        rg_se = np.sqrt(sigma2 * XtWX_inv[1, 1]) * M / np.sqrt(n1 * n2)

        # Constrain to [-1, 1]
        rg = max(-1.0, min(1.0, rg))

        results = {
            'rg': rg,
            'rg_se': rg_se,
            'n_snps': M,
            'p_value': 2 * stats.norm.sf(abs(rg / rg_se))
        }

        logger.info(f"\nGenetic Correlation:")
        logger.info(f"  rg = {rg:.4f} (SE = {rg_se:.4f})")
        logger.info(f"  P-value = {results['p_value']:.2e}")

        return results
