"""
Deep Learning Model for Oil Discovery
Multi-task learning: predicts both presence and reserve size
"""

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, models, callbacks
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import KFold
from sklearn.metrics import roc_auc_score, precision_recall_curve, auc
import joblib
from typing import Tuple, Dict, List
import os


class OilDiscoveryModel:
    """Deep learning model for oil reserve prediction"""

    def __init__(self, input_dim: int = 9, random_seed: int = 42):
        """
        Initialize the model

        Args:
            input_dim: Number of input features
            random_seed: Random seed for reproducibility
        """
        self.input_dim = input_dim
        self.random_seed = random_seed
        self.model = None
        self.scaler = StandardScaler()
        self.history = None

        # Set seeds
        np.random.seed(random_seed)
        tf.random.set_seed(random_seed)

    def build_model(self) -> keras.Model:
        """
        Build deep neural network architecture

        Architecture:
        - Input layer
        - Multiple dense layers with batch normalization and dropout
        - Two output heads: binary classification + regression
        """
        # Input
        inputs = layers.Input(shape=(self.input_dim,), name='geological_features')

        # Shared feature extraction layers
        x = layers.Dense(256, activation='relu', name='dense1')(inputs)
        x = layers.BatchNormalization(name='bn1')(x)
        x = layers.Dropout(0.3, name='dropout1')(x)

        x = layers.Dense(128, activation='relu', name='dense2')(x)
        x = layers.BatchNormalization(name='bn2')(x)
        x = layers.Dropout(0.3, name='dropout2')(x)

        x = layers.Dense(64, activation='relu', name='dense3')(x)
        x = layers.BatchNormalization(name='bn3')(x)
        x = layers.Dropout(0.2, name='dropout3')(x)

        x = layers.Dense(32, activation='relu', name='dense4')(x)
        x = layers.BatchNormalization(name='bn4')(x)

        # Branch 1: Binary classification (has oil or not)
        classification_branch = layers.Dense(16, activation='relu', name='class_dense')(x)
        classification_output = layers.Dense(1, activation='sigmoid', name='has_oil_output')(classification_branch)

        # Branch 2: Regression (reserve size)
        regression_branch = layers.Dense(16, activation='relu', name='reg_dense')(x)
        regression_output = layers.Dense(1, activation='linear', name='reserve_size_output')(regression_branch)

        # Create model
        model = models.Model(
            inputs=inputs,
            outputs=[classification_output, regression_output],
            name='oil_discovery_model'
        )

        return model

    def compile_model(self, learning_rate: float = 0.001):
        """Compile model with loss functions and metrics"""
        self.model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
            loss={
                'has_oil_output': 'binary_crossentropy',
                'reserve_size_output': 'mse'
            },
            loss_weights={
                'has_oil_output': 1.0,
                'reserve_size_output': 0.5
            },
            metrics={
                'has_oil_output': ['accuracy', keras.metrics.AUC(name='auc')],
                'reserve_size_output': ['mae']
            }
        )

    def prepare_data(self, df: pd.DataFrame,
                    feature_columns: List[str]) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """
        Prepare features and labels from dataframe

        Args:
            df: Input dataframe
            feature_columns: List of feature column names

        Returns:
            Tuple of (features, labels_dict)
        """
        X = df[feature_columns].values
        y = {
            'has_oil_output': df['has_oil'].values,
            'reserve_size_output': df['reserve_size'].values
        }

        return X, y

    def train(self, X_train: np.ndarray, y_train: Dict[str, np.ndarray],
              X_val: np.ndarray, y_val: Dict[str, np.ndarray],
              epochs: int = 200, batch_size: int = 512,
              verbose: int = 1) -> keras.callbacks.History:
        """
        Train the model

        Args:
            X_train: Training features
            y_train: Training labels
            X_val: Validation features
            y_val: Validation labels
            epochs: Number of training epochs
            batch_size: Batch size
            verbose: Verbosity level

        Returns:
            Training history
        """
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val)

        # Callbacks
        early_stop = callbacks.EarlyStopping(
            monitor='val_has_oil_output_auc',
            patience=20,
            restore_best_weights=True,
            mode='max',
            verbose=1
        )

        reduce_lr = callbacks.ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,
            patience=10,
            min_lr=1e-7,
            verbose=1
        )

        # Train
        # Note: Using loss_weights in compile_model to handle class imbalance
        # instead of sample_weight for multi-output compatibility
        self.history = self.model.fit(
            X_train_scaled,
            y_train,
            validation_data=(X_val_scaled, y_val),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=[early_stop, reduce_lr],
            verbose=verbose
        )

        return self.history

    def predict(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Make predictions

        Args:
            X: Input features

        Returns:
            Tuple of (oil_probability, reserve_size_prediction)
        """
        X_scaled = self.scaler.transform(X)
        predictions = self.model.predict(X_scaled, verbose=0)

        oil_prob = predictions[0].flatten()
        reserve_size = predictions[1].flatten()

        # Ensure reserve size is non-negative
        reserve_size = np.maximum(reserve_size, 0)

        return oil_prob, reserve_size

    def evaluate(self, X: np.ndarray, y: Dict[str, np.ndarray]) -> Dict[str, float]:
        """
        Evaluate model performance

        Args:
            X: Features
            y: True labels

        Returns:
            Dictionary of metrics
        """
        oil_prob, reserve_pred = self.predict(X)

        # Classification metrics
        auc_score = roc_auc_score(y['has_oil_output'], oil_prob)

        # Precision-Recall AUC
        precision, recall, _ = precision_recall_curve(y['has_oil_output'], oil_prob)
        pr_auc = auc(recall, precision)

        # Regression metrics (only for points with oil)
        has_oil_mask = y['has_oil_output'] == 1
        if has_oil_mask.sum() > 0:
            mae = np.mean(np.abs(reserve_pred[has_oil_mask] - y['reserve_size_output'][has_oil_mask]))
            rmse = np.sqrt(np.mean((reserve_pred[has_oil_mask] - y['reserve_size_output'][has_oil_mask])**2))
        else:
            mae = 0.0
            rmse = 0.0

        return {
            'roc_auc': auc_score,
            'pr_auc': pr_auc,
            'mae_reserve_size': mae,
            'rmse_reserve_size': rmse
        }

    def save(self, model_dir: str):
        """Save model and scaler"""
        os.makedirs(model_dir, exist_ok=True)
        self.model.save(os.path.join(model_dir, 'model.h5'))
        joblib.dump(self.scaler, os.path.join(model_dir, 'scaler.pkl'))
        print(f"Model saved to {model_dir}")

    def load(self, model_dir: str):
        """Load model and scaler"""
        self.model = keras.models.load_model(os.path.join(model_dir, 'model.h5'))
        self.scaler = joblib.load(os.path.join(model_dir, 'scaler.pkl'))
        print(f"Model loaded from {model_dir}")


class CrossValidationTrainer:
    """Performs k-fold cross-validation with holdout test set"""

    def __init__(self, n_splits: int = 5, random_seed: int = 42):
        """
        Initialize cross-validation trainer

        Args:
            n_splits: Number of CV folds
            random_seed: Random seed
        """
        self.n_splits = n_splits
        self.random_seed = random_seed
        self.cv_results = []

    def train_with_cv(self, df: pd.DataFrame, feature_columns: List[str],
                     test_reserves: List[str], epochs: int = 200,
                     batch_size: int = 512) -> Dict:
        """
        Train with cross-validation, excluding test reserves

        Args:
            df: Full dataframe
            feature_columns: Feature column names
            test_reserves: Names of reserves to hold out
            epochs: Training epochs per fold
            batch_size: Batch size

        Returns:
            Dictionary with CV results and best model
        """
        # Split data: training (no test reserves) vs test (test reserves only)
        train_df = df[~df['is_test_reserve']].copy()
        test_df = df[df['is_test_reserve']].copy()

        print(f"\n{'='*60}")
        print(f"Cross-Validation Training")
        print(f"{'='*60}")
        print(f"Training samples: {len(train_df):,}")
        print(f"  - With oil: {train_df['has_oil'].sum():,}")
        print(f"Test samples (held-out reserves): {len(test_df):,}")
        print(f"  - With oil: {test_df['has_oil'].sum():,}")
        print(f"Test reserves: {', '.join(test_reserves)}")
        print(f"{'='*60}\n")

        # Prepare test data
        X_test = test_df[feature_columns].values
        y_test = {
            'has_oil_output': test_df['has_oil'].values,
            'reserve_size_output': test_df['reserve_size'].values
        }

        # K-fold cross-validation on training data
        kfold = KFold(n_splits=self.n_splits, shuffle=True, random_state=self.random_seed)

        best_model = None
        best_auc = 0.0

        for fold, (train_idx, val_idx) in enumerate(kfold.split(train_df), 1):
            print(f"\n{'='*60}")
            print(f"Training Fold {fold}/{self.n_splits}")
            print(f"{'='*60}")

            # Split fold
            fold_train_df = train_df.iloc[train_idx]
            fold_val_df = train_df.iloc[val_idx]

            X_train = fold_train_df[feature_columns].values
            y_train = {
                'has_oil_output': fold_train_df['has_oil'].values,
                'reserve_size_output': fold_train_df['reserve_size'].values
            }

            X_val = fold_val_df[feature_columns].values
            y_val = {
                'has_oil_output': fold_val_df['has_oil'].values,
                'reserve_size_output': fold_val_df['reserve_size'].values
            }

            # Create and train model
            model = OilDiscoveryModel(input_dim=len(feature_columns), random_seed=self.random_seed)
            model.model = model.build_model()
            model.compile_model()

            history = model.train(X_train, y_train, X_val, y_val,
                                epochs=epochs, batch_size=batch_size, verbose=1)

            # Evaluate on validation set
            val_metrics = model.evaluate(X_val, y_val)

            print(f"\nFold {fold} Validation Metrics:")
            for metric_name, value in val_metrics.items():
                print(f"  {metric_name}: {value:.4f}")

            # Track best model
            if val_metrics['roc_auc'] > best_auc:
                best_auc = val_metrics['roc_auc']
                best_model = model

            self.cv_results.append({
                'fold': fold,
                'val_metrics': val_metrics,
                'history': history.history
            })

        # Evaluate best model on held-out test reserves
        print(f"\n{'='*60}")
        print(f"Final Evaluation on Held-Out Test Reserves")
        print(f"{'='*60}")

        test_metrics = best_model.evaluate(X_test, y_test)

        print(f"\nTest Set Metrics (Held-Out Reserves):")
        for metric_name, value in test_metrics.items():
            print(f"  {metric_name}: {value:.4f}")

        # Get predictions for test reserves
        test_oil_prob, test_reserve_pred = best_model.predict(X_test)
        test_df_copy = test_df.copy()
        test_df_copy['predicted_oil_prob'] = test_oil_prob
        test_df_copy['predicted_reserve_size'] = test_reserve_pred

        # Summary by reserve
        print(f"\nPredictions by Test Reserve:")
        for reserve_name in test_reserves:
            reserve_data = test_df_copy[test_df_copy['reserve_name'] == reserve_name]
            if len(reserve_data) > 0:
                avg_prob = reserve_data['predicted_oil_prob'].mean()
                total_pred = reserve_data['predicted_reserve_size'].sum()
                total_actual = reserve_data['reserve_size'].sum()
                print(f"\n  {reserve_name}:")
                print(f"    Avg oil probability: {avg_prob:.3f}")
                print(f"    Predicted total reserves: {total_pred:.2f} billion barrels")
                print(f"    Actual total reserves: {total_actual:.2f} billion barrels")

        return {
            'best_model': best_model,
            'cv_results': self.cv_results,
            'test_metrics': test_metrics,
            'test_predictions': test_df_copy,
            'test_reserves': test_reserves
        }


if __name__ == "__main__":
    print("Oil Discovery Model - Test")
    print("Building model architecture...")

    model = OilDiscoveryModel(input_dim=9)
    model.model = model.build_model()
    model.compile_model()

    print("\nModel Summary:")
    model.model.summary()
