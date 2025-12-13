/**
 * @file ldpred.cpp
 * @brief Implementation of LDpred2-auto
 */

#include "ldpred.h"
#include <cmath>
#include <iostream>
#include <algorithm>
#include <limits>

namespace genomic {

LDpred2::LDpred2(
    const LDMatrix& ld_matrix,
    UInt n_iter,
    UInt burn_in,
    UInt random_seed
) : ld_matrix_(ld_matrix),
    n_iter_(n_iter),
    burn_in_(burn_in),
    rng_(random_seed) {}

LDpredResult LDpred2::fit(
    const GWASData& gwas,
    Float h2,
    Float p
) {
    const UInt m = gwas.snps.size();

    // Extract marginal statistics
    Vector marginal_beta(m);
    Vector marginal_se(m);
    UInt n_samples = 0;

    for (UInt i = 0; i < m; ++i) {
        marginal_beta(i) = gwas.snps[i].beta;
        marginal_se(i) = gwas.snps[i].se;
        n_samples = std::max(n_samples, gwas.snps[i].sample_size);
    }

    std::cout << "Running LDpred2 with h²=" << h2 << ", p=" << p << std::endl;
    std::cout << "  SNPs: " << m << std::endl;
    std::cout << "  Sample size: " << n_samples << std::endl;

    // Run Gibbs sampler
    return gibbs_sampler(marginal_beta, marginal_se, n_samples, h2, p);
}

LDpredResult LDpred2::fit_auto(
    const GWASData& gwas,
    const std::vector<Float>& h2_grid,
    const std::vector<Float>& p_grid
) {
    std::cout << "=" * 80 << std::endl;
    std::cout << "LDpred2-auto: Grid search over hyperparameters" << std::endl;
    std::cout << "=" * 80 << std::endl;
    std::cout << "h² grid: ";
    for (Float h2 : h2_grid) std::cout << h2 << " ";
    std::cout << std::endl;
    std::cout << "p grid: ";
    for (Float p : p_grid) std::cout << p << " ";
    std::cout << std::endl;

    Float best_elbo = -std::numeric_limits<Float>::infinity();
    LDpredResult best_result;
    Float best_h2 = 0.0;
    Float best_p = 0.0;

    const UInt m = gwas.snps.size();
    Vector marginal_beta(m);
    Vector marginal_se(m);
    UInt n_samples = 0;

    for (UInt i = 0; i < m; ++i) {
        marginal_beta(i) = gwas.snps[i].beta;
        marginal_se(i) = gwas.snps[i].se;
        n_samples = std::max(n_samples, gwas.snps[i].sample_size);
    }

    // Grid search
    for (Float h2 : h2_grid) {
        for (Float p : p_grid) {
            std::cout << "\nTrying h²=" << h2 << ", p=" << p << std::endl;

            // Fit model
            LDpredResult result = gibbs_sampler(marginal_beta, marginal_se, n_samples, h2, p);

            // Compute ELBO for model selection
            Float elbo = compute_elbo(marginal_beta, result.beta_posterior, ld_matrix_);

            std::cout << "  ELBO: " << elbo << std::endl;
            std::cout << "  Converged: " << (result.converged ? "Yes" : "No") << std::endl;

            // Update best model
            if (elbo > best_elbo && result.converged) {
                best_elbo = elbo;
                best_result = result;
                best_h2 = h2;
                best_p = p;
            }
        }
    }

    std::cout << "\n" << "=" * 80 << std::endl;
    std::cout << "Best model: h²=" << best_h2 << ", p=" << best_p << std::endl;
    std::cout << "Best ELBO: " << best_elbo << std::endl;
    std::cout << "=" * 80 << std::endl;

    best_result.h2_estimate = best_h2;
    best_result.polygenicity = best_p;

    return best_result;
}

LDpredResult LDpred2::gibbs_sampler(
    const Vector& marginal_beta,
    const Vector& marginal_se,
    UInt n_samples,
    Float h2,
    Float p
) {
    const UInt m = marginal_beta.size();

    // Initialize effect sizes at marginal estimates
    Vector current_beta = marginal_beta;

    // Storage for MCMC samples
    Matrix beta_samples(n_iter_ - burn_in_, m);
    std::vector<Float> mcmc_h2;
    mcmc_h2.reserve(n_iter_ - burn_in_);

    // Gibbs iterations
    for (UInt iter = 0; iter < n_iter_; ++iter) {
        if (iter % 100 == 0) {
            std::cout << "  Iteration " << iter << " / " << n_iter_ << std::endl;
        }

        // Update each SNP
        for (UInt i = 0; i < m; ++i) {
            current_beta(i) = sample_conditional_posterior(
                i,
                current_beta,
                marginal_beta(i),
                marginal_se(i),
                n_samples,
                h2,
                p
            );
        }

        // Store samples after burn-in
        if (iter >= burn_in_) {
            beta_samples.row(iter - burn_in_) = current_beta;

            // Track heritability
            Float iter_h2 = estimate_h2(beta_samples.topRows(iter - burn_in_ + 1));
            mcmc_h2.push_back(iter_h2);
        }
    }

    // Posterior mean
    Vector beta_posterior = beta_samples.colwise().mean();

    // Posterior inclusion probabilities (proportion of non-zero samples)
    Vector pip = Vector::Zero(m);
    for (UInt j = 0; j < m; ++j) {
        UInt count_nonzero = 0;
        for (UInt i = 0; i < beta_samples.rows(); ++i) {
            if (std::abs(beta_samples(i, j)) > 1e-10) {
                count_nonzero++;
            }
        }
        pip(j) = static_cast<Float>(count_nonzero) / beta_samples.rows();
    }

    // Check convergence
    bool converged = check_convergence(mcmc_h2);

    // Create result
    LDpredResult result;
    result.beta_posterior = beta_posterior;
    result.pip = pip;
    result.h2_estimate = mcmc_h2.back();
    result.polygenicity = p;
    result.mcmc_h2 = mcmc_h2;
    result.converged = converged;

    return result;
}

Float LDpred2::sample_conditional_posterior(
    UInt i,
    const Vector& current_beta,
    Float marginal_beta,
    Float marginal_se,
    UInt n_samples,
    Float h2,
    Float p
) {
    const UInt m = current_beta.size();

    // Prior variance for causal SNPs
    Float sigma2_prior = h2 / (m * p);

    // Compute residual (contribution from other SNPs)
    Float residual = marginal_beta;
    for (UInt j = 0; j < m; ++j) {
        if (j != i) {
            residual -= ld_matrix_(i, j) * current_beta(j);
        }
    }

    // Posterior variance
    Float precision_prior = 1.0 / sigma2_prior;
    Float precision_likelihood = n_samples / (marginal_se * marginal_se);
    Float precision_posterior = precision_prior + precision_likelihood * ld_matrix_(i, i);
    Float sigma2_posterior = 1.0 / precision_posterior;

    // Posterior mean
    Float mu_posterior = sigma2_posterior * precision_likelihood * residual;

    // Spike-and-slab: with probability p, sample from slab; otherwise set to 0
    std::bernoulli_distribution bernoulli(p);
    std::normal_distribution<Float> normal(mu_posterior, std::sqrt(sigma2_posterior));

    if (bernoulli(rng_)) {
        // Causal: sample from slab
        return normal(rng_);
    } else {
        // Non-causal: set to 0
        return 0.0;
    }
}

bool LDpred2::check_convergence(const std::vector<Float>& mcmc_trace) {
    if (mcmc_trace.size() < 100) {
        return false;  // Need enough samples
    }

    // Simple convergence check: variance of last 50 samples < 0.1 * overall variance
    const UInt n = mcmc_trace.size();
    const UInt window = std::min(static_cast<UInt>(50), n / 4);

    // Compute variance of last window
    Float mean_last = 0.0;
    for (UInt i = n - window; i < n; ++i) {
        mean_last += mcmc_trace[i];
    }
    mean_last /= window;

    Float var_last = 0.0;
    for (UInt i = n - window; i < n; ++i) {
        Float diff = mcmc_trace[i] - mean_last;
        var_last += diff * diff;
    }
    var_last /= window;

    // Compute overall variance
    Float mean_all = 0.0;
    for (Float val : mcmc_trace) {
        mean_all += val;
    }
    mean_all /= mcmc_trace.size();

    Float var_all = 0.0;
    for (Float val : mcmc_trace) {
        Float diff = val - mean_all;
        var_all += diff * diff;
    }
    var_all /= mcmc_trace.size();

    // Converged if variance stabilized
    bool converged = (var_last < 0.1 * var_all);

    return converged;
}

Float LDpred2::estimate_h2(const Matrix& beta_samples) {
    // Estimate heritability as variance explained by current betas
    // h² ≈ Var(Σ β_i)

    const UInt n_samples = beta_samples.rows();
    const UInt m = beta_samples.cols();

    // Compute variance of polygenic scores across MCMC samples
    Float mean_score = 0.0;
    std::vector<Float> scores(n_samples);

    for (UInt i = 0; i < n_samples; ++i) {
        scores[i] = beta_samples.row(i).sum();
        mean_score += scores[i];
    }
    mean_score /= n_samples;

    Float variance = 0.0;
    for (Float score : scores) {
        Float diff = score - mean_score;
        variance += diff * diff;
    }
    variance /= n_samples;

    // Normalize by number of SNPs
    Float h2 = variance / m;

    return std::max(0.0, std::min(1.0, h2));  // Clamp to [0, 1]
}

Float LDpred2::compute_elbo(
    const Vector& marginal_beta,
    const Vector& posterior_beta,
    const LDMatrix& ld_matrix
) {
    // Simplified ELBO: negative squared error accounting for LD
    // ELBO ≈ -||β_marginal - R·β_posterior||²

    Vector predicted = ld_matrix * posterior_beta;
    Vector residual = marginal_beta - predicted;

    Float elbo = -residual.squaredNorm();

    return elbo;
}

Vector LDpred2::predict(
    const GenotypeMatrix& genotypes,
    const Vector& beta
) {
    const UInt n_individuals = genotypes.rows();
    const UInt m = genotypes.cols();

    if (static_cast<UInt>(beta.size()) != m) {
        throw std::invalid_argument("Beta size must match number of SNPs");
    }

    Vector pgs = Vector::Zero(n_individuals);

    #pragma omp parallel for
    for (Int i = 0; i < static_cast<Int>(n_individuals); ++i) {
        Float score = 0.0;
        for (UInt j = 0; j < m; ++j) {
            if (genotypes(i, j) != 255) {  // Not missing
                score += beta(j) * genotypes(i, j);
            }
        }
        pgs(i) = score;
    }

    return pgs;
}

} // namespace genomic
