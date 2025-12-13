/**
 * @file ld_matrix.cpp
 * @brief Implementation of LD matrix calculation
 */

#include "ld_matrix.h"
#include <Eigen/Eigenvalues>
#include <cmath>
#include <stdexcept>
#include <iostream>

namespace genomic {

LDMatrixCalculator::LDMatrixCalculator(Float shrinkage, Float min_maf)
    : shrinkage_(shrinkage), min_maf_(min_maf) {

    if (shrinkage < 0.0 || shrinkage > 1.0) {
        throw std::invalid_argument("Shrinkage must be in [0, 1]");
    }

    if (min_maf < 0.0 || min_maf > 0.5) {
        throw std::invalid_argument("Minimum MAF must be in [0, 0.5]");
    }
}

Vector LDMatrixCalculator::estimate_allele_frequencies(
    const GenotypeMatrix& genotypes
) {
    const Int n_individuals = genotypes.rows();
    const Int n_snps = genotypes.cols();

    Vector allele_freq(n_snps);

    #pragma omp parallel for
    for (Int j = 0; j < n_snps; ++j) {
        Float sum = 0.0;
        Int count = 0;

        for (Int i = 0; i < n_individuals; ++i) {
            uint8_t genotype = genotypes(i, j);

            // Skip missing genotypes (encoded as 255)
            if (genotype != 255) {
                sum += genotype;
                count++;
            }
        }

        // Allele frequency = mean(genotypes) / 2
        if (count > 0) {
            allele_freq(j) = sum / (2.0 * count);
        } else {
            allele_freq(j) = 0.0;  // No data for this SNP
        }

        // Clamp to [0, 1]
        allele_freq(j) = std::max(0.0, std::min(1.0, allele_freq(j)));
    }

    return allele_freq;
}

Matrix LDMatrixCalculator::standardize_genotypes(
    const GenotypeMatrix& genotypes,
    const Vector& allele_freq
) {
    const Int n_individuals = genotypes.rows();
    const Int n_snps = genotypes.cols();

    Matrix standardized(n_individuals, n_snps);

    #pragma omp parallel for
    for (Int j = 0; j < n_snps; ++j) {
        Float p = allele_freq(j);

        // Variance = 2p(1-p)
        Float variance = 2.0 * p * (1.0 - p);

        // Avoid division by zero for monomorphic SNPs
        Float std_dev = std::sqrt(std::max(variance, 1e-10));

        for (Int i = 0; i < n_individuals; ++i) {
            uint8_t g = genotypes(i, j);

            if (g != 255) {  // Not missing
                // Standardize: (g - 2p) / sqrt(2p(1-p))
                standardized(i, j) = (static_cast<Float>(g) - 2.0 * p) / std_dev;
            } else {
                // Impute missing as mean (0 after standardization)
                standardized(i, j) = 0.0;
            }
        }
    }

    return standardized;
}

LDMatrix LDMatrixCalculator::compute(const GenotypeMatrix& genotypes) {
    const Int n_individuals = genotypes.rows();
    const Int n_snps = genotypes.cols();

    std::cout << "Computing LD matrix for " << n_snps << " SNPs and "
              << n_individuals << " individuals..." << std::endl;

    // Step 1: Estimate allele frequencies from genotypes
    Vector allele_freq = estimate_allele_frequencies(genotypes);

    // Filter out rare variants (MAF < min_maf)
    std::vector<Int> keep_snps;
    for (Int j = 0; j < n_snps; ++j) {
        Float maf = std::min(allele_freq(j), 1.0 - allele_freq(j));
        if (maf >= min_maf_) {
            keep_snps.push_back(j);
        }
    }

    std::cout << "Keeping " << keep_snps.size() << " / " << n_snps
              << " SNPs after MAF filter (MAF >= " << min_maf_ << ")" << std::endl;

    // Step 2: Standardize genotypes
    Matrix standardized = standardize_genotypes(genotypes, allele_freq);

    // Step 3: Compute correlation matrix R = X'X / n
    // Use only filtered SNPs
    const Int m = keep_snps.size();
    LDMatrix ld_matrix(m, m);

    #pragma omp parallel for schedule(dynamic)
    for (Int i = 0; i < m; ++i) {
        Int snp_i = keep_snps[i];

        for (Int j = i; j < m; ++j) {
            Int snp_j = keep_snps[j];

            // Pearson correlation
            Float corr = standardized.col(snp_i).dot(standardized.col(snp_j)) / n_individuals;

            ld_matrix(i, j) = corr;
            ld_matrix(j, i) = corr;  // Symmetric
        }
    }

    // Step 4: Apply shrinkage: R_shrunk = shrinkage * R + (1 - shrinkage) * I
    LDMatrix identity = LDMatrix::Identity(m, m);
    ld_matrix = shrinkage_ * ld_matrix + (1.0 - shrinkage_) * identity;

    // Step 5: Verify positive definiteness
    if (!is_positive_definite(ld_matrix)) {
        std::cout << "Warning: LD matrix not positive definite, regularizing..." << std::endl;
        ld_matrix = regularize(ld_matrix);
    }

    std::cout << "LD matrix computation complete." << std::endl;

    return ld_matrix;
}

SparseLDMatrix LDMatrixCalculator::compute_windowed(
    const GenotypeMatrix& genotypes,
    const std::vector<UInt>& positions,
    UInt window_size
) {
    const Int n_individuals = genotypes.rows();
    const Int n_snps = genotypes.cols();

    std::cout << "Computing windowed LD matrix (window = " << window_size << " bp)..." << std::endl;

    // Estimate allele frequencies
    Vector allele_freq = estimate_allele_frequencies(genotypes);
    Matrix standardized = standardize_genotypes(genotypes, allele_freq);

    // Build sparse matrix with triplets
    std::vector<Eigen::Triplet<Float>> triplets;
    triplets.reserve(n_snps * 100);  // Rough estimate

    #pragma omp parallel
    {
        std::vector<Eigen::Triplet<Float>> local_triplets;

        #pragma omp for schedule(dynamic)
        for (Int i = 0; i < n_snps; ++i) {
            for (Int j = i; j < n_snps; ++j) {
                // Check if SNPs are within window
                if (std::abs(static_cast<Int>(positions[j]) - static_cast<Int>(positions[i])) <= static_cast<Int>(window_size)) {
                    Float corr = standardized.col(i).dot(standardized.col(j)) / n_individuals;

                    // Only store non-zero correlations (threshold at 0.01)
                    if (std::abs(corr) > 0.01 || i == j) {
                        local_triplets.emplace_back(i, j, corr);
                        if (i != j) {
                            local_triplets.emplace_back(j, i, corr);
                        }
                    }
                }
            }
        }

        #pragma omp critical
        {
            triplets.insert(triplets.end(), local_triplets.begin(), local_triplets.end());
        }
    }

    // Construct sparse matrix
    SparseLDMatrix sparse_ld(n_snps, n_snps);
    sparse_ld.setFromTriplets(triplets.begin(), triplets.end());

    // Add shrinkage to diagonal
    for (Int i = 0; i < n_snps; ++i) {
        sparse_ld.coeffRef(i, i) = shrinkage_ * sparse_ld.coeff(i, i) + (1.0 - shrinkage_);
    }

    std::cout << "Sparse LD matrix: " << sparse_ld.nonZeros() << " / "
              << (n_snps * n_snps) << " non-zero elements ("
              << (100.0 * sparse_ld.nonZeros() / (n_snps * n_snps)) << "%)" << std::endl;

    return sparse_ld;
}

bool LDMatrixCalculator::is_positive_definite(const LDMatrix& ld_matrix) {
    // Compute eigenvalues
    Eigen::SelfAdjointEigenSolver<LDMatrix> es(ld_matrix);

    if (es.info() != Eigen::Success) {
        return false;
    }

    // Check if all eigenvalues are positive
    Vector eigenvalues = es.eigenvalues();
    Float min_eigenvalue = eigenvalues.minCoeff();

    return min_eigenvalue > 0.0;
}

LDMatrix LDMatrixCalculator::regularize(
    const LDMatrix& ld_matrix,
    Float min_eigenvalue
) {
    // Spectral decomposition: R = Q Λ Q'
    Eigen::SelfAdjointEigenSolver<LDMatrix> es(ld_matrix);

    if (es.info() != Eigen::Success) {
        throw std::runtime_error("Eigenvalue decomposition failed");
    }

    Vector eigenvalues = es.eigenvalues();
    Matrix eigenvectors = es.eigenvectors();

    // Clip eigenvalues to minimum
    for (Int i = 0; i < eigenvalues.size(); ++i) {
        eigenvalues(i) = std::max(eigenvalues(i), min_eigenvalue);
    }

    // Reconstruct: R_reg = Q Λ_clipped Q'
    LDMatrix regularized = eigenvectors * eigenvalues.asDiagonal() * eigenvectors.transpose();

    return regularized;
}

} // namespace genomic
