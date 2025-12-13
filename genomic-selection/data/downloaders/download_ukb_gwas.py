#!/usr/bin/env python3
"""
Download UK Biobank GWAS summary statistics for algorithm validation.

UK Biobank provides GWAS for hundreds of phenotypes with n~500K samples.
These are ideal for validating our LDpred2 implementation.

Data source: https://broad-ukb-sumstats-us-east-1.s3.amazonaws.com/
"""

import os
import sys
import requests
from pathlib import Path
from tqdm import tqdm
import gzip
import pandas as pd


class UKBiobank_Downloader:
    """Download and process UK Biobank GWAS summary statistics."""

    BASE_URL = "https://broad-ukb-sumstats-us-east-1.s3.amazonaws.com/round2/additive-tsvs/"

    # Key phenotypes for validation
    PHENOTYPES = {
        'height': {
            'code': '50_irnt',
            'description': 'Standing height (highly heritable, well-studied)',
            'h2': 0.7,  # SNP heritability ~70%
        },
        'bmi': {
            'code': '21001_irnt',
            'description': 'Body mass index',
            'h2': 0.3,
        },
        'weight': {
            'code': '21002_irnt',
            'description': 'Weight (analogous to animal growth traits)',
            'h2': 0.5,
        },
        'cholesterol': {
            'code': '30690_irnt',
            'description': 'Cholesterol (metabolic trait)',
            'h2': 0.4,
        },
    }

    def __init__(self, output_dir="data/raw/ukb_gwas"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_phenotype(self, phenotype_name, force=False):
        """
        Download GWAS summary statistics for a specific phenotype.

        Args:
            phenotype_name: One of 'height', 'bmi', 'weight', 'cholesterol'
            force: Re-download even if file exists
        """
        if phenotype_name not in self.PHENOTYPES:
            raise ValueError(f"Unknown phenotype: {phenotype_name}")

        pheno = self.PHENOTYPES[phenotype_name]
        filename = f"{pheno['code']}.gwas.imputed_v3.both_sexes.tsv.bgz"
        url = self.BASE_URL + filename
        output_path = self.output_dir / filename

        # Check if already downloaded
        if output_path.exists() and not force:
            print(f"✓ {phenotype_name} already downloaded: {output_path}")
            return output_path

        print(f"Downloading {phenotype_name} GWAS ({pheno['description']})...")
        print(f"URL: {url}")
        print(f"Expected h²: {pheno['h2']}")

        # Stream download with progress bar
        response = requests.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))

        with open(output_path, 'wb') as f:
            with tqdm(total=total_size, unit='B', unit_scale=True) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    pbar.update(len(chunk))

        print(f"✓ Downloaded: {output_path}")

        # Validate file
        self._validate_gwas(output_path)

        return output_path

    def _validate_gwas(self, filepath):
        """Validate GWAS file format and content."""
        print(f"Validating {filepath.name}...")

        # Read first few lines
        with gzip.open(filepath, 'rt') as f:
            header = f.readline().strip().split('\t')
            first_line = f.readline().strip().split('\t')

        # Check required columns
        required_cols = ['variant', 'chr', 'pos', 'ref', 'alt', 'beta', 'se', 'pval', 'n_complete_samples']
        missing = [col for col in required_cols if col not in header]

        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        print(f"  ✓ Header valid: {len(header)} columns")
        print(f"  ✓ Required columns present")
        print(f"  ✓ First variant: {first_line[header.index('variant')]}")

    def download_all(self):
        """Download all key phenotypes."""
        for pheno_name in self.PHENOTYPES.keys():
            try:
                self.download_phenotype(pheno_name)
            except Exception as e:
                print(f"✗ Failed to download {pheno_name}: {e}")

    def convert_to_ldpred_format(self, phenotype_name):
        """
        Convert UK Biobank format to LDpred2 input format.

        LDpred expects:
        - CHR: Chromosome
        - POS: Position
        - SNP: Variant ID
        - A1: Effect allele
        - A2: Reference allele
        - BETA: Effect size
        - SE: Standard error
        - P: P-value
        - N: Sample size
        """
        pheno = self.PHENOTYPES[phenotype_name]
        input_file = self.output_dir / f"{pheno['code']}.gwas.imputed_v3.both_sexes.tsv.bgz"
        output_file = self.output_dir / f"{phenotype_name}_ldpred_format.tsv"

        if not input_file.exists():
            raise FileNotFoundError(f"Please download {phenotype_name} first")

        print(f"Converting {phenotype_name} to LDpred format...")

        # Read GWAS
        df = pd.read_csv(input_file, sep='\t', compression='gzip')

        # Convert to LDpred format
        ldpred_df = pd.DataFrame({
            'CHR': df['chr'],
            'POS': df['pos'],
            'SNP': df['variant'],
            'A1': df['alt'],  # Effect allele
            'A2': df['ref'],  # Reference allele
            'BETA': df['beta'],
            'SE': df['se'],
            'P': df['pval'],
            'N': df['n_complete_samples']
        })

        # Filter to autosomal chromosomes
        ldpred_df = ldpred_df[ldpred_df['CHR'].isin(range(1, 23))]

        # Remove missing values
        ldpred_df = ldpred_df.dropna()

        # Save
        ldpred_df.to_csv(output_file, sep='\t', index=False)

        print(f"✓ Converted: {output_file}")
        print(f"  Total variants: {len(ldpred_df):,}")
        print(f"  Mean N: {ldpred_df['N'].mean():.0f}")
        print(f"  Genome-wide significant hits (P<5e-8): {(ldpred_df['P'] < 5e-8).sum():,}")

        return output_file


def main():
    """Main download script."""
    downloader = UKBiobank_Downloader()

    print("=" * 80)
    print("UK Biobank GWAS Downloader")
    print("=" * 80)
    print()
    print("This script downloads GWAS summary statistics for:")
    for name, info in downloader.PHENOTYPES.items():
        print(f"  - {name}: {info['description']} (h²≈{info['h2']})")
    print()

    # Download key phenotypes
    print("Downloading phenotypes...")
    downloader.download_all()

    print("\n" + "=" * 80)
    print("Converting to LDpred format...")
    print("=" * 80)

    # Convert to LDpred format
    for pheno_name in downloader.PHENOTYPES.keys():
        try:
            downloader.convert_to_ldpred_format(pheno_name)
        except Exception as e:
            print(f"✗ Failed to convert {pheno_name}: {e}")

    print("\n" + "=" * 80)
    print("✓ Download complete!")
    print("=" * 80)
    print(f"\nData saved to: {downloader.output_dir}")


if __name__ == "__main__":
    main()
