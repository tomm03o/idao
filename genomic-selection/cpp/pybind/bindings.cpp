/**
 * @file bindings.cpp
 * @brief Python bindings for genomic selection C++ core
 *
 * Exposes C++ classes and functions to Python via pybind11
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/eigen.h>

#include "types.h"
#include "ld_matrix.h"
#include "ldpred.h"
#include "grm.h"

namespace py = pybind11;
using namespace genomic;

PYBIND11_MODULE(genomic_core_cpp, m) {
    m.doc() = "High-performance C++ core for genomic selection";

    // ========================================================================
    // Types
    // ========================================================================

    py::class_<SNP>(m, "SNP")
        .def(py::init<>())
        .def_readwrite("id", &SNP::id)
        .def_readwrite("chromosome", &SNP::chromosome)
        .def_readwrite("position", &SNP::position)
        .def_readwrite("allele_ref", &SNP::allele_ref)
        .def_readwrite("allele_alt", &SNP::allele_alt)
        .def_readwrite("beta", &SNP::beta)
        .def_readwrite("se", &SNP::se)
        .def_readwrite("pvalue", &SNP::pvalue)
        .def_readwrite("sample_size", &SNP::sample_size)
        .def_readwrite("maf", &SNP::maf);

    py::class_<GWASData>(m, "GWASData")
        .def(py::init<>())
        .def_readwrite("snps", &GWASData::snps)
        .def_readwrite("total_samples", &GWASData::total_samples)
        .def_readwrite("heritability", &GWASData::heritability);

    py::class_<LDpredParams>(m, "LDpredParams")
        .def(py::init<>())
        .def_readwrite("h2", &LDpredParams::h2)
        .def_readwrite("p", &LDpredParams::p)
        .def_readwrite("n_samples", &LDpredParams::n_samples)
        .def_readwrite("n_iter", &LDpredParams::n_iter)
        .def_readwrite("burn_in", &LDpredParams::burn_in)
        .def_readwrite("shrink", &LDpredParams::shrink);

    py::class_<LDpredResult>(m, "LDpredResult")
        .def(py::init<>())
        .def_readwrite("beta_posterior", &LDpredResult::beta_posterior)
        .def_readwrite("pip", &LDpredResult::pip)
        .def_readwrite("h2_estimate", &LDpredResult::h2_estimate)
        .def_readwrite("polygenicity", &LDpredResult::polygenicity)
        .def_readwrite("mcmc_h2", &LDpredResult::mcmc_h2)
        .def_readwrite("converged", &LDpredResult::converged);

    // ========================================================================
    // LD Matrix Calculator
    // ========================================================================

    py::class_<LDMatrixCalculator>(m, "LDMatrixCalculator")
        .def(py::init<Float, Float>(),
             py::arg("shrinkage") = 0.9,
             py::arg("min_maf") = 0.01,
             R"doc(
                 LD matrix calculator

                 Args:
                     shrinkage: Shrinkage toward identity (default: 0.9)
                     min_maf: Minimum minor allele frequency (default: 0.01)
             )doc")
        .def("compute", &LDMatrixCalculator::compute,
             py::arg("genotypes"),
             R"doc(
                 Compute LD matrix from genotypes

                 Args:
                     genotypes: Genotype matrix (n_individuals × n_snps), values in {0, 1, 2}

                 Returns:
                     LD correlation matrix (n_snps × n_snps)
             )doc")
        .def("compute_windowed", &LDMatrixCalculator::compute_windowed,
             py::arg("genotypes"),
             py::arg("positions"),
             py::arg("window_size") = 3000000,
             R"doc(
                 Compute windowed LD matrix

                 Args:
                     genotypes: Genotype matrix
                     positions: SNP positions in base pairs
                     window_size: Window size in bp (default: 3 Mb)

                 Returns:
                     Sparse LD matrix
             )doc")
        .def("estimate_allele_frequencies", &LDMatrixCalculator::estimate_allele_frequencies,
             py::arg("genotypes"),
             "Estimate allele frequencies from genotype data")
        .def("standardize_genotypes", &LDMatrixCalculator::standardize_genotypes,
             py::arg("genotypes"),
             py::arg("allele_freq"),
             "Standardize genotypes for LD calculation")
        .def("is_positive_definite", &LDMatrixCalculator::is_positive_definite,
             py::arg("ld_matrix"),
             "Check if LD matrix is positive definite")
        .def("regularize", &LDMatrixCalculator::regularize,
             py::arg("ld_matrix"),
             py::arg("min_eigenvalue") = 1e-6,
             "Regularize LD matrix to ensure positive definiteness");

    // ========================================================================
    // LDpred2
    // ========================================================================

    py::class_<LDpred2>(m, "LDpred2")
        .def(py::init<const LDMatrix&, UInt, UInt, UInt>(),
             py::arg("ld_matrix"),
             py::arg("n_iter") = 1000,
             py::arg("burn_in") = 200,
             py::arg("random_seed") = 42,
             R"doc(
                 LDpred2 polygenic scoring

                 Args:
                     ld_matrix: LD correlation matrix
                     n_iter: Number of Gibbs iterations (default: 1000)
                     burn_in: Burn-in iterations (default: 200)
                     random_seed: Random seed for reproducibility
             )doc")
        .def("fit", &LDpred2::fit,
             py::arg("gwas"),
             py::arg("h2"),
             py::arg("p"),
             R"doc(
                 Fit LDpred2 with fixed hyperparameters

                 Args:
                     gwas: GWAS summary statistics
                     h2: SNP heritability
                     p: Polygenicity (proportion of causal SNPs)

                 Returns:
                     LDpredResult with posterior effect sizes
             )doc")
        .def("fit_auto", &LDpred2::fit_auto,
             py::arg("gwas"),
             py::arg("h2_grid"),
             py::arg("p_grid"),
             R"doc(
                 Fit LDpred2-auto with grid search

                 Automatically selects optimal hyperparameters

                 Args:
                     gwas: GWAS summary statistics
                     h2_grid: Grid of h² values (e.g., [0.1, 0.3, 0.5, 0.7])
                     p_grid: Grid of p values (e.g., [0.01, 0.1, 0.3, 1.0])

                 Returns:
                     Best LDpredResult
             )doc")
        .def("predict", &LDpred2::predict,
             py::arg("genotypes"),
             py::arg("beta"),
             R"doc(
                 Predict polygenic scores

                 Args:
                     genotypes: Genotype matrix (n_individuals × n_snps)
                     beta: Effect sizes from fit()

                 Returns:
                     Vector of polygenic scores
             )doc");

    // ========================================================================
    // GRM Calculator
    // ========================================================================

    py::class_<GRMCalculator>(m, "GRMCalculator")
        .def(py::init<Float>(),
             py::arg("min_maf") = 0.01,
             R"doc(
                 Genomic Relationship Matrix calculator

                 Args:
                     min_maf: Minimum minor allele frequency (default: 0.01)
             )doc")
        .def("compute", &GRMCalculator::compute,
             py::arg("genotypes"),
             R"doc(
                 Compute genomic relationship matrix

                 G_ij = genetic similarity between individuals i and j
                 G_ii ≈ 1 + inbreeding coefficient

                 Args:
                     genotypes: Genotype matrix (n_individuals × n_snps)

                 Returns:
                     GRM matrix (n_individuals × n_individuals)
             )doc")
        .def("compute_allele_frequencies", &GRMCalculator::compute_allele_frequencies,
             py::arg("genotypes"),
             "Compute allele frequencies from genotypes")
        .def("center_genotypes", &GRMCalculator::center_genotypes,
             py::arg("genotypes"),
             py::arg("allele_freq"),
             "Center genotypes: X - 2p")
        .def("estimate_inbreeding", &GRMCalculator::estimate_inbreeding,
             py::arg("grm"),
             "Estimate inbreeding coefficients from GRM")
        .def("find_related_pairs", &GRMCalculator::find_related_pairs,
             py::arg("grm"),
             py::arg("threshold") = 0.05,
             "Find related individuals");

    // ========================================================================
    // Utilities
    // ========================================================================

    m.def("version", []() { return "1.0.0"; },
          "Get version string");

    m.def("has_openmp", []() {
        #ifdef _OPENMP
            return true;
        #else
            return false;
        #endif
    }, "Check if compiled with OpenMP support");
}
