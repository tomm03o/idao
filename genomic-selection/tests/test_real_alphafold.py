#!/usr/bin/env python3
"""
Test Reverse Structural Mapping with REAL AlphaFold Data

Downloads actual β-Casein structure from AlphaFold DB and
performs reverse mapping to genomic coordinates.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from structure.reverse_mapping import ProteinStructureAnalyzer
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_real_alphafold_download():
    """Test downloading real AlphaFold structure."""

    logger.info("=" * 80)
    logger.info("TEST 1: Real AlphaFold Structure Download")
    logger.info("=" * 80)

    # Initialize analyzer
    analyzer = ProteinStructureAnalyzer(
        cache_dir=Path("data/structures")
    )

    # Test with β-Casein (P02666 - cattle milk protein)
    logger.info("\nDownloading β-Casein (CSN2) structure from AlphaFold DB...")
    logger.info("UniProt ID: P02666 (Bos taurus)")

    pdb_file = analyzer.get_alphafold_structure("P02666")

    if pdb_file:
        logger.info(f"\n✓ SUCCESS: Downloaded structure to {pdb_file}")

        # Check file size
        size_mb = pdb_file.stat().st_size / (1024 * 1024)
        logger.info(f"  File size: {size_mb:.2f} MB")

        # Read first few lines
        with open(pdb_file, 'r') as f:
            lines = f.readlines()[:20]

        logger.info(f"  Total lines: ~{len(lines)*10}")
        logger.info("\n  First few lines:")
        for line in lines[:5]:
            logger.info(f"    {line.strip()}")

        return True
    else:
        logger.error("✗ FAILED: Could not download structure")
        return False


def test_functional_annotations():
    """Test getting functional annotations from UniProt."""

    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Functional Annotations from UniProt")
    logger.info("=" * 80)

    analyzer = ProteinStructureAnalyzer()

    logger.info("\nFetching functional annotations for β-Casein...")
    domains = analyzer.get_functional_annotations("P02666")

    if domains:
        logger.info(f"\n✓ SUCCESS: Found {len(domains)} functional domains")

        logger.info("\nDomain details:")
        for i, domain in enumerate(domains[:10], 1):
            logger.info(f"\n{i}. {domain.name}")
            logger.info(f"   Type: {domain.domain_type}")
            logger.info(f"   Positions: {domain.aa_positions[0]}-{domain.aa_positions[-1]} ({len(domain.aa_positions)} aa)")
            logger.info(f"   Importance: {domain.importance_score:.2f}")
            logger.info(f"   Description: {domain.description}")

        return True
    else:
        logger.warning("No functional domains found (might be normal for some proteins)")
        return False


def test_structure_analysis():
    """Test structural analysis with pLDDT scores."""

    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: Structural Analysis (High-Confidence Residues)")
    logger.info("=" * 80)

    analyzer = ProteinStructureAnalyzer()

    # Get structure
    pdb_file = analyzer.get_alphafold_structure("P02666")

    if not pdb_file:
        logger.error("Structure not available")
        return False

    logger.info(f"\nAnalyzing structure: {pdb_file}")

    # Identify critical residues
    critical_residues = analyzer.identify_critical_residues_structural(
        pdb_file,
        min_confidence=70.0
    )

    logger.info(f"\n✓ Found {len(critical_residues)} high-confidence residues (pLDDT ≥ 70)")

    if len(critical_residues) > 0:
        logger.info(f"\nFirst 20 critical positions: {critical_residues[:20]}")
        logger.info(f"Last 20 critical positions: {critical_residues[-20:]}")

        # Statistics
        logger.info(f"\nStatistics:")
        logger.info(f"  Min position: {min(critical_residues)}")
        logger.info(f"  Max position: {max(critical_residues)}")
        logger.info(f"  Coverage: {len(critical_residues)}/{max(critical_residues)} residues")

        return True
    else:
        logger.warning("No high-confidence residues found")
        return False


def test_multiple_proteins():
    """Test with multiple milk proteins."""

    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: Multiple Milk Proteins")
    logger.info("=" * 80)

    analyzer = ProteinStructureAnalyzer()

    milk_proteins = {
        'CSN2': 'P02666',   # β-Casein
        'LALBA': 'P00711',  # α-Lactalbumin
        'LGB': 'P02754',    # β-Lactoglobulin
    }

    results = {}

    for protein_name, uniprot_id in milk_proteins.items():
        logger.info(f"\n{protein_name} ({uniprot_id}):")

        try:
            # Download structure
            pdb_file = analyzer.get_alphafold_structure(uniprot_id)

            if pdb_file:
                logger.info(f"  ✓ Structure downloaded")

                # Get annotations
                domains = analyzer.get_functional_annotations(uniprot_id)
                logger.info(f"  ✓ Functional domains: {len(domains)}")

                # Analyze structure
                critical = analyzer.identify_critical_residues_structural(pdb_file)
                logger.info(f"  ✓ Critical residues: {len(critical)}")

                results[protein_name] = {
                    'pdb': pdb_file,
                    'domains': len(domains),
                    'critical_residues': len(critical)
                }
            else:
                logger.warning(f"  ✗ Structure not available")
                results[protein_name] = None

        except Exception as e:
            logger.error(f"  ✗ Error: {e}")
            results[protein_name] = None

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY:")
    for protein, data in results.items():
        if data:
            logger.info(f"  {protein}: {data['domains']} domains, {data['critical_residues']} critical residues")
        else:
            logger.info(f"  {protein}: FAILED")

    return len([r for r in results.values() if r]) > 0


def main():
    """Run all tests."""

    logger.info("=" * 80)
    logger.info("REAL DATA TESTING: AlphaFold + UniProt Integration")
    logger.info("=" * 80)
    logger.info("")

    tests = [
        ("AlphaFold Download", test_real_alphafold_download),
        ("UniProt Annotations", test_functional_annotations),
        ("Structural Analysis", test_structure_analysis),
        ("Multiple Proteins", test_multiple_proteins),
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            success = test_func()
            results[test_name] = success
        except Exception as e:
            logger.error(f"\n✗ {test_name} FAILED with exception: {e}")
            results[test_name] = False

    # Final summary
    logger.info("\n" + "=" * 80)
    logger.info("FINAL RESULTS:")
    logger.info("=" * 80)

    for test_name, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        logger.info(f"  {status}: {test_name}")

    passed = sum(1 for s in results.values() if s)
    total = len(results)

    logger.info(f"\nPassed: {passed}/{total}")

    if passed == total:
        logger.info("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        logger.warning(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
