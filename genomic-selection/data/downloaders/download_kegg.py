#!/usr/bin/env python3
"""
Download KEGG pathway database using REST API.

KEGG (Kyoto Encyclopedia of Genes and Genomes) provides curated
biological pathways essential for interpretable genomic prediction.

API docs: https://rest.kegg.jp/
"""

import requests
import time
from pathlib import Path
import json
from tqdm import tqdm


class KEGG_Downloader:
    """Download KEGG pathways via REST API."""

    BASE_URL = "https://rest.kegg.jp"

    # Key pathways for growth, size, and metabolic traits
    PRIORITY_PATHWAYS = {
        # Growth and development
        'hsa04150': 'mTOR signaling pathway',
        'hsa04151': 'PI3K-Akt signaling pathway',
        'hsa04910': 'Insulin signaling pathway',
        'hsa04350': 'TGF-beta signaling pathway',
        'hsa04068': 'FoxO signaling pathway',
        'hsa04066': 'HIF-1 signaling pathway',

        # IGF-1 and growth hormone
        'hsa04060': 'Cytokine-cytokine receptor interaction',
        'hsa04630': 'JAK-STAT signaling pathway',

        # Metabolism
        'hsa00010': 'Glycolysis / Gluconeogenesis',
        'hsa00020': 'Citrate cycle (TCA cycle)',
        'hsa00190': 'Oxidative phosphorylation',
        'hsa00500': 'Starch and sucrose metabolism',
        'hsa00564': 'Glycerophospholipid metabolism',

        # Cell cycle and proliferation
        'hsa04110': 'Cell cycle',
        'hsa04115': 'p53 signaling pathway',
        'hsa04510': 'Focal adhesion',

        # Immune and inflammatory (relevant for disease resistance)
        'hsa04620': 'Toll-like receptor signaling pathway',
        'hsa04621': 'NOD-like receptor signaling pathway',
        'hsa04064': 'NF-kappa B signaling pathway',
        'hsa04668': 'TNF signaling pathway',
    }

    def __init__(self, output_dir="data/raw/kegg"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_pathway_info(self, pathway_id):
        """Get pathway information from KEGG."""
        url = f"{self.BASE_URL}/get/{pathway_id}"
        response = requests.get(url)
        response.raise_for_status()
        return response.text

    def parse_pathway_entry(self, entry_text):
        """Parse KEGG pathway entry text format."""
        lines = entry_text.strip().split('\n')

        pathway_data = {
            'id': None,
            'name': None,
            'description': None,
            'genes': [],
            'compounds': [],
            'modules': [],
        }

        current_section = None

        for line in lines:
            if line.startswith('ENTRY'):
                pathway_data['id'] = line.split()[1]

            elif line.startswith('NAME'):
                pathway_data['name'] = line.replace('NAME', '').strip()

            elif line.startswith('DESCRIPTION'):
                pathway_data['description'] = line.replace('DESCRIPTION', '').strip()

            elif line.startswith('GENE'):
                current_section = 'genes'
                # Parse gene line: "GENE    1234  GENE_NAME; description"
                gene_info = line.replace('GENE', '').strip()
                if gene_info:
                    pathway_data['genes'].append(gene_info)

            elif line.startswith(' ' * 12) and current_section == 'genes':
                # Continuation of genes
                pathway_data['genes'].append(line.strip())

        return pathway_data

    def download_pathway(self, pathway_id):
        """Download single pathway."""
        print(f"Downloading {pathway_id}...")

        # Get pathway data
        pathway_text = self.get_pathway_info(pathway_id)
        pathway_data = self.parse_pathway_entry(pathway_text)

        # Get pathway genes
        genes_url = f"{self.BASE_URL}/link/genes/{pathway_id}"
        genes_response = requests.get(genes_url)

        if genes_response.status_code == 200:
            genes = []
            for line in genes_response.text.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        gene_id = parts[1]
                        genes.append(gene_id)

            pathway_data['gene_ids'] = genes

        # Save
        output_file = self.output_dir / f"{pathway_id}.json"
        with open(output_file, 'w') as f:
            json.dump(pathway_data, f, indent=2)

        # Rate limiting (KEGG requests to be polite)
        time.sleep(0.5)

        return pathway_data

    def download_all_priority_pathways(self):
        """Download all priority pathways."""
        print("=" * 80)
        print("Downloading KEGG Priority Pathways")
        print("=" * 80)
        print()

        pathways = {}

        for pathway_id, description in tqdm(self.PRIORITY_PATHWAYS.items(),
                                            desc="Downloading pathways"):
            try:
                pathway_data = self.download_pathway(pathway_id)
                pathways[pathway_id] = pathway_data
                print(f"  ✓ {pathway_id}: {description}")
                print(f"    Genes: {len(pathway_data.get('gene_ids', []))}")

            except Exception as e:
                print(f"  ✗ Failed: {pathway_id} - {e}")

        # Save summary
        summary_file = self.output_dir / "pathways_summary.json"
        with open(summary_file, 'w') as f:
            json.dump({
                'total_pathways': len(pathways),
                'pathways': {
                    pid: {
                        'name': self.PRIORITY_PATHWAYS[pid],
                        'gene_count': len(data.get('gene_ids', []))
                    }
                    for pid, data in pathways.items()
                }
            }, f, indent=2)

        print(f"\n✓ Downloaded {len(pathways)} pathways")
        print(f"✓ Summary saved: {summary_file}")

        return pathways

    def convert_to_gene_sets(self, species='hsa'):
        """
        Convert KEGG pathways to simple gene set format.

        Output format:
        pathway_id\tpathway_name\tgene1\tgene2\tgene3...
        """
        output_file = self.output_dir / f"kegg_genesets_{species}.gmt"

        with open(output_file, 'w') as f:
            for pathway_id in self.PRIORITY_PATHWAYS.keys():
                json_file = self.output_dir / f"{pathway_id}.json"

                if not json_file.exists():
                    continue

                with open(json_file, 'r') as pf:
                    data = json.load(pf)

                # Extract gene symbols from IDs
                genes = []
                for gene_id in data.get('gene_ids', []):
                    # gene_id format: "hsa:1234" -> extract "1234"
                    if ':' in gene_id:
                        genes.append(gene_id.split(':')[1])

                if genes:
                    name = self.PRIORITY_PATHWAYS[pathway_id]
                    f.write(f"{pathway_id}\t{name}\t" + "\t".join(genes) + "\n")

        print(f"✓ Gene sets saved: {output_file}")
        return output_file

    def download_ortholog_mapping(self, source_species='hsa', target_species='bta'):
        """
        Download ortholog mapping between species.

        Args:
            source_species: Source organism code (hsa=human)
            target_species: Target organism code (bta=cattle, cfa=dog, eca=horse)
        """
        print(f"Downloading ortholog mapping: {source_species} → {target_species}")

        url = f"{self.BASE_URL}/link/{source_species}/{target_species}"
        response = requests.get(url)

        if response.status_code == 200:
            output_file = self.output_dir / f"orthologs_{source_species}_{target_species}.tsv"

            with open(output_file, 'w') as f:
                f.write("source_gene\ttarget_gene\n")
                f.write(response.text)

            print(f"✓ Orthologs saved: {output_file}")
            return output_file
        else:
            print(f"✗ Failed to download orthologs: {response.status_code}")
            return None


def main():
    """Main download script."""
    downloader = KEGG_Downloader()

    print("=" * 80)
    print("KEGG Pathway Database Downloader")
    print("=" * 80)
    print()
    print(f"Downloading {len(downloader.PRIORITY_PATHWAYS)} priority pathways:")
    for pid, name in downloader.PRIORITY_PATHWAYS.items():
        print(f"  {pid}: {name}")
    print()

    # Download pathways
    downloader.download_all_priority_pathways()

    # Convert to gene sets
    print("\nConverting to gene set format...")
    downloader.convert_to_gene_sets()

    # Download ortholog mappings for key species
    print("\nDownloading ortholog mappings...")
    for species_code, species_name in [('bta', 'cattle'), ('cfa', 'dog'), ('eca', 'horse')]:
        try:
            downloader.download_ortholog_mapping('hsa', species_code)
        except Exception as e:
            print(f"  ✗ Failed for {species_name}: {e}")

    print("\n" + "=" * 80)
    print("✓ Download complete!")
    print("=" * 80)
    print(f"\nData saved to: {downloader.output_dir}")


if __name__ == "__main__":
    main()
