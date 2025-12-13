"""
Genotype file I/O for VCF and PLINK formats.

Supports reading real genomic data from:
- VCF (Variant Call Format) - standard for SNP genotypes
- PLINK binary (.bed/.bim/.fam) - efficient for large datasets
- PLINK text (.ped/.map) - human-readable format
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple, List, Optional
import logging

try:
    import cyvcf2
    HAS_CYVCF2 = True
except ImportError:
    HAS_CYVCF2 = False
    logging.warning("cyvcf2 not installed, VCF reading will be slow")

try:
    from bed_reader import open_bed
    HAS_BED_READER = True
except ImportError:
    HAS_BED_READER = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GenotypeReader:
    """Read genotype data from various formats."""

    @staticmethod
    def read_vcf(
        vcf_file: Path,
        chrom: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None
    ) -> Tuple[np.ndarray, pd.DataFrame, List[str]]:
        """
        Read genotypes from VCF file.

        Args:
            vcf_file: Path to VCF file (.vcf or .vcf.gz)
            chrom: Filter to specific chromosome
            start: Start position (bp)
            end: End position (bp)

        Returns:
            (genotypes, variant_info, sample_ids)
            - genotypes: numpy array (n_samples × n_variants), values in {0, 1, 2, 255}
                        255 = missing genotype
            - variant_info: DataFrame with columns [CHROM, POS, ID, REF, ALT, QUAL, FILTER]
            - sample_ids: List of sample IDs
        """
        logger.info(f"Reading VCF: {vcf_file}")

        if not HAS_CYVCF2:
            raise ImportError("cyvcf2 required for VCF reading. Install with: pip install cyvcf2")

        vcf = cyvcf2.VCF(str(vcf_file))

        # Get sample IDs
        sample_ids = vcf.samples

        genotypes_list = []
        variant_info_list = []

        # Read variants
        for variant in vcf:
            # Filter by region if specified
            if chrom and variant.CHROM != chrom:
                continue
            if start and variant.POS < start:
                continue
            if end and variant.POS > end:
                break

            # Extract genotypes
            gt = variant.gt_types  # 0=HOM_REF, 1=HET, 2=HOM_ALT, 3=UNKNOWN

            # Convert to dosage (0, 1, 2, 255)
            gt_dosage = np.where(gt == 3, 255, gt).astype(np.uint8)

            genotypes_list.append(gt_dosage)

            # Store variant info
            variant_info_list.append({
                'CHROM': variant.CHROM,
                'POS': variant.POS,
                'ID': variant.ID or f"{variant.CHROM}:{variant.POS}",
                'REF': variant.REF,
                'ALT': ','.join(variant.ALT) if variant.ALT else '.',
                'QUAL': variant.QUAL,
                'FILTER': variant.FILTER or 'PASS'
            })

        # Convert to numpy array
        genotypes = np.array(genotypes_list).T  # Transpose to n_samples × n_variants

        variant_info = pd.DataFrame(variant_info_list)

        logger.info(f"  Samples: {len(sample_ids)}")
        logger.info(f"  Variants: {len(variant_info)}")
        logger.info(f"  Genotype matrix shape: {genotypes.shape}")

        return genotypes, variant_info, sample_ids

    @staticmethod
    def read_plink_bed(
        bed_file: Path
    ) -> Tuple[np.ndarray, pd.DataFrame, pd.DataFrame]:
        """
        Read PLINK binary format (.bed/.bim/.fam).

        Most efficient format for large genotype datasets.

        Args:
            bed_file: Path to .bed file (assumes .bim and .fam in same directory)

        Returns:
            (genotypes, bim, fam)
            - genotypes: numpy array (n_samples × n_variants)
            - bim: DataFrame with variant info [CHR, SNP, CM, POS, A1, A2]
            - fam: DataFrame with sample info [FID, IID, PID, MID, SEX, PHENO]
        """
        logger.info(f"Reading PLINK bed: {bed_file}")

        bed_path = Path(bed_file)
        bim_path = bed_path.with_suffix('.bim')
        fam_path = bed_path.with_suffix('.fam')

        # Check files exist
        for filepath in [bed_path, bim_path, fam_path]:
            if not filepath.exists():
                raise FileNotFoundError(f"Missing file: {filepath}")

        if HAS_BED_READER:
            # Use fast bed_reader
            with open_bed(str(bed_path)) as bed:
                genotypes = bed.read(dtype=np.uint8)
        else:
            # Fallback: manual parsing (slower)
            genotypes = GenotypeReader._read_bed_manual(bed_path)

        # Read .bim (variant info)
        bim = pd.read_csv(
            bim_path,
            sep='\t',
            header=None,
            names=['CHR', 'SNP', 'CM', 'POS', 'A1', 'A2']
        )

        # Read .fam (sample info)
        fam = pd.read_csv(
            fam_path,
            sep=r'\s+',
            header=None,
            names=['FID', 'IID', 'PID', 'MID', 'SEX', 'PHENO']
        )

        logger.info(f"  Samples: {len(fam)}")
        logger.info(f"  Variants: {len(bim)}")
        logger.info(f"  Genotype matrix shape: {genotypes.shape}")

        return genotypes, bim, fam

    @staticmethod
    def _read_bed_manual(bed_path: Path) -> np.ndarray:
        """
        Manual PLINK .bed parser (fallback if bed_reader not available).

        .bed format:
        - Header: 3 bytes (magic number 0x6C 0x1B, mode byte)
        - Data: 2 bits per genotype, packed 4 genotypes per byte
        """
        with open(bed_path, 'rb') as f:
            # Read header
            magic = f.read(2)
            if magic != b'\x6c\x1b':
                raise ValueError("Invalid .bed file (bad magic number)")

            mode = f.read(1)
            if mode != b'\x01':
                raise ValueError("Only SNP-major mode supported")

            # Read genotype data
            bed_data = np.fromfile(f, dtype=np.uint8)

        # Decode genotypes
        # PLINK encoding: 00=HOM_ALT, 01=missing, 10=HET, 11=HOM_REF
        # We want: 0=HOM_REF, 1=HET, 2=HOM_ALT, 255=missing

        # This is complex bit manipulation - refer to PLINK documentation
        # For production, use bed_reader library instead

        logger.warning("Manual .bed parsing not fully implemented - install bed_reader")
        raise NotImplementedError("Install bed_reader: pip install bed-reader")

    @staticmethod
    def write_plink_bed(
        genotypes: np.ndarray,
        bim: pd.DataFrame,
        fam: pd.DataFrame,
        output_prefix: Path
    ):
        """
        Write genotypes to PLINK binary format.

        Args:
            genotypes: Genotype matrix (n_samples × n_variants)
            bim: Variant info DataFrame
            fam: Sample info DataFrame
            output_prefix: Output file prefix (will create .bed/.bim/.fam)
        """
        output_prefix = Path(output_prefix)

        # Write .bim
        bim_path = output_prefix.with_suffix('.bim')
        bim.to_csv(bim_path, sep='\t', header=False, index=False)

        # Write .fam
        fam_path = output_prefix.with_suffix('.fam')
        fam.to_csv(fam_path, sep='\t', header=False, index=False)

        # Write .bed
        bed_path = output_prefix.with_suffix('.bed')

        if HAS_BED_READER:
            with open_bed(str(bed_path), 'w') as bed:
                bed.write(genotypes)
        else:
            raise NotImplementedError("Install bed_reader for writing .bed files")

        logger.info(f"Written PLINK files: {output_prefix}.{{bed,bim,fam}}")


class GWASReader:
    """Read GWAS summary statistics."""

    @staticmethod
    def read_gwas(
        gwas_file: Path,
        format: str = 'auto'
    ) -> pd.DataFrame:
        """
        Read GWAS summary statistics.

        Supports multiple formats:
        - UK Biobank (variant, chr, pos, ref, alt, beta, se, pval, n_complete_samples)
        - PLINK --assoc (CHR, SNP, BP, A1, TEST, NMISS, BETA, SE, P)
        - BOLT-LMM (SNP, CHR, BP, GENPOS, ALLELE1, ALLELE0, BETA, SE, P_BOLT_LMM)
        - Standard (CHR, POS, SNP, A1, A2, BETA, SE, P, N)

        Args:
            gwas_file: Path to GWAS file
            format: 'auto', 'ukb', 'plink', 'bolt', 'standard'

        Returns:
            DataFrame with standardized columns: CHR, POS, SNP, A1, A2, BETA, SE, P, N
        """
        logger.info(f"Reading GWAS: {gwas_file}")

        # Read file
        if gwas_file.suffix == '.gz':
            df = pd.read_csv(gwas_file, sep='\t', compression='gzip')
        else:
            df = pd.read_csv(gwas_file, sep='\t')

        logger.info(f"  Loaded {len(df)} variants")

        # Auto-detect format
        if format == 'auto':
            if 'variant' in df.columns and 'n_complete_samples' in df.columns:
                format = 'ukb'
            elif 'P_BOLT_LMM' in df.columns:
                format = 'bolt'
            elif 'TEST' in df.columns:
                format = 'plink'
            else:
                format = 'standard'

        logger.info(f"  Detected format: {format}")

        # Standardize columns
        if format == 'ukb':
            df_std = pd.DataFrame({
                'CHR': df['chr'],
                'POS': df['pos'],
                'SNP': df['variant'],
                'A1': df['alt'],  # Effect allele
                'A2': df['ref'],
                'BETA': df['beta'],
                'SE': df['se'],
                'P': df['pval'],
                'N': df['n_complete_samples']
            })

        elif format == 'bolt':
            df_std = pd.DataFrame({
                'CHR': df['CHR'],
                'POS': df['BP'],
                'SNP': df['SNP'],
                'A1': df['ALLELE1'],
                'A2': df['ALLELE0'],
                'BETA': df['BETA'],
                'SE': df['SE'],
                'P': df['P_BOLT_LMM'],
                'N': len(df)  # Approximation
            })

        elif format == 'plink':
            df_std = pd.DataFrame({
                'CHR': df['CHR'],
                'POS': df['BP'],
                'SNP': df['SNP'],
                'A1': df['A1'],
                'A2': df.get('A2', 'N'),
                'BETA': df['BETA'],
                'SE': df['SE'],
                'P': df['P'],
                'N': df['NMISS']
            })

        else:  # standard
            required = ['CHR', 'POS', 'SNP', 'A1', 'A2', 'BETA', 'SE', 'P']
            missing = [col for col in required if col not in df.columns]
            if missing:
                raise ValueError(f"Missing required columns: {missing}")

            df_std = df[required + (['N'] if 'N' in df.columns else [])]

        # Quality control
        df_std = df_std.dropna()
        df_std = df_std[df_std['P'] > 0]  # Remove invalid p-values
        df_std = df_std[df_std['SE'] > 0]  # Remove invalid SEs

        logger.info(f"  After QC: {len(df_std)} variants")

        return df_std
