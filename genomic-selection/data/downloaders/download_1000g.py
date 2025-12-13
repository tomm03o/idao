#!/usr/bin/env python3
"""
Download 1000 Genomes Phase 3 LD reference panel.

1000G provides population-specific genotypes for constructing
LD matrices required for LDpred2.

Data source: https://www.internationalgenome.org/
"""

import os
import sys
import requests
from pathlib import Path
from tqdm import tqdm
import subprocess


class ThousandGenomes_Downloader:
    """Download 1000 Genomes Phase 3 data for LD reference."""

    # PLINK formatted files from Broad Institute
    BASE_URL = "https://data.broadinstitute.org/alkesgroup/LDSCORE/"

    POPULATIONS = {
        'EUR': 'European (recommended for UK Biobank validation)',
        'EAS': 'East Asian',
        'AFR': 'African',
        'AMR': 'Admixed American',
        'SAS': 'South Asian',
    }

    def __init__(self, output_dir="data/raw/1000g_ld"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_population(self, population='EUR', force=False):
        """
        Download LD reference panel for specific population.

        Args:
            population: One of 'EUR', 'EAS', 'AFR', 'AMR', 'SAS'
            force: Re-download even if files exist
        """
        if population not in self.POPULATIONS:
            raise ValueError(f"Unknown population: {population}")

        print(f"Downloading 1000G Phase 3 - {population}")
        print(f"Description: {self.POPULATIONS[population]}")

        # Download file
        filename = "1000G_Phase3_plinkfiles.tgz"
        url = self.BASE_URL + filename
        output_path = self.output_dir / filename

        if not output_path.exists() or force:
            print(f"Downloading from {url}...")

            response = requests.get(url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))

            with open(output_path, 'wb') as f:
                with tqdm(total=total_size, unit='B', unit_scale=True) as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        pbar.update(len(chunk))

            print(f"✓ Downloaded: {output_path}")
        else:
            print(f"✓ Already downloaded: {output_path}")

        # Extract
        extract_dir = self.output_dir / "1000G_Phase3_plinkfiles"
        if not extract_dir.exists() or force:
            print("Extracting archive...")
            subprocess.run(['tar', '-xzf', str(output_path), '-C', str(self.output_dir)],
                          check=True)
            print(f"✓ Extracted to: {extract_dir}")
        else:
            print(f"✓ Already extracted: {extract_dir}")

        # Validate
        self._validate_plink_files(extract_dir)

        return extract_dir

    def _validate_plink_files(self, directory):
        """Validate PLINK binary files exist."""
        print("Validating PLINK files...")

        # Check for chromosome-wise files
        required_extensions = ['.bed', '.bim', '.fam']

        for chrom in range(1, 23):
            for ext in required_extensions:
                filepath = directory / f"1000G.{population}.QC.{chrom}{ext}"
                if not filepath.exists():
                    print(f"  ✗ Missing: {filepath.name}")
                else:
                    print(f"  ✓ Found: {filepath.name}")

    def download_genetic_map(self, force=False):
        """
        Download genetic recombination map (for simulation and phasing).

        Genetic map is required for:
        - Simulation-based uncertainty quantification
        - Haplotype phasing
        """
        map_url = "https://bochet.gcc.biostat.washington.edu/beagle/genetic_maps/"
        filename = "plink.GRCh37.map.zip"

        output_path = self.output_dir / filename

        if not output_path.exists() or force:
            print(f"Downloading genetic map from {map_url}...")

            response = requests.get(map_url + filename, stream=True)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"✓ Downloaded: {output_path}")

            # Extract
            import zipfile
            with zipfile.ZipFile(output_path, 'r') as zip_ref:
                zip_ref.extractall(self.output_dir / "genetic_maps")

            print(f"✓ Extracted genetic maps")
        else:
            print(f"✓ Genetic map already downloaded")

        return output_path


def main():
    """Main download script."""
    downloader = ThousandGenomes_Downloader()

    print("=" * 80)
    print("1000 Genomes Phase 3 LD Reference Panel Downloader")
    print("=" * 80)
    print()
    print("Available populations:")
    for pop, desc in downloader.POPULATIONS.items():
        print(f"  {pop}: {desc}")
    print()

    # Download European population (default for UK Biobank validation)
    print("Downloading EUR population (recommended for UK Biobank)...")
    downloader.download_population('EUR')

    print("\nDownloading genetic recombination map...")
    downloader.download_genetic_map()

    print("\n" + "=" * 80)
    print("✓ Download complete!")
    print("=" * 80)
    print(f"\nData saved to: {downloader.output_dir}")
    print("\nNext steps:")
    print("1. Use PLINK files to construct LD matrices")
    print("2. Use genetic map for meiosis simulation")


if __name__ == "__main__":
    main()
