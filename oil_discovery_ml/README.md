# Oil Discovery ML - Geological Machine Learning System

A comprehensive deep learning system for predicting oil reserves based on geological features including biomass accumulation, geological pressure, tectonic plate movements, and other geological indicators.

## Features

### Realistic Geological Data Generation
- **Biomass Accumulation**: Sedimentary basin modeling with historical marine productivity
- **Geological Pressure**: Depth-based and tectonic compression modeling
- **Tectonic Activity**: Plate boundary proximity, subduction zones, and rift zones
- **Temperature Gradient**: Geothermal conditions for oil maturation
- **Cap Rock Presence**: Sealing layer probability estimation
- **Porosity/Permeability**: Reservoir rock quality indicators

### Known Oil Reserves Database
Includes 21 major oil fields worldwide:
- Middle East: Ghawar, Burgan, Safaniya, Rumaila, West Qurna
- South America: Orinoco Belt, Tupi, Libra
- North America: Prudhoe Bay, East Texas, Bakken, Permian Basin
- Russia/Caspian: Samotlor, Romashkino, Tengiz
- Africa: Hassi Messaoud, Jubilee
- North Sea: Ekofisk, Statfjord
- Asia: Daqing, Cantarell

### Deep Learning Architecture
- **Multi-task Learning**: Simultaneous prediction of oil presence (classification) and reserve size (regression)
- **Architecture**: Deep neural network with batch normalization and dropout
- **Regularization**: Early stopping, learning rate reduction, class weighting
- **Features**: 9 geological input features

### Rigorous Validation
- **K-Fold Cross-Validation**: 5-fold CV on training data
- **Held-Out Test Set**: 30% of known reserves excluded from training entirely
- **Anti-Overfitting**: Model never sees test reserves during training
- **Iterative Training**: 150+ epochs with early stopping

### Comprehensive Visualizations
- Global heatmaps of oil probability predictions
- Actual vs predicted reserve comparisons
- Training history across CV folds
- Feature importance analysis
- Prediction distributions
- Geological feature maps

## Project Structure

```
oil_discovery_ml/
├── src/
│   ├── geological_data_generator.py  # Data generation module
│   ├── oil_discovery_model.py        # Deep learning model
│   └── visualization.py               # Plotting and heatmaps
├── data/                              # Generated datasets
├── models/                            # Trained model files
├── results/                           # Predictions and metrics
│   └── plots/                         # Visualization outputs
├── train_and_evaluate.py              # Main training script
└── requirements.txt                   # Python dependencies
```

## Installation

```bash
cd oil_discovery_ml
pip install -r requirements.txt
```

## Usage

### Full Training and Evaluation Pipeline

```bash
python train_and_evaluate.py
```

This will:
1. Generate realistic geological data with 21 known oil reserves
2. Split reserves into train (70%) and test (30%) sets
3. Train deep learning model with 5-fold cross-validation
4. Evaluate on held-out test reserves never seen during training
5. Create comprehensive visualizations
6. Save model, predictions, and results

### Output Files

After running, you'll find:

**Data**:
- `data/geological_data.csv`: Full geological dataset
- `data/test_reserves.json`: List of held-out test reserves

**Model**:
- `models/best_model/model.h5`: Trained model weights
- `models/best_model/scaler.pkl`: Feature scaler

**Results**:
- `results/test_predictions.csv`: Predictions on test reserves
- `results/full_global_predictions.csv`: Predictions for entire globe
- `results/test_metrics.json`: Test set performance metrics
- `results/cv_summary.json`: Cross-validation results

**Visualizations** (`results/plots/`):
- `heatmap_predicted_probability.png`: Global oil probability heatmap
- `heatmap_actual_vs_predicted.png`: Side-by-side comparison
- `training_history.png`: Training curves across CV folds
- `feature_importance.png`: Feature correlation analysis
- `prediction_distribution.png`: Prediction statistics
- `feature_*.png`: Individual geological feature maps

## Validation Methodology

### Critical: No Data Leakage

The system ensures rigorous validation:

1. **Test reserves are randomly selected** before any training
2. **Test reserves are completely excluded** from all training data
3. **Model never sees test reserves** during any CV fold
4. **Final evaluation** is on these truly held-out reserves

This means the model must **discover** known oil fields it has never seen, proving it learned genuine geological patterns rather than memorizing locations.

### Example

If the test set includes Prudhoe Bay and Bakken Formation:
- Training data: All other 19 reserves + surrounding geological features
- Model learns: Geological signatures that correlate with oil presence
- Test evaluation: Can the model predict Prudhoe Bay and Bakken based on their geological features alone?

## Performance Metrics

The system reports:

### Classification Metrics (Oil Presence)
- **ROC AUC**: Area under ROC curve
- **PR AUC**: Precision-Recall AUC (better for imbalanced data)
- **Accuracy**: Overall classification accuracy

### Regression Metrics (Reserve Size)
- **MAE**: Mean Absolute Error in billion barrels
- **RMSE**: Root Mean Squared Error in billion barrels

## Geological Features Explained

1. **Biomass Accumulation**: Historical accumulation of organic matter in sedimentary basins
2. **Geological Pressure**: Combination of sediment depth and tectonic compression
3. **Subduction Proximity**: Distance to subduction zones (convergent plate boundaries)
4. **Rift Proximity**: Distance to rift zones (divergent plate boundaries)
5. **Temperature Gradient**: Geothermal gradient affecting oil maturation
6. **Cap Rock Probability**: Likelihood of sealing layer for oil traps
7. **Porosity Index**: Reservoir rock quality indicator
8. **Latitude/Longitude**: Geographic coordinates

## Technical Details

### Model Architecture
- Input: 9 geological features
- Hidden layers: 256 → 128 → 64 → 32 neurons
- Batch normalization after each layer
- Dropout (0.2-0.3) for regularization
- Two output heads:
  - Binary classification (sigmoid activation)
  - Regression (linear activation)

### Training Configuration
- Optimizer: Adam (learning rate: 0.001)
- Batch size: 512
- Epochs: 150 (with early stopping)
- Loss: Binary crossentropy + MSE
- Class weighting for imbalanced data

### Data
- Grid resolution: 1.5 degrees
- Coverage: Global (-90° to 90° lat, -180° to 180° lon)
- Total points: ~60,000+
- Oil-bearing points: ~1-2% (realistic class imbalance)

## Future Enhancements

Potential improvements:
- Incorporate real seismic data
- Add temporal geological evolution
- Include actual well log data
- 3D subsurface modeling
- Integration with remote sensing data
- Uncertainty quantification with Bayesian methods

## License

Educational and research purposes.

## Citation

If you use this system, please cite:
```
Oil Discovery ML - Geological Machine Learning System
Deep Learning for Oil Reserve Prediction
2025
```
