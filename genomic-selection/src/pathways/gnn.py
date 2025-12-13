"""
PathwayGNN: Graph Neural Network for biological pathway modeling

This module implements a GNN that operates on protein-protein interaction networks
to provide pathway-level genomic predictions with biological interpretability.

Key innovation: Instead of treating genes as independent, model them as a GRAPH
where genes are nodes and protein interactions are edges.

Architecture:
    Input: Gene-level variant effects (aggregated from SNPs)
    Graph: Protein-protein interaction network from STRING
    Output: Pathway activation score

This provides:
    - Biological interpretability (which pathways are driving predictions)
    - Better generalization (learns biological mechanisms, not just correlations)
    - Cross-species transfer (same pathways, different genomes)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GCNConv, GATConv, global_mean_pool, global_max_pool
from torch_geometric.data import Data, Batch
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from pathlib import Path


class PathwayGNN(nn.Module):
    """
    Graph Neural Network for pathway-level genomic prediction.

    Nodes: Genes (features = aggregated variant effects in gene)
    Edges: Protein-protein interactions from STRING
    Output: Pathway activation score
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int = 64,
        num_layers: int = 3,
        dropout: float = 0.2,
        aggregation: str = 'mean',
        attention: bool = False
    ):
        """
        Args:
            input_dim: Dimension of gene-level input features
            hidden_dim: Hidden dimension for GNN layers
            num_layers: Number of GNN layers
            dropout: Dropout rate
            aggregation: Global pooling ('mean', 'max', or 'both')
            attention: Use GAT (attention) instead of GCN
        """
        super().__init__()

        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.dropout = dropout
        self.aggregation = aggregation

        # Choose convolution type
        ConvLayer = GATConv if attention else GCNConv

        # Input projection
        self.input_proj = nn.Linear(input_dim, hidden_dim)

        # GNN layers
        self.convs = nn.ModuleList()
        self.batch_norms = nn.ModuleList()

        for i in range(num_layers):
            if attention:
                self.convs.append(GATConv(hidden_dim, hidden_dim, heads=4, concat=False))
            else:
                self.convs.append(GCNConv(hidden_dim, hidden_dim))

            self.batch_norms.append(nn.BatchNorm1d(hidden_dim))

        # Output projection
        output_dim = hidden_dim * 2 if aggregation == 'both' else hidden_dim
        self.fc1 = nn.Linear(output_dim, hidden_dim // 2)
        self.fc2 = nn.Linear(hidden_dim // 2, 1)

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        batch: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Forward pass

        Args:
            x: Node features [num_nodes, input_dim]
            edge_index: Edge indices [2, num_edges]
            batch: Batch assignment [num_nodes] (for batched graphs)

        Returns:
            Pathway score [batch_size, 1]
        """
        # Input projection
        x = self.input_proj(x)
        x = F.relu(x)

        # GNN layers with residual connections
        for i, (conv, bn) in enumerate(zip(self.convs, self.batch_norms)):
            x_residual = x

            x = conv(x, edge_index)
            x = bn(x)
            x = F.relu(x)
            x = F.dropout(x, p=self.dropout, training=self.training)

            # Residual connection
            if i > 0:
                x = x + x_residual

        # Global pooling
        if batch is None:
            batch = torch.zeros(x.size(0), dtype=torch.long, device=x.device)

        if self.aggregation == 'mean':
            x = global_mean_pool(x, batch)
        elif self.aggregation == 'max':
            x = global_max_pool(x, batch)
        elif self.aggregation == 'both':
            x_mean = global_mean_pool(x, batch)
            x_max = global_max_pool(x, batch)
            x = torch.cat([x_mean, x_max], dim=1)
        else:
            raise ValueError(f"Unknown aggregation: {self.aggregation}")

        # Output layers
        x = self.fc1(x)
        x = F.relu(x)
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.fc2(x)

        return x


class PathwayDataset:
    """
    Dataset for pathway-level genomic prediction.

    Aggregates SNP-level effects to gene-level, then constructs
    pathway-specific graphs using STRING PPI network.
    """

    def __init__(
        self,
        kegg_pathways_file: Path,
        string_network_file: Path,
        snp_annotation_file: Path
    ):
        """
        Args:
            kegg_pathways_file: KEGG gene sets (.gmt format)
            string_network_file: STRING edge list (gene1, gene2, score)
            snp_annotation_file: SNP to gene mapping
        """
        self.pathways = self._load_kegg_pathways(kegg_pathways_file)
        self.ppi_network = self._load_string_network(string_network_file)
        self.snp_to_gene = self._load_snp_annotation(snp_annotation_file)

    def _load_kegg_pathways(self, filepath: Path) -> Dict[str, List[str]]:
        """Load KEGG pathways from .gmt file."""
        pathways = {}

        with open(filepath, 'r') as f:
            for line in f:
                parts = line.strip().split('\t')
                pathway_id = parts[0]
                pathway_name = parts[1]
                genes = parts[2:]
                pathways[pathway_id] = {
                    'name': pathway_name,
                    'genes': genes
                }

        print(f"Loaded {len(pathways)} pathways")
        return pathways

    def _load_string_network(self, filepath: Path) -> pd.DataFrame:
        """Load STRING protein-protein interaction network."""
        df = pd.read_csv(filepath, sep='\t')
        print(f"Loaded STRING network: {len(df)} edges")
        return df

    def _load_snp_annotation(self, filepath: Path) -> pd.DataFrame:
        """Load SNP to gene annotation."""
        df = pd.read_csv(filepath, sep='\t')
        print(f"Loaded SNP annotation: {len(df)} SNPs")
        return df

    def aggregate_snps_to_genes(
        self,
        snp_effects: np.ndarray,
        snp_ids: List[str],
        aggregation: str = 'mean'
    ) -> Dict[str, float]:
        """
        Aggregate SNP-level effects to gene-level effects.

        Args:
            snp_effects: Array of SNP effect sizes
            snp_ids: List of SNP IDs
            aggregation: 'mean', 'max', or 'sum'

        Returns:
            Dictionary mapping gene -> aggregated effect
        """
        snp_effect_dict = dict(zip(snp_ids, snp_effects))

        gene_effects = {}

        for gene in self.snp_to_gene['gene'].unique():
            gene_snps = self.snp_to_gene[self.snp_to_gene['gene'] == gene]['snp'].tolist()

            # Get effects for SNPs in this gene
            effects = [snp_effect_dict.get(snp, 0.0) for snp in gene_snps]

            if effects:
                if aggregation == 'mean':
                    gene_effects[gene] = np.mean(effects)
                elif aggregation == 'max':
                    gene_effects[gene] = np.max(np.abs(effects))
                elif aggregation == 'sum':
                    gene_effects[gene] = np.sum(effects)
                else:
                    raise ValueError(f"Unknown aggregation: {aggregation}")

        return gene_effects

    def create_pathway_graph(
        self,
        pathway_id: str,
        gene_effects: Dict[str, float]
    ) -> Data:
        """
        Create PyTorch Geometric graph for a specific pathway.

        Args:
            pathway_id: KEGG pathway ID
            gene_effects: Dictionary of gene -> effect size

        Returns:
            PyTorch Geometric Data object
        """
        pathway = self.pathways[pathway_id]
        pathway_genes = pathway['genes']

        # Filter genes with data
        genes_with_data = [g for g in pathway_genes if g in gene_effects]

        if len(genes_with_data) < 3:
            raise ValueError(f"Pathway {pathway_id} has < 3 genes with data")

        # Create gene to index mapping
        gene_to_idx = {gene: idx for idx, gene in enumerate(genes_with_data)}

        # Node features: gene effects
        x = torch.tensor([gene_effects[g] for g in genes_with_data], dtype=torch.float32)
        x = x.unsqueeze(1)  # [num_genes, 1]

        # Edges: filter PPI network to pathway genes
        edges = []
        edge_weights = []

        for _, row in self.ppi_network.iterrows():
            gene1, gene2 = row['gene1'], row['gene2']

            if gene1 in gene_to_idx and gene2 in gene_to_idx:
                idx1, idx2 = gene_to_idx[gene1], gene_to_idx[gene2]
                edges.append([idx1, idx2])
                edges.append([idx2, idx1])  # Undirected
                edge_weights.extend([row['score'], row['score']])

        if not edges:
            # No edges in pathway: create fully connected graph
            for i in range(len(genes_with_data)):
                for j in range(i + 1, len(genes_with_data)):
                    edges.append([i, j])
                    edges.append([j, i])
                    edge_weights.extend([0.5, 0.5])  # Default weight

        edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()
        edge_attr = torch.tensor(edge_weights, dtype=torch.float32)

        # Create graph
        data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
        data.pathway_id = pathway_id
        data.pathway_name = pathway['name']
        data.genes = genes_with_data

        return data


class PathwayIntegratedPGS:
    """
    Combines traditional PGS with pathway-informed GNN scores.

    Final score = α × PGS_ldpred + (1-α) × Σ(w_p × PathwayGNN_p)
    """

    def __init__(
        self,
        pgs_model,  # LDpred2 model
        pathway_gnns: Dict[str, PathwayGNN],
        pathway_weights: Dict[str, float],
        alpha: float = 0.6
    ):
        """
        Args:
            pgs_model: Fitted LDpred2 model
            pathway_gnns: Dictionary of pathway_id -> trained PathwayGNN
            pathway_weights: Economic weights for each pathway
            alpha: Weight for traditional PGS (1-alpha for pathway scores)
        """
        self.pgs_model = pgs_model
        self.pathway_gnns = pathway_gnns
        self.pathway_weights = pathway_weights
        self.alpha = alpha

    def predict(
        self,
        genotypes: np.ndarray,
        gene_effects: Dict[str, float],
        pathway_graphs: Dict[str, Data]
    ) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """
        Predict with combined PGS + pathway scores.

        Args:
            genotypes: Genotype matrix
            gene_effects: Gene-level effect estimates
            pathway_graphs: Pathway graphs

        Returns:
            (final_scores, pathway_scores_dict)
        """
        # Traditional PGS
        pgs = self.pgs_model.predict(genotypes)

        # Pathway scores
        pathway_scores = {}

        for pathway_id, gnn in self.pathway_gnns.items():
            if pathway_id not in pathway_graphs:
                continue

            graph = pathway_graphs[pathway_id]

            with torch.no_grad():
                gnn.eval()
                score = gnn(graph.x, graph.edge_index).item()
                pathway_scores[pathway_id] = score

        # Weighted combination
        pathway_contribution = sum(
            self.pathway_weights.get(pid, 0.0) * score
            for pid, score in pathway_scores.items()
        )

        final_scores = self.alpha * pgs + (1 - self.alpha) * pathway_contribution

        return final_scores, pathway_scores


def train_pathway_gnn(
    gnn: PathwayGNN,
    train_graphs: List[Data],
    train_targets: torch.Tensor,
    val_graphs: Optional[List[Data]] = None,
    val_targets: Optional[torch.Tensor] = None,
    epochs: int = 100,
    lr: float = 0.001,
    device: str = 'cpu'
) -> Dict[str, List[float]]:
    """
    Train PathwayGNN on GWAS data.

    Args:
        gnn: PathwayGNN model
        train_graphs: List of pathway graphs
        train_targets: Target values (e.g., phenotypes or marginal effects)
        val_graphs: Validation graphs
        val_targets: Validation targets
        epochs: Number of training epochs
        lr: Learning rate
        device: 'cpu' or 'cuda'

    Returns:
        Training history
    """
    gnn = gnn.to(device)
    optimizer = torch.optim.Adam(gnn.parameters(), lr=lr, weight_decay=1e-5)
    criterion = nn.MSELoss()

    history = {'train_loss': [], 'val_loss': []}

    for epoch in range(epochs):
        # Training
        gnn.train()
        train_loss = 0.0

        for graph, target in zip(train_graphs, train_targets):
            graph = graph.to(device)
            target = target.to(device).unsqueeze(0)

            optimizer.zero_grad()
            pred = gnn(graph.x, graph.edge_index)
            loss = criterion(pred, target)
            loss.backward()
            optimizer.step()

            train_loss += loss.item()

        train_loss /= len(train_graphs)
        history['train_loss'].append(train_loss)

        # Validation
        if val_graphs is not None:
            gnn.eval()
            val_loss = 0.0

            with torch.no_grad():
                for graph, target in zip(val_graphs, val_targets):
                    graph = graph.to(device)
                    target = target.to(device).unsqueeze(0)

                    pred = gnn(graph.x, graph.edge_index)
                    loss = criterion(pred, target)
                    val_loss += loss.item()

            val_loss /= len(val_graphs)
            history['val_loss'].append(val_loss)

            if epoch % 10 == 0:
                print(f"Epoch {epoch:3d}: Train Loss = {train_loss:.4f}, Val Loss = {val_loss:.4f}")
        else:
            if epoch % 10 == 0:
                print(f"Epoch {epoch:3d}: Train Loss = {train_loss:.4f}")

    return history
