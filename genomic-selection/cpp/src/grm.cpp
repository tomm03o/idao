/**
 * @file grm.cpp
 * @brief Implementation of Genomic Relationship Matrix calculation
 */

#include "grm.h"
#include <iostream>
#include <cmath>

namespace genomic {

GRMCalculator::GRMCalculator(Float min_maf)
    : min_maf_(min_maf) {}

Vector GRMCalculator::compute_allele_frequencies(
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
            uint8_t g = genotypes(i, j);

            if (g != 255) {  // Not missing
                sum += g;
                count++;
            }
        }

        if (count > 0) {
            // Allele frequency = mean(genotypes) / 2
            allele_freq(j) = sum / (2.0 * count);
        } else {
            allele_freq(j) = 0.0;
        }

        // Clamp to [0, 1]
        allele_freq(j) = std::max(0.0, std::min(1.0, allele_freq(j)));
    }

    return allele_freq;
}

Matrix GRMCalculator::center_genotypes(
    const GenotypeMatrix& genotypes,
    const Vector& allele_freq
) {
    const Int n_individuals = genotypes.rows();
    const Int n_snps = genotypes.cols();

    Matrix centered(n_individuals, n_snps);

    #pragma omp parallel for
    for (Int j = 0; j < n_snps; ++j) {
        Float expected = 2.0 * allele_freq(j);  // E[X] = 2p

        for (Int i = 0; i < n_individuals; ++i) {
            uint8_t g = genotypes(i, j);

            if (g != 255) {
                // Center: X - E[X]
                centered(i, j) = static_cast<Float>(g) - expected;
            } else {
                // Impute missing as 0 (after centering)
                centered(i, j) = 0.0;
            }
        }
    }

    return centered;
}

Matrix GRMCalculator::compute(const GenotypeMatrix& genotypes) {
    const Int n_individuals = genotypes.rows();
    const Int n_snps = genotypes.cols();

    std::cout << "Computing GRM for " << n_individuals << " individuals and "
              << n_snps << " SNPs..." << std::endl;

    // Step 1: Compute allele frequencies FROM GENOTYPES
    std::cout << "  Computing allele frequencies from genotype data..." << std::endl;
    Vector allele_freq = compute_allele_frequencies(genotypes);

    // Step 2: Filter SNPs by MAF
    std::vector<Int> keep_snps;
    for (Int j = 0; j < n_snps; ++j) {
        Float maf = std::min(allele_freq(j), 1.0 - allele_freq(j));
        if (maf >= min_maf_) {
            keep_snps.push_back(j);
        }
    }

    const Int m = keep_snps.size();
    std::cout << "  Keeping " << m << " / " << n_snps << " SNPs (MAF >= "
              << min_maf_ << ")" << std::endl;

    // Step 3: Center genotypes
    std::cout << "  Centering genotypes..." << std::endl;
    Matrix centered = center_genotypes(genotypes, allele_freq);

    // Extract kept SNPs
    Matrix X(n_individuals, m);
    for (Int j = 0; j < m; ++j) {
        X.col(j) = centered.col(keep_snps[j]);
    }

    // Step 4: Compute normalization factor
    // Denominator: Σ 2p_i(1-p_i)
    Float normalization = 0.0;
    for (Int j : keep_snps) {
        Float p = allele_freq(j);
        normalization += 2.0 * p * (1.0 - p);
    }

    std::cout << "  Normalization factor: " << normalization << std::endl;

    // Step 5: Compute GRM = X X' / normalization
    std::cout << "  Computing G = X X' / norm..." << std::endl;
    Matrix grm = (X * X.transpose()) / normalization;

    // Step 6: Validate diagonal
    std::cout << "\nGRM Diagonal Statistics:" << std::endl;
    Vector diagonal = grm.diagonal();
    std::cout << "  Mean: " << diagonal.mean() << std::endl;
    std::cout << "  Min: " << diagonal.minCoeff() << std::endl;
    std::cout << "  Max: " << diagonal.maxCoeff() << std::endl;
    std::cout << "  Std: " << std::sqrt((diagonal.array() - diagonal.mean()).square().mean())
              << std::endl;

    // Expected: diagonal ≈ 1 for non-inbred individuals
    if (diagonal.mean() > 1.5 || diagonal.mean() < 0.5) {
        std::cout << "\n⚠️  WARNING: GRM diagonal mean far from 1.0!" << std::endl;
        std::cout << "    This suggests allele frequency estimation error." << std::endl;
    }

    std::cout << "\nGRM computation complete." << std::endl;

    return grm;
}

Vector GRMCalculator::estimate_inbreeding(const Matrix& grm) {
    // Inbreeding coefficient F = G_ii - 1
    Vector inbreeding = grm.diagonal().array() - 1.0;

    std::cout << "\nInbreeding Statistics:" << std::endl;
    std::cout << "  Mean F: " << inbreeding.mean() << std::endl;
    std::cout << "  Max F: " << inbreeding.maxCoeff() << std::endl;
    std::cout << "  Min F: " << inbreeding.minCoeff() << std::endl;

    Int n_inbred = (inbreeding.array() > 0.05).count();
    std::cout << "  Inbred individuals (F > 0.05): " << n_inbred << std::endl;

    return inbreeding;
}

std::vector<std::pair<UInt, UInt>> GRMCalculator::find_related_pairs(
    const Matrix& grm,
    Float threshold
) {
    const Int n = grm.rows();
    std::vector<std::pair<UInt, UInt>> related_pairs;

    for (Int i = 0; i < n; ++i) {
        for (Int j = i + 1; j < n; ++j) {
            if (grm(i, j) > threshold) {
                related_pairs.emplace_back(i, j);
            }
        }
    }

    std::cout << "\nRelated pairs (threshold = " << threshold << "): "
              << related_pairs.size() << std::endl;

    // Print examples
    if (!related_pairs.empty()) {
        std::cout << "Examples:" << std::endl;
        for (UInt k = 0; k < std::min(static_cast<UInt>(5), static_cast<UInt>(related_pairs.size())); ++k) {
            auto [i, j] = related_pairs[k];
            std::cout << "  Individuals " << i << " - " << j
                      << ": G = " << grm(i, j) << std::endl;
        }
    }

    return related_pairs;
}

} // namespace genomic
