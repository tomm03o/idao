#!/usr/bin/env python3
"""
GPU Training Script Optimized for NVIDIA A100

Features:
- Automatic mixed precision (AMP) with bfloat16 (A100 only)
- Flash Attention 2 support
- Tensor Core optimization
- Multi-GPU Distributed Data Parallel (DDP)
- Gradient checkpointing for large models
- Efficient data loading with pinned memory
- TensorBoard logging
- Model checkpointing with automatic resume
- Integration with Weights & Biases (wandb)

Usage:
    # Single GPU
    python scripts/train_gpu_a100.py --config configs/cattle_milk.yaml

    # Multi-GPU (4x A100)
    torchrun --nproc_per_node=4 scripts/train_gpu_a100.py --config configs/cattle_milk.yaml
"""

import os
import sys
from pathlib import Path
import argparse
import yaml
import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models.genomic_transformer import GenomicTransformer, create_genomic_transformer_model
from models.multi_task_trainer import (
    MultiTaskTrainer,
    TrainingConfig,
    GenomicDataset
)

# Optional: Weights & Biases integration
try:
    import wandb
    WANDB_AVAILABLE = True
except ImportError:
    WANDB_AVAILABLE = False
    print("Warning: wandb not available. Install with: pip install wandb")


def setup_distributed():
    """Initialize distributed training."""
    if 'RANK' in os.environ and 'WORLD_SIZE' in os.environ:
        rank = int(os.environ['RANK'])
        world_size = int(os.environ['WORLD_SIZE'])
        local_rank = int(os.environ['LOCAL_RANK'])

        torch.cuda.set_device(local_rank)
        dist.init_process_group(backend='nccl')

        return rank, world_size, local_rank
    else:
        return 0, 1, 0


def cleanup_distributed():
    """Clean up distributed training."""
    if dist.is_initialized():
        dist.destroy_process_group()


def load_simulated_data(
    n_samples: int = 1000,
    n_snps: int = 10000,
    n_tasks: int = 3
) -> tuple:
    """
    Load simulated data for testing.

    In production, replace with real genotype data loader.
    """
    print(f"Loading simulated data: {n_samples} samples, {n_snps} SNPs")

    # Simulate genotypes {0, 1, 2}
    genotypes = np.random.randint(0, 3, size=(n_samples, n_snps), dtype=np.int64)

    # Simulate annotations
    allele_freq = np.random.beta(2, 5, size=n_snps).astype(np.float32)
    functional_class = np.random.randint(0, 10, size=n_snps, dtype=np.int64)
    ld_score = np.random.exponential(10, size=n_snps).astype(np.float32)

    # Structural weights (most SNPs weight=1, some high-priority weight=100)
    structural_weight = np.ones(n_snps, dtype=np.float32)
    n_priority = n_snps // 100
    priority_indices = np.random.choice(n_snps, n_priority, replace=False)
    structural_weight[priority_indices] = 100.0

    distance_to_gene = np.random.exponential(5000, size=n_snps).astype(np.float32)
    positions = np.sort(np.random.randint(1, 100_000_000, size=n_snps))

    # Simulate targets (multi-task)
    task_names = [f'task_{i}' for i in range(n_tasks)]
    targets = {}

    for task_idx, task_name in enumerate(task_names):
        # True causal effect (sparse)
        true_beta = np.zeros(n_snps)
        n_causal = n_snps // 20  # 5% causal
        causal_indices = np.random.choice(n_snps, n_causal, replace=False)
        true_beta[causal_indices] = np.random.randn(n_causal) * 0.1

        # Phenotypes = genetic + noise
        genetic = (genotypes * true_beta).sum(axis=1)
        noise = np.random.randn(n_samples) * genetic.std()
        phenotypes = genetic + noise

        # Standardize
        phenotypes = (phenotypes - phenotypes.mean()) / phenotypes.std()

        targets[task_name] = phenotypes.astype(np.float32)

    return (
        genotypes, targets, allele_freq, functional_class,
        ld_score, structural_weight, distance_to_gene, positions
    )


def create_datasets(
    train_split: float = 0.8,
    n_samples: int = 1000,
    n_snps: int = 10000,
    n_tasks: int = 3
) -> tuple:
    """Create train and validation datasets."""
    # Load data
    (genotypes, targets, allele_freq, functional_class,
     ld_score, structural_weight, distance_to_gene, positions) = load_simulated_data(
        n_samples, n_snps, n_tasks
    )

    # Train/val split
    n_train = int(n_samples * train_split)

    train_dataset = GenomicDataset(
        genotypes=genotypes[:n_train],
        targets={task: vals[:n_train] for task, vals in targets.items()},
        allele_freq=allele_freq,
        functional_class=functional_class,
        ld_score=ld_score,
        structural_weight=structural_weight,
        distance_to_gene=distance_to_gene,
        positions=positions
    )

    val_dataset = GenomicDataset(
        genotypes=genotypes[n_train:],
        targets={task: vals[n_train:] for task, vals in targets.items()},
        allele_freq=allele_freq,
        functional_class=functional_class,
        ld_score=ld_score,
        structural_weight=structural_weight,
        distance_to_gene=distance_to_gene,
        positions=positions
    )

    return train_dataset, val_dataset


