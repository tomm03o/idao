/**
 * @file grm.h
 * @brief Genomic Relationship Matrix (GRM) calculation
 *
 * GRM quantifies genetic similarity between individuals.
 * Critical for inbreeding control in embryo selection.
 *
 * Formula (VanRaden 2008):
 *   G = (X - P)(X - P)' / Σ(2p_i(1-p_i))
 *
 * where:
 *   X = genotype matrix (n × m), values in {0, 1, 2}
 *   P = matrix of expected genotypes (2p_i for each SNP i)
 *   p_i = allele frequency of SNP i
 *
 * CRITICAL: Allele frequencies MUST be derived from genotype matrix,
 * NOT from simulation parameters!
 */

#ifndef GENOMIC_SELECTION_GRM_H
#define GENOMIC_SELECTION_GRM_H

#include "types.h"

namespace genomic {

class GRMCalculator {
public:
    /**
     * Constructor
     *
     * @param min_maf Minimum minor allele frequency for SNP inclusion (default: 0.01)
     */
    explicit GRMCalculator(Float min_maf = 0.01);

    /**
     * Compute genomic relationship matrix
     *
     * G_ij = genetic relationship between individuals i and j
     *   G_ii ≈ 1 + inbreeding coefficient
     *   G_ij ≈ 0 for unrelated individuals
     *   G_ij ≈ 0.5 for parent-offspring or full siblings
     *
     * @param genotypes Genotype matrix (n_individuals × n_snps)
     * @return GRM matrix (n_individuals × n_individuals)
     */
    Matrix compute(const GenotypeMatrix& genotypes);

    /**
     * Compute allele frequencies from genotype data
     *
     * MUST use this method, not external parameters!
     *
     * @param genotypes Genotype matrix
     * @return Allele frequency vector
     */
    Vector compute_allele_frequencies(const GenotypeMatrix& genotypes);

    /**
     * Center genotypes: X_centered = X - 2p
     *
     * @param genotypes Raw genotypes
     * @param allele_freq Allele frequencies
     * @return Centered genotypes
     */
    Matrix center_genotypes(
        const GenotypeMatrix& genotypes,
        const Vector& allele_freq
    );

    /**
     * Check for inbreeding
     *
     * Diagonal elements > 1.1 indicate inbreeding
     *
     * @param grm Genomic relationship matrix
     * @return Vector of inbreeding coefficients (length n_individuals)
     */
    Vector estimate_inbreeding(const Matrix& grm);

    /**
     * Identify related individuals
     *
     * @param grm Genomic relationship matrix
     * @param threshold Relationship threshold (default: 0.05 for 2nd-degree relatives)
     * @return Pairs of related individuals
     */
    std::vector<std::pair<UInt, UInt>> find_related_pairs(
        const Matrix& grm,
        Float threshold = 0.05
    );

private:
    Float min_maf_;
};

} // namespace genomic

#endif // GENOMIC_SELECTION_GRM_H
