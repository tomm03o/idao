/**
 * @file ldpred.h
 * @brief LDpred2-auto implementation
 *
 * Bayesian polygenic score with automatic hyperparameter tuning via grid search.
 *
 * Model:
 *   β_i | p, h² ~ π·N(0, h²/(Mp)) + (1-π)·δ_0
 *
 * where:
 *   β = true effect sizes
 *   p = polygenicity (proportion of causal SNPs)
 *   h² = SNP heritability
 *   M = number of SNPs
 *
 * Reference: Privé et al. (2020) "LDpred2: better, faster, stronger"
 */

#ifndef GENOMIC_SELECTION_LDPRED_H
#define GENOMIC_SELECTION_LDPRED_H

#include "types.h"
#include "ld_matrix.h"
#include <random>

namespace genomic {

class LDpred2 {
public:
    /**
     * Constructor
     *
     * @param ld_matrix LD correlation matrix
     * @param n_iter Number of Gibbs sampling iterations (default: 1000)
     * @param burn_in Burn-in iterations (default: 200)
     * @param random_seed Random seed for reproducibility
     */
    LDpred2(
        const LDMatrix& ld_matrix,
        UInt n_iter = 1000,
        UInt burn_in = 200,
        UInt random_seed = 42
    );

    /**
     * Fit LDpred2 model with fixed hyperparameters
     *
     * @param gwas GWAS summary statistics
     * @param h2 SNP heritability
     * @param p Polygenicity
     * @return Posterior effect sizes
     */
    LDpredResult fit(
        const GWASData& gwas,
        Float h2,
        Float p
    );

    /**
     * Fit LDpred2-auto with grid search over hyperparameters
     *
     * Automatically selects optimal h² and p via:
     * 1. Grid search over h² and p
     * 2. MCMC to estimate parameters
     * 3. Convergence diagnostics
     *
     * @param gwas GWAS summary statistics
     * @param h2_grid Grid of h² values (e.g., [0.1, 0.3, 0.5, 0.7])
     * @param p_grid Grid of p values (e.g., [0.01, 0.1, 0.3, 1.0])
     * @return Best model results
     */
    LDpredResult fit_auto(
        const GWASData& gwas,
        const std::vector<Float>& h2_grid,
        const std::vector<Float>& p_grid
    );

    /**
     * Predict polygenic scores for new genotypes
     *
     * PGS = Σ(β_i × G_i)
     *
     * @param genotypes Genotype matrix (n_individuals × n_snps)
     * @param beta Effect sizes from fit()
     * @return Vector of polygenic scores (length n_individuals)
     */
    Vector predict(
        const GenotypeMatrix& genotypes,
        const Vector& beta
    );

private:
    const LDMatrix& ld_matrix_;
    UInt n_iter_;
    UInt burn_in_;
    std::mt19937 rng_;

    /**
     * Gibbs sampler for posterior inference
     *
     * Iteratively samples from:
     *   p(β_i | β_{-i}, X, y, R, h², p)
     *
     * @param marginal_beta Marginal effect sizes (from GWAS)
     * @param marginal_se Marginal standard errors
     * @param n_samples GWAS sample size
     * @param h2 Heritability
     * @param p Polygenicity
     * @return Posterior effect sizes and diagnostics
     */
    LDpredResult gibbs_sampler(
        const Vector& marginal_beta,
        const Vector& marginal_se,
        UInt n_samples,
        Float h2,
        Float p
    );

    /**
     * Sample from conditional posterior for single SNP
     *
     * p(β_i | β_{-i}) ∝ N(μ_i, σ²_i) × [π + (1-π)δ_0]
     *
     * @param i SNP index
     * @param current_beta Current effect sizes
     * @param marginal_beta Marginal effect from GWAS
     * @param marginal_se Standard error
     * @param n_samples Sample size
     * @param h2 Heritability
     * @param p Polygenicity
     * @return Sampled effect size
     */
    Float sample_conditional_posterior(
        UInt i,
        const Vector& current_beta,
        Float marginal_beta,
        Float marginal_se,
        UInt n_samples,
        Float h2,
        Float p
    );

    /**
     * Check MCMC convergence using Geweke diagnostic
     *
     * @param mcmc_trace MCMC trace for a parameter
     * @return true if converged
     */
    bool check_convergence(const std::vector<Float>& mcmc_trace);

    /**
     * Estimate heritability from MCMC trace
     *
     * @param beta_samples Matrix of MCMC samples (n_iter × n_snps)
     * @return Posterior mean h²
     */
    Float estimate_h2(const Matrix& beta_samples);

    /**
     * Compute ELBO (Evidence Lower Bound) for model selection
     *
     * @param marginal_beta Marginal effects
     * @param posterior_beta Posterior effects
     * @param ld_matrix LD matrix
     * @return ELBO value
     */
    Float compute_elbo(
        const Vector& marginal_beta,
        const Vector& posterior_beta,
        const LDMatrix& ld_matrix
    );
};

} // namespace genomic

#endif // GENOMIC_SELECTION_LDPRED_H