def main(args):
    """Main training loop."""
    # Distributed setup
    rank, world_size, local_rank = setup_distributed()
    is_main_process = (rank == 0)

    if is_main_process:
        print("=" * 80)
        print("Genomic Transformer Training on NVIDIA A100")
        print("=" * 80)
        print(f"PyTorch version: {torch.__version__}")
        print(f"CUDA version: {torch.version.cuda}")
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"Number of GPUs: {world_size}")
        print(f"Compute capability: {torch.cuda.get_device_capability(0)}")

        # Check for bfloat16 support (A100)
        if torch.cuda.is_bf16_supported():
            print("✓ bfloat16 supported (using for AMP)")
        else:
            print("⚠ bfloat16 not supported (using float16)")

    # Load configuration
    if args.config:
        with open(args.config) as f:
            config_dict = yaml.safe_load(f)
            config = TrainingConfig(**config_dict)
    else:
        config = TrainingConfig(
            d_model=256,
            n_heads=8,
            n_layers=6,
            dim_feedforward=1024,
            batch_size=32,
            n_epochs=100,
            learning_rate=1e-4,
            use_amp=True,
            task_names=['task_0', 'task_1', 'task_2'],
            device=f'cuda:{local_rank}'
        )

    # Wandb logging (main process only)
    if is_main_process and WANDB_AVAILABLE and not args.no_wandb:
        wandb.init(
            project="genomic-embryo-selection",
            config=vars(config),
            name=f"transformer_{config.d_model}d_{config.n_layers}l"
        )

    # Create datasets
    if is_main_process:
        print("\nCreating datasets...")

    train_dataset, val_dataset = create_datasets(
        n_samples=args.n_samples,
        n_snps=args.n_snps,
        n_tasks=len(config.task_names)
    )

    if is_main_process:
        print(f"  Train: {len(train_dataset)} samples")
        print(f"  Val: {len(val_dataset)} samples")

    # Create model
    if is_main_process:
        print("\nCreating model...")

    model = GenomicTransformer(
        d_model=config.d_model,
        n_heads=config.n_heads,
        n_layers=config.n_layers,
        dim_feedforward=config.dim_feedforward,
        n_tasks=len(config.task_names),
        dropout=config.dropout,
        use_checkpointing=True
    )

    # Move to device
    device = torch.device(config.device)
    model = model.to(device)

    # Wrap with DDP for multi-GPU
    if world_size > 1:
        model = DDP(model, device_ids=[local_rank], output_device=local_rank)

    if is_main_process:
        n_params = sum(p.numel() for p in model.parameters())
        print(f"  Parameters: {n_params:,} ({n_params/1e6:.1f}M)")

    # Create trainer
    trainer = MultiTaskTrainer(
        model=model,
        config=config,
        train_dataset=train_dataset,
        val_dataset=val_dataset
    )

    # Resume from checkpoint if specified
    if args.resume:
        epoch = trainer.load_checkpoint(Path(args.resume))
        if is_main_process:
            print(f"\nResumed from epoch {epoch}")

    # Train
    if is_main_process:
        print("\nStarting training...\n")

    history = trainer.train()

    # Save final model
    if is_main_process:
        final_path = config.checkpoint_dir / "final_model.pt"
        torch.save({
            'model_state_dict': model.state_dict(),
            'config': config,
            'history': history
        }, final_path)
        print(f"\nSaved final model: {final_path}")

        if WANDB_AVAILABLE and not args.no_wandb:
            wandb.finish()

    # Cleanup
    cleanup_distributed()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Genomic Transformer on A100")

    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config YAML file'
    )

    parser.add_argument(
        '--resume',
        type=str,
        default=None,
        help='Path to checkpoint to resume from'
    )

    parser.add_argument(
        '--n_samples',
        type=int,
        default=1000,
        help='Number of samples (for testing)'
    )

    parser.add_argument(
        '--n_snps',
        type=int,
        default=10000,
        help='Number of SNPs (for testing)'
    )

    parser.add_argument(
        '--no_wandb',
        action='store_true',
        help='Disable Weights & Biases logging'
    )

    args = parser.parse_args()

    main(args)
