/**
 * @file types.h
 * @brief Common type definitions for genomic selection core
 */

#ifndef GENOMIC_SELECTION_TYPES_H
#define GENOMIC_SELECTION_TYPES_H

#include <Eigen/Dense>
#include <Eigen/Sparse>
#include <vector>
#include <string>
#include <cstdint>

namespace genomic {

// Scalar types
using Float = double;
using Int = int64_t;
using UInt = uint64_t;

// Eigen matrix types
using Matrix = Eigen::MatrixXd;
using Vector = Eigen::VectorXd;
using SparseMatrix = Eigen::SparseMatrix<Float>;

// Genotype matrix: individuals × SNPs (0, 1, 2 for diploid genotypes)
using GenotypeMatrix = Eigen::Matrix<uint8_t, Eigen::Dynamic, Eigen::Dynamic>;

// LD matrix: SNP correlations (typically sparse for distant SNPs)
using LDMatrix = Eigen::MatrixXd;  // Dense for local LD blocks
using SparseLDMatrix = Eigen::SparseMatrix<Float>;  // Sparse for genome-wide

/**
 * GWAS summary statistics for a single SNP
 */
struct SNP {
    std::string id;           // rs ID or chr:pos
    std::string chromosome;   // Chromosome (1-22, X, Y, MT)
    UInt position;            // Base pair position
    std::string allele_ref;   // Reference allele
    std::string allele_alt;   // Alternative (effect) allele
    Float beta;               // Effect size
    Float se;                 // Standard error
    Float pvalue;             // P-value
    UInt sample_size;         // Sample size for this SNP
    Float maf;                // Minor allele frequency (derived from genotypes)
};

/**
 * GWAS summary statistics for multiple SNPs
 */
struct GWASData {
    std::vector<SNP> snps;
    UInt total_samples;  // Total GWAS sample size
    Float heritability;  // SNP heritability (if known)
};

/**
 * LDpred2 hyperparameters
 */
struct LDpredParams {
    Float h2;           // SNP heritability
    Float p;            // Polygenicity (proportion of causal SNPs)
    UInt n_samples;     // GWAS sample size
    UInt n_iter;        // Number of Gibbs iterations
    UInt burn_in;       // Burn-in iterations
    Float shrink;       // Shrinkage parameter for LD matrix
};

/**
 * LDpred2 results
 */
struct LDpredResult {
    Vector beta_posterior;      // Posterior effect sizes
    Vector pip;                 // Posterior inclusion probabilities
    Float h2_estimate;          // Estimated heritability
    Float polygenicity;         // Estimated polygenicity
    std::vector<Float> mcmc_h2; // MCMC trace for h2
    bool converged;             // Convergence flag
};

/**
 * SuSiE credible set
 */
struct CredibleSet {
    std::vector<UInt> snp_indices;  // SNP indices in credible set
    Vector purity;                   // LD purity measure
    Float coverage;                  // Cumulative posterior probability
};

/**
 * SuSiE fine-mapping results
 */
struct SuSiEResult {
    Vector pip;                        // Posterior inclusion probabilities
    Matrix alpha;                      // L × M matrix of posterior assignments
    Matrix mu;                         // L × M matrix of posterior means
    std::vector<CredibleSet> cs;      // Credible sets
    UInt L;                           // Number of single effects
    bool converged;
};

} // namespace genomic

#endif // GENOMIC_SELECTION_TYPES_H
