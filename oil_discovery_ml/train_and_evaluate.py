#!/usr/bin/env python3
"""
Main training and evaluation script for Oil Discovery ML
This script:
1. Generates realistic geological data
2. Trains deep learning model with cross-validation
3. Evaluates on held-out test reserves (not seen during training)
4. Creates comprehensive visualizations
5. Saves all results and model
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from geological_data_generator import GeologicalDataGenerator
from oil_discovery_model import OilDiscoveryModel, CrossValidationTrainer
from visualization import create_all_visualizations


def main():
    """Main training and evaluation pipeline"""

    print("="*80)
    print("OIL DISCOVERY ML - TRAINING AND EVALUATION")
    print("="*80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    # Configuration
    config = {
        'grid_resolution': 1.5,  # degrees
        'test_reserves_ratio': 0.3,  # 30% of reserves held out for testing
        'cv_folds': 5,
        'epochs': 150,
        'batch_size': 512,
        'random_seed': 42
    }

    print("\nConfiguration:")
    for key, value in config.items():
        print(f"  {key}: {value}")
    print()

    # Create output directories
    os.makedirs('data', exist_ok=True)
    os.makedirs('models', exist_ok=True)
    os.makedirs('results', exist_ok=True)

    # ========================================================================
    # STEP 1: Generate Geological Data
    # ========================================================================
    print("\n" + "="*80)
    print("STEP 1: GENERATING GEOLOGICAL DATA")
    print("="*80)

    generator = GeologicalDataGenerator(
        grid_resolution=config['grid_resolution'],
        random_seed=config['random_seed']
    )

    df, test_reserves = generator.generate_full_dataset(
        test_ratio=config['test_reserves_ratio']
    )

    # Save raw data
    data_path = 'data/geological_data.csv'
    df.to_csv(data_path, index=False)
    print(f"\nDataset saved to: {data_path}")

    # Save test reserves list
    with open('data/test_reserves.json', 'w') as f:
        json.dump(test_reserves, f, indent=2)

    # Print data statistics
    print("\n" + "-"*80)
    print("Dataset Statistics:")
    print("-"*80)
    print(f"Total grid points: {len(df):,}")
    print(f"Points with oil: {df['has_oil'].sum():,} ({100*df['has_oil'].sum()/len(df):.2f}%)")
    print(f"Points in training set: {(~df['is_test_reserve']).sum():,}")
    print(f"Points in test set: {df['is_test_reserve'].sum():,}")
    print(f"\nTest reserves (held out): {len(test_reserves)}")
    for reserve in test_reserves:
        print(f"  - {reserve}")

    # ========================================================================
    # STEP 2: Define Features
    # ========================================================================
    print("\n" + "="*80)
    print("STEP 2: FEATURE ENGINEERING")
    print("="*80)

    feature_columns = [
        'latitude',
        'longitude',
        'biomass_accumulation',
        'geological_pressure',
        'subduction_proximity',
        'rift_proximity',
        'temperature_gradient',
        'cap_rock_probability',
        'porosity_index'
    ]

    print("\nSelected features:")
    for i, feature in enumerate(feature_columns, 1):
        print(f"  {i}. {feature}")

    print("\nFeature statistics:")
    print(df[feature_columns].describe())

    # ========================================================================
    # STEP 3: Cross-Validation Training
    # ========================================================================
    print("\n" + "="*80)
    print("STEP 3: CROSS-VALIDATION TRAINING")
    print("="*80)

    cv_trainer = CrossValidationTrainer(
        n_splits=config['cv_folds'],
        random_seed=config['random_seed']
    )

    results = cv_trainer.train_with_cv(
        df=df,
        feature_columns=feature_columns,
        test_reserves=test_reserves,
        epochs=config['epochs'],
        batch_size=config['batch_size']
    )

    best_model = results['best_model']
    test_metrics = results['test_metrics']
    test_predictions = results['test_predictions']
    cv_results = results['cv_results']

    # ========================================================================
    # STEP 4: Save Model and Results
    # ========================================================================
    print("\n" + "="*80)
    print("STEP 4: SAVING MODEL AND RESULTS")
    print("="*80)

    # Save model
    model_dir = 'models/best_model'
    best_model.save(model_dir)

    # Save test predictions
    predictions_path = 'results/test_predictions.csv'
    test_predictions.to_csv(predictions_path, index=False)
    print(f"Test predictions saved to: {predictions_path}")

    # Save metrics
    metrics_path = 'results/test_metrics.json'
    with open(metrics_path, 'w') as f:
        # Convert numpy types to Python types for JSON serialization
        metrics_serializable = {k: float(v) for k, v in test_metrics.items()}
        json.dump(metrics_serializable, f, indent=2)
    print(f"Test metrics saved to: {metrics_path}")

    # Save CV summary
    cv_summary = []
    for result in cv_results:
        fold_summary = {
            'fold': result['fold'],
            'val_metrics': {k: float(v) for k, v in result['val_metrics'].items()}
        }
        cv_summary.append(fold_summary)

    cv_path = 'results/cv_summary.json'
    with open(cv_path, 'w') as f:
        json.dump(cv_summary, f, indent=2)
    print(f"CV summary saved to: {cv_path}")

    # ========================================================================
    # STEP 5: Create Visualizations
    # ========================================================================
    print("\n" + "="*80)
    print("STEP 5: CREATING VISUALIZATIONS")
    print("="*80)

    create_all_visualizations(
        df=df,
        test_predictions=test_predictions,
        cv_results=cv_results,
        feature_columns=feature_columns,
        output_dir='results/plots'
    )

    # ========================================================================
    # STEP 6: Final Summary
    # ========================================================================
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)

    print("\nCross-Validation Results:")
    print("-"*80)
    for result in cv_results:
        print(f"\nFold {result['fold']}:")
        for metric, value in result['val_metrics'].items():
            print(f"  {metric}: {value:.4f}")

    print("\n" + "-"*80)
    print("Test Set Performance (Held-Out Reserves):")
    print("-"*80)
    for metric, value in test_metrics.items():
        print(f"  {metric}: {value:.4f}")

    print("\n" + "-"*80)
    print("Predictions on Test Reserves:")
    print("-"*80)
    for reserve_name in test_reserves:
        reserve_data = test_predictions[test_predictions['reserve_name'] == reserve_name]
        if len(reserve_data) > 0:
            avg_prob = reserve_data['predicted_oil_prob'].mean()
            total_pred = reserve_data['predicted_reserve_size'].sum()
            total_actual = reserve_data['reserve_size'].sum()

            print(f"\n{reserve_name}:")
            print(f"  Average oil probability: {avg_prob:.3f}")
            print(f"  Predicted reserves: {total_pred:.2f} billion barrels")
            print(f"  Actual reserves: {total_actual:.2f} billion barrels")
            print(f"  Error: {abs(total_pred - total_actual):.2f} billion barrels ({100*abs(total_pred - total_actual)/total_actual:.1f}%)")

    # ========================================================================
    # STEP 7: Generate Full Global Predictions
    # ========================================================================
    print("\n" + "="*80)
    print("STEP 7: GENERATING GLOBAL PREDICTIONS")
    print("="*80)

    print("\nPredicting on entire global grid...")
    X_all = df[feature_columns].values
    oil_prob_all, reserve_size_all = best_model.predict(X_all)

    df['predicted_oil_prob'] = oil_prob_all
    df['predicted_reserve_size'] = reserve_size_all

    # Save full predictions
    full_predictions_path = 'results/full_global_predictions.csv'
    df.to_csv(full_predictions_path, index=False)
    print(f"Full global predictions saved to: {full_predictions_path}")

    # Find top predicted areas (excluding known reserves)
    unknown_areas = df[df['has_oil'] == 0].copy()
    top_predictions = unknown_areas.nlargest(20, 'predicted_oil_prob')

    print("\nTop 20 Predicted Areas (Unknown Reserves):")
    print("-"*80)
    print(f"{'Rank':<6} {'Latitude':<10} {'Longitude':<10} {'Oil Prob':<12} {'Pred. Size':<12}")
    print("-"*80)
    for i, (idx, row) in enumerate(top_predictions.iterrows(), 1):
        print(f"{i:<6} {row['latitude']:<10.2f} {row['longitude']:<10.2f} "
              f"{row['predicted_oil_prob']:<12.3f} {row['predicted_reserve_size']:<12.2f}")

    # ========================================================================
    # COMPLETION
    # ========================================================================
    print("\n" + "="*80)
    print("TRAINING AND EVALUATION COMPLETED")
    print("="*80)
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nAll outputs saved to:")
    print(f"  - Data: data/")
    print(f"  - Model: models/best_model/")
    print(f"  - Results: results/")
    print(f"  - Visualizations: results/plots/")
    print("="*80)


if __name__ == "__main__":
    main()
