from setuptools import setup, find_packages
from pybind11.setup_helpers import Pybind11Extension, build_ext
import os

# Read README
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# C++ extension modules
ext_modules = [
    Pybind11Extension(
        "genomic_selection.genomic_core_cpp",
        [
            "cpp/pybind/bindings.cpp",
            "cpp/src/ld_matrix.cpp",
            "cpp/src/ldpred.cpp",
            "cpp/src/grm.cpp",
            "cpp/src/susie.cpp",
            "cpp/src/utils.cpp",
        ],
        include_dirs=["cpp/include"],
        extra_compile_args=["-O3", "-march=native", "-fopenmp", "-std=c++17"],
        extra_link_args=["-fopenmp"],
    ),
]

setup(
    name="genomic-selection",
    version="1.0.0",
    author="Genomic Selection Platform Team",
    description="Production-grade genomic prediction for embryo selection",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/genomic-selection",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: C++",
    ],
    python_requires=">=3.10",
    install_requires=[
        "numpy>=1.24.0",
        "scipy>=1.10.0",
        "pandas>=2.0.0",
        "torch>=2.0.0",
        "scikit-allel>=1.3.0",
        "pybind11>=2.11.0",
    ],
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    entry_points={
        "console_scripts": [
            "genomic-predict=genomic_selection.cli:main",
        ],
    },
)
