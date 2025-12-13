/**
 * @file ld_matrix.h
 * @brief Linkage disequilibrium (LD) matrix calculation
 *
 * Computes pairwise LD (r²) between SNPs, accounting for:
 * - Proper allele frequency estimation from genotypes
 * - Sparse storage for long-range LD
 * - Shrinkage for numerical stability
 */

#ifndef GENOMIC_SELECTION_LD_MATRIX_H
#define GENOMIC_SELECTION_LD_MATRIX_H

#include "types.h"
#include <Eigen/Dense>

namespace genomic {

class LDMatrixCalculator {
public:
    /**
     * Constructor
     *
     * @param shrinkage Shrinkage toward identity (default: 0.9)
     * @param min_maf Minimum minor allele frequency (default: 0.01)
     */
    LDMatrixCalculator(Float shrinkage = 0.9, Float min_maf = 0.01);

    /**
     * Compute LD matrix from genotype data
     *
     * Correlation between SNPs i and j:
     * r_ij = Cov(G_i, G_j) / sqrt(Var(G_i) * Var(G_j))
     *
     * With shrinkage:
     * R_shrunk = shrinkage * R + (1 - shrinkage) * I
     *
     * @param genotypes Genotype matrix (n_individuals × n_snps), values in {0, 1, 2}
     * @return LD correlation matrix (n_snps × n_snps)
     */
    LDMatrix compute(const GenotypeMatrix& genotypes);

    /**
     * Compute LD matrix for a genomic window
     *
     * Only compute LD for SNPs within a window (e.g., 3 Mb or 3 cM)
     * This is more efficient and biologically meaningful
     *
     * @param genotypes Genotype matrix
     * @param positions SNP positions in base pairs
     * @param window_size Window size in base pairs (default: 3000000 = 3 Mb)
     * @return Sparse LD matrix
     */
    SparseLDMatrix compute_windowed(
        const GenotypeMatrix& genotypes,
        const std::vector<UInt>& positions,
        UInt window_size = 3000000
    );

    /**
     * Estimate allele frequencies from genotypes
     *
     * CRITICAL: Must derive from GENOTYPES, not simulation parameters!
     *
     * @param genotypes Genotype matrix
     * @return Vector of allele frequencies (length n_snps)
     */
    Vector estimate_allele_frequencies(const GenotypeMatrix& genotypes);

    /**
     * Standardize genotypes for LD calculation
     *
     * X_std = (X - 2p) / sqrt(2p(1-p))
     *
     * @param genotypes Raw genotypes
     * @param allele_freq Allele frequencies
     * @return Standardized genotypes
     */
    Matrix standardize_genotypes(
        const GenotypeMatrix& genotypes,
        const Vector& allele_freq
    );

    /**
     * Check positive definiteness of LD matrix
     *
     * Required for LDpred2. If not PD, increase shrinkage.
     *
     * @param ld_matrix LD matrix
     * @return true if positive definite
     */
    bool is_positive_definite(const LDMatrix& ld_matrix);

    /**
     * Regularize LD matrix to ensure positive definiteness
     *
     * Uses spectral decomposition and eigenvalue clipping
     *
     * @param ld_matrix Input LD matrix
     * @param min_eigenvalue Minimum eigenvalue (default: 1e-6)
     * @return Regularized LD matrix
     */
    LDMatrix regularize(const LDMatrix& ld_matrix, Float min_eigenvalue = 1e-6);

private:
    Float shrinkage_;
    Float min_maf_;

    /**
     * Compute correlation between two standardized genotype vectors
     */
    Float correlation(const Vector& g1, const Vector& g2);
};

} // namespace genomic

#endif // GENOMIC_SELECTION_LD_MATRIX_H
