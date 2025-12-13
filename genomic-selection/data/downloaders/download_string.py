#!/usr/bin/env python3
"""
Download STRING protein-protein interaction network database.

STRING provides experimentally validated and computationally
predicted protein interactions, essential for PathwayGNN.

Data source: https://string-db.org/
"""

import requests
from pathlib import Path
from tqdm import tqdm
import gzip
import pandas as pd


class STRING_Downloader:
    """Download STRING protein interaction networks."""

    BASE_URL = "https://stringdb-downloads.org/download"
    VERSION = "v12.0"

    # NCBI Taxonomy IDs for key species
    SPECIES = {
        'human': {'taxid': 9606, 'name': 'Homo sapiens'},
        'cattle': {'taxid': 9913, 'name': 'Bos taurus'},
        'dog': {'taxid': 9615, 'name': 'Canis lupus familiaris'},
        'horse': {'taxid': 9796, 'name': 'Equus caballus'},
        'pig': {'taxid': 9823, 'name': 'Sus scrofa'},
        'mouse': {'taxid': 10090, 'name': 'Mus musculus'},
    }

    def __init__(self, output_dir="data/raw/string"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_interactions(self, species='human', score_threshold=400, force=False):
        """
        Download protein-protein interaction network.

        Args:
            species: One of 'human', 'cattle', 'dog', 'horse', 'pig', 'mouse'
            score_threshold: Minimum interaction score (0-1000, recommend 400=medium confidence)
            force: Re-download even if exists
        """
        if species not in self.SPECIES:
            raise ValueError(f"Unknown species: {species}")

        taxid = self.SPECIES[species]['taxid']
        species_name = self.SPECIES[species]['name']

        print(f"Downloading STRING interactions for {species_name} (taxid={taxid})")

        # Construct URL
        filename = f"{taxid}.protein.links.{self.VERSION}.txt.gz"
        url = f"{self.BASE_URL}/protein.links.{self.VERSION}/{filename}"

        output_path = self.output_dir / filename

        if output_path.exists() and not force:
            print(f"✓ Already downloaded: {output_path}")
            return output_path

        # Download
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

        # Filter by score threshold
        self._filter_interactions(output_path, score_threshold, species)

        return output_path

    def _filter_interactions(self, filepath, score_threshold, species):
        """Filter interactions by confidence score."""
        print(f"Filtering interactions (score >= {score_threshold})...")

        output_file = self.output_dir / f"{species}_interactions_filtered.tsv"

        # Read and filter
        df = pd.read_csv(filepath, sep=' ', compression='gzip')

        print(f"  Total interactions: {len(df):,}")

        # Filter by combined score
        df_filtered = df[df['combined_score'] >= score_threshold]

        print(f"  After filtering: {len(df_filtered):,}")

        # Save filtered
        df_filtered.to_csv(output_file, sep='\t', index=False)

        print(f"✓ Filtered interactions saved: {output_file}")

        # Print statistics
        print(f"\nInteraction statistics:")
        print(f"  Mean score: {df_filtered['combined_score'].mean():.1f}")
        print(f"  Median score: {df_filtered['combined_score'].median():.1f}")
        print(f"  Unique proteins: {pd.concat([df_filtered['protein1'], df_filtered['protein2']]).nunique():,}")

        return output_file

    def download_protein_info(self, species='human', force=False):
        """
        Download protein information (IDs, names, annotations).

        This provides mapping from STRING IDs to gene names.
        """
        if species not in self.SPECIES:
            raise ValueError(f"Unknown species: {species}")

        taxid = self.SPECIES[species]['taxid']

        print(f"Downloading protein info for {species}...")

        filename = f"{taxid}.protein.info.{self.VERSION}.txt.gz"
        url = f"{self.BASE_URL}/protein.info.{self.VERSION}/{filename}"

        output_path = self.output_dir / filename

        if output_path.exists() and not force:
            print(f"✓ Already downloaded: {output_path}")
            return output_path

        # Download
        response = requests.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))

        with open(output_path, 'wb') as f:
            with tqdm(total=total_size, unit='B', unit_scale=True) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    pbar.update(len(chunk))

        print(f"✓ Downloaded: {output_path}")

        # Create ID mapping
        self._create_id_mapping(output_path, species)

        return output_path

    def _create_id_mapping(self, filepath, species):
        """Create mapping from STRING IDs to gene names."""
        print("Creating STRING ID → gene name mapping...")

        df = pd.read_csv(filepath, sep='\t', compression='gzip')

        # Extract preferred name (usually gene symbol)
        mapping = df[['protein_external_id', 'preferred_name']].copy()
        mapping.columns = ['string_id', 'gene_name']

        output_file = self.output_dir / f"{species}_id_mapping.tsv"
        mapping.to_csv(output_file, sep='\t', index=False)

        print(f"✓ ID mapping saved: {output_file}")
        print(f"  Total proteins: {len(mapping):,}")

        return output_file

    def convert_to_edge_list(self, species='human'):
        """
        Convert STRING network to simple edge list for GNN.

        Output format: gene1 gene2 score
        """
        interactions_file = self.output_dir / f"{species}_interactions_filtered.tsv"
        mapping_file = self.output_dir / f"{species}_id_mapping.tsv"

        if not interactions_file.exists():
            print(f"✗ Missing interactions file for {species}")
            return None

        if not mapping_file.exists():
            print(f"✗ Missing ID mapping file for {species}")
            return None

        print(f"Converting {species} network to edge list...")

        # Load data
        interactions = pd.read_csv(interactions_file, sep='\t')
        mapping = pd.read_csv(mapping_file, sep='\t')

        # Create mapping dict
        id_to_gene = dict(zip(mapping['string_id'], mapping['gene_name']))

        # Convert STRING IDs to gene names
        interactions['gene1'] = interactions['protein1'].map(id_to_gene)
        interactions['gene2'] = interactions['protein2'].map(id_to_gene)

        # Remove unmapped
        interactions = interactions.dropna(subset=['gene1', 'gene2'])

        # Create edge list
        edge_list = interactions[['gene1', 'gene2', 'combined_score']].copy()

        # Normalize scores to [0, 1]
        edge_list['score'] = edge_list['combined_score'] / 1000.0

        output_file = self.output_dir / f"{species}_edgelist.tsv"
        edge_list.to_csv(output_file, sep='\t', index=False)

        print(f"✓ Edge list saved: {output_file}")
        print(f"  Edges: {len(edge_list):,}")
        print(f"  Nodes: {len(set(edge_list['gene1']) | set(edge_list['gene2'])):,}")

        return output_file


def main():
    """Main download script."""
    downloader = STRING_Downloader()

    print("=" * 80)
    print("STRING Protein-Protein Interaction Network Downloader")
    print("=" * 80)
    print()

    # Download for key species
    priority_species = ['human', 'cattle', 'dog']

    for species in priority_species:
        print(f"\n{'='*80}")
        print(f"Downloading {species.upper()} network")
        print('='*80)

        try:
            # Download interactions
            downloader.download_interactions(species, score_threshold=400)

            # Download protein info
            downloader.download_protein_info(species)

            # Convert to edge list
            downloader.convert_to_edge_list(species)

        except Exception as e:
            print(f"✗ Failed for {species}: {e}")

    print("\n" + "=" * 80)
    print("✓ Download complete!")
    print("=" * 80)
    print(f"\nData saved to: {downloader.output_dir}")
    print("\nNext steps:")
    print("1. Use edge lists to construct GNN graphs")
    print("2. Integrate with KEGG pathways for pathway-specific networks")


if __name__ == "__main__":
    main()
