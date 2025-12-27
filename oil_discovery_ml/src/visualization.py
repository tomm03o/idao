"""
Visualization module for oil discovery predictions
Creates heatmaps and geographical plots
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Optional, Tuple
import os


def plot_global_heatmap(df: pd.DataFrame,
                       value_column: str,
                       title: str,
                       output_path: str,
                       cmap: str = 'YlOrRd',
                       figsize: Tuple[int, int] = (20, 10),
                       vmin: Optional[float] = None,
                       vmax: Optional[float] = None):
    """
    Plot global heatmap of predictions or features

    Args:
        df: DataFrame with latitude, longitude, and value columns
        value_column: Column name to plot
        title: Plot title
        output_path: Path to save figure
        cmap: Colormap name
        figsize: Figure size
        vmin: Minimum value for colormap
        vmax: Maximum value for colormap
    """
    plt.figure(figsize=figsize)

    # Create pivot table for heatmap
    pivot_data = df.pivot_table(
        values=value_column,
        index='latitude',
        columns='longitude',
        aggfunc='mean'
    )

    # Plot heatmap
    plt.imshow(pivot_data, cmap=cmap, aspect='auto',
              extent=[-180, 180, -90, 90], origin='lower',
              vmin=vmin, vmax=vmax, interpolation='bilinear')

    plt.colorbar(label=value_column, shrink=0.8)
    plt.xlabel('Longitude', fontsize=14)
    plt.ylabel('Latitude', fontsize=14)
    plt.title(title, fontsize=16, fontweight='bold')

    # Add gridlines
    plt.grid(True, alpha=0.3, linestyle='--')

    # Add coastlines approximation (simple box for continents)
    plt.axhline(y=0, color='gray', linestyle='-', alpha=0.5, linewidth=0.5)
    plt.axvline(x=0, color='gray', linestyle='-', alpha=0.5, linewidth=0.5)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()


def plot_overlay_heatmap(df: pd.DataFrame,
                        prediction_column: str,
                        actual_column: str,
                        title: str,
                        output_path: str,
                        figsize: Tuple[int, int] = (20, 10)):
    """
    Plot predicted vs actual oil reserves overlay

    Args:
        df: DataFrame with predictions and actuals
        prediction_column: Column with predictions
        actual_column: Column with actual values
        title: Plot title
        output_path: Path to save figure
        figsize: Figure size
    """
    fig, axes = plt.subplots(1, 2, figsize=figsize)

    for ax, column, subtitle in zip(axes,
                                    [actual_column, prediction_column],
                                    ['Actual Oil Reserves', 'Predicted Oil Reserves']):

        pivot_data = df.pivot_table(
            values=column,
            index='latitude',
            columns='longitude',
            aggfunc='mean'
        )

        im = ax.imshow(pivot_data, cmap='YlOrRd', aspect='auto',
                      extent=[-180, 180, -90, 90], origin='lower',
                      vmin=0, vmax=df[actual_column].max(), interpolation='bilinear')

        ax.set_xlabel('Longitude', fontsize=12)
        ax.set_ylabel('Latitude', fontsize=12)
        ax.set_title(subtitle, fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='--')

        plt.colorbar(im, ax=ax, label='Reserve Size', shrink=0.8)

    fig.suptitle(title, fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()


def plot_training_history(cv_results: list,
                         output_path: str,
                         figsize: Tuple[int, int] = (16, 10)):
    """
    Plot training history across CV folds

    Args:
        cv_results: List of CV results with history
        output_path: Path to save figure
        figsize: Figure size
    """
    fig, axes = plt.subplots(2, 2, figsize=figsize)

    metrics = [
        ('loss', 'Loss'),
        ('has_oil_output_auc', 'AUC (Oil Presence)'),
        ('has_oil_output_accuracy', 'Accuracy (Oil Presence)'),
        ('reserve_size_output_mae', 'MAE (Reserve Size)')
    ]

    for ax, (metric, title) in zip(axes.flatten(), metrics):
        for fold_idx, result in enumerate(cv_results, 1):
            history = result['history']

            if metric in history:
                ax.plot(history[metric], label=f'Fold {fold_idx} - Train', alpha=0.6)

            val_metric = f'val_{metric}'
            if val_metric in history:
                ax.plot(history[val_metric], label=f'Fold {fold_idx} - Val',
                       linestyle='--', alpha=0.6)

        ax.set_xlabel('Epoch', fontsize=11)
        ax.set_ylabel(title, fontsize=11)
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.legend(fontsize=8, ncol=2)
        ax.grid(True, alpha=0.3)

    fig.suptitle('Training History Across CV Folds', fontsize=16, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()


def plot_feature_importance_analysis(df: pd.DataFrame,
                                     feature_columns: list,
                                     output_path: str,
                                     figsize: Tuple[int, int] = (14, 8)):
    """
    Plot correlation heatmap of features with oil presence

    Args:
        df: DataFrame with features and labels
        feature_columns: List of feature column names
        output_path: Path to save figure
        figsize: Figure size
    """
    # Compute correlations with has_oil
    correlations = df[feature_columns + ['has_oil']].corr()['has_oil'][:-1].sort_values(ascending=False)

    fig, axes = plt.subplots(1, 2, figsize=figsize)

    # Bar plot of correlations
    axes[0].barh(range(len(correlations)), correlations.values)
    axes[0].set_yticks(range(len(correlations)))
    axes[0].set_yticklabels(correlations.index)
    axes[0].set_xlabel('Correlation with Oil Presence', fontsize=12)
    axes[0].set_title('Feature Correlations', fontsize=14, fontweight='bold')
    axes[0].grid(True, alpha=0.3, axis='x')

    # Correlation matrix heatmap
    corr_matrix = df[feature_columns].corr()
    sns.heatmap(corr_matrix, annot=True, fmt='.2f', cmap='coolwarm',
               center=0, square=True, ax=axes[1], cbar_kws={'shrink': 0.8})
    axes[1].set_title('Feature Correlation Matrix', fontsize=14, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()


def plot_prediction_distribution(test_predictions: pd.DataFrame,
                                output_path: str,
                                figsize: Tuple[int, int] = (14, 6)):
    """
    Plot distribution of predictions

    Args:
        test_predictions: DataFrame with predictions
        output_path: Path to save figure
        figsize: Figure size
    """
    fig, axes = plt.subplots(1, 2, figsize=figsize)

    # Oil probability distribution
    axes[0].hist(test_predictions['predicted_oil_prob'], bins=50,
                edgecolor='black', alpha=0.7)
    axes[0].set_xlabel('Predicted Oil Probability', fontsize=12)
    axes[0].set_ylabel('Frequency', fontsize=12)
    axes[0].set_title('Distribution of Oil Probabilities', fontsize=14, fontweight='bold')
    axes[0].grid(True, alpha=0.3, axis='y')

    # Reserve size: actual vs predicted (for points with oil)
    oil_points = test_predictions[test_predictions['has_oil'] == 1]
    axes[1].scatter(oil_points['reserve_size'], oil_points['predicted_reserve_size'],
                   alpha=0.6, s=30)
    axes[1].plot([0, oil_points['reserve_size'].max()],
                [0, oil_points['reserve_size'].max()],
                'r--', label='Perfect prediction')
    axes[1].set_xlabel('Actual Reserve Size', fontsize=12)
    axes[1].set_ylabel('Predicted Reserve Size', fontsize=12)
    axes[1].set_title('Reserve Size: Actual vs Predicted', fontsize=14, fontweight='bold')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()


def create_all_visualizations(df: pd.DataFrame,
                              test_predictions: pd.DataFrame,
                              cv_results: list,
                              feature_columns: list,
                              output_dir: str):
    """
    Create all visualization plots

    Args:
        df: Full dataset
        test_predictions: Test set predictions
        cv_results: Cross-validation results
        feature_columns: Feature column names
        output_dir: Directory to save plots
    """
    os.makedirs(output_dir, exist_ok=True)

    print("\nCreating visualizations...")

    # 1. Heatmap of predicted oil probabilities
    if 'predicted_oil_prob' in test_predictions.columns:
        plot_global_heatmap(
            test_predictions,
            value_column='predicted_oil_prob',
            title='Predicted Oil Discovery Probability - Held-Out Test Reserves',
            output_path=os.path.join(output_dir, 'heatmap_predicted_probability.png'),
            cmap='YlOrRd',
            vmin=0,
            vmax=1
        )

    # 2. Overlay of actual vs predicted reserves
    if 'predicted_reserve_size' in test_predictions.columns:
        plot_overlay_heatmap(
            test_predictions,
            prediction_column='predicted_reserve_size',
            actual_column='reserve_size',
            title='Oil Reserves: Actual vs Predicted (Held-Out Test Set)',
            output_path=os.path.join(output_dir, 'heatmap_actual_vs_predicted.png')
        )

    # 3. Training history
    plot_training_history(
        cv_results,
        output_path=os.path.join(output_dir, 'training_history.png')
    )

    # 4. Feature importance
    plot_feature_importance_analysis(
        df,
        feature_columns=feature_columns,
        output_path=os.path.join(output_dir, 'feature_importance.png')
    )

    # 5. Prediction distributions
    if 'predicted_oil_prob' in test_predictions.columns:
        plot_prediction_distribution(
            test_predictions,
            output_path=os.path.join(output_dir, 'prediction_distribution.png')
        )

    # 6. Heatmaps of geological features
    for feature in feature_columns[:4]:  # Plot first 4 features
        plot_global_heatmap(
            df,
            value_column=feature,
            title=f'Geological Feature: {feature}',
            output_path=os.path.join(output_dir, f'feature_{feature}.png'),
            cmap='viridis'
        )

    print(f"\nAll visualizations saved to: {output_dir}")


if __name__ == "__main__":
    print("Visualization module loaded successfully")
