"""
Geological Data Generator for Oil Discovery ML
Generates realistic geological features based on:
- Biomass accumulation (sedimentary basins)
- Geological pressure and depth
- Tectonic plate movements
- Temperature and geological conditions
"""

import numpy as np
import pandas as pd
from typing import Tuple, List, Dict
from dataclasses import dataclass


@dataclass
class OilReserve:
    """Represents a known oil reserve"""
    name: str
    latitude: float
    longitude: float
    reserves_billion_barrels: float
    discovery_year: int


class GeologicalDataGenerator:
    """Generates geological features for oil discovery prediction"""

    # Known major oil reserves (approximate locations and sizes)
    KNOWN_RESERVES = [
        # Middle East
        OilReserve("Ghawar Field", 25.5, 49.5, 75.0, 1948),
        OilReserve("Burgan Field", 29.1, 48.1, 66.0, 1938),
        OilReserve("Safaniya Field", 27.7, 48.8, 36.0, 1951),
        OilReserve("Rumaila Field", 30.5, 47.5, 17.0, 1953),
        OilReserve("West Qurna", 31.0, 47.3, 21.0, 1973),

        # South America
        OilReserve("Orinoco Belt", 8.5, -63.5, 220.0, 1935),
        OilReserve("Tupi Field", -25.5, -42.5, 8.0, 2006),
        OilReserve("Libra Field", -23.5, -41.5, 15.0, 2010),

        # North America
        OilReserve("Prudhoe Bay", 70.3, -148.7, 25.0, 1968),
        OilReserve("East Texas Field", 32.3, -94.9, 5.6, 1930),
        OilReserve("Bakken Formation", 48.0, -103.5, 7.4, 1951),
        OilReserve("Permian Basin", 31.9, -102.3, 20.0, 1920),

        # Russia/Caspian
        OilReserve("Samotlor Field", 61.1, 76.7, 16.0, 1965),
        OilReserve("Romashkino Field", 54.8, 52.5, 17.0, 1948),
        OilReserve("Tengiz Field", 45.4, 54.4, 26.0, 1979),

        # Africa
        OilReserve("Hassi Messaoud", 31.8, 6.1, 6.4, 1956),
        OilReserve("Jubilee Field", 4.9, -2.5, 1.8, 2007),

        # North Sea
        OilReserve("Ekofisk", 56.5, 3.2, 3.6, 1969),
        OilReserve("Statfjord", 61.3, 1.8, 4.2, 1974),

        # Asia
        OilReserve("Daqing Field", 46.6, 125.0, 16.0, 1959),
        OilReserve("Cantarell Field", 19.7, -92.4, 35.0, 1976),
    ]

    # Tectonic plate boundaries (simplified)
    PLATE_BOUNDARIES = [
        # Ring of Fire (Pacific)
        {"lat_range": (-60, 70), "lon_range": (120, -60), "type": "subduction", "activity": 0.9},
        # Mid-Atlantic Ridge
        {"lat_range": (-60, 70), "lon_range": (-40, -10), "type": "divergent", "activity": 0.7},
        # Arabian Plate
        {"lat_range": (10, 40), "lon_range": (35, 65), "type": "convergent", "activity": 0.8},
        # African Rift
        {"lat_range": (-30, 20), "lon_range": (25, 50), "type": "divergent", "activity": 0.6},
    ]

    # Sedimentary basins (high biomass accumulation areas)
    SEDIMENTARY_BASINS = [
        # Major basins
        {"lat": 27.0, "lon": 50.0, "radius": 8.0, "biomass_factor": 1.5},  # Persian Gulf
        {"lat": 8.0, "lon": -64.0, "radius": 6.0, "biomass_factor": 1.4},   # Orinoco
        {"lat": 62.0, "lon": 75.0, "radius": 10.0, "biomass_factor": 1.3},  # West Siberian
        {"lat": 32.0, "lon": -102.0, "radius": 7.0, "biomass_factor": 1.4}, # Permian
        {"lat": 58.0, "lon": 2.5, "radius": 5.0, "biomass_factor": 1.2},    # North Sea
        {"lat": 20.0, "lon": -92.0, "radius": 6.0, "biomass_factor": 1.3},  # Gulf of Mexico
        {"lat": 31.0, "lon": 6.0, "radius": 7.0, "biomass_factor": 1.2},    # Saharan
        {"lat": 46.0, "lon": 125.0, "radius": 8.0, "biomass_factor": 1.3},  # Songliao
    ]

    def __init__(self, grid_resolution: float = 1.0, random_seed: int = 42):
        """
        Initialize the geological data generator

        Args:
            grid_resolution: Resolution in degrees for the global grid
            random_seed: Random seed for reproducibility
        """
        self.grid_resolution = grid_resolution
        self.random_seed = random_seed
        np.random.seed(random_seed)

    def generate_global_grid(self) -> pd.DataFrame:
        """Generate a global grid of geographical points"""
        latitudes = np.arange(-90, 90, self.grid_resolution)
        longitudes = np.arange(-180, 180, self.grid_resolution)

        lat_grid, lon_grid = np.meshgrid(latitudes, longitudes)

        df = pd.DataFrame({
            'latitude': lat_grid.flatten(),
            'longitude': lon_grid.flatten()
        })

        return df

    def calculate_distance(self, lat1: float, lon1: float,
                          lat2: float, lon2: float) -> float:
        """Calculate great circle distance in km"""
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        return 6371 * c  # Earth radius in km

    def compute_biomass_accumulation(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute biomass accumulation based on:
        - Proximity to sedimentary basins
        - Historical marine productivity
        - Organic matter preservation
        """
        biomass_score = np.zeros(len(df))

        for basin in self.SEDIMENTARY_BASINS:
            distances = np.array([
                self.calculate_distance(row['latitude'], row['longitude'],
                                      basin['lat'], basin['lon'])
                for _, row in df.iterrows()
            ])

            # Gaussian falloff from basin center
            influence = basin['biomass_factor'] * np.exp(-(distances / (basin['radius'] * 111))**2)
            biomass_score += influence

        # Add latitude-based productivity (paleo-equatorial regions)
        paleo_productivity = 0.3 * np.exp(-((df['latitude'] - 15) / 30)**2)
        biomass_score += paleo_productivity

        # Add some realistic noise
        biomass_score += np.random.normal(0, 0.1, len(df))
        biomass_score = np.clip(biomass_score, 0, 3)

        df['biomass_accumulation'] = biomass_score
        return df

    def compute_geological_pressure(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute geological pressure based on:
        - Depth/subsidence
        - Tectonic compression
        - Overburden weight
        """
        # Base pressure from sediment depth (correlated with basins)
        depth_pressure = df['biomass_accumulation'] * 0.8

        # Tectonic pressure from plate boundaries
        tectonic_pressure = np.zeros(len(df))
        for boundary in self.PLATE_BOUNDARIES:
            lat_min, lat_max = boundary['lat_range']
            lon_min, lon_max = boundary['lon_range']

            # Handle longitude wrap-around
            if lon_min > lon_max:
                in_range = ((df['latitude'] >= lat_min) & (df['latitude'] <= lat_max) &
                           ((df['longitude'] >= lon_min) | (df['longitude'] <= lon_max)))
            else:
                in_range = ((df['latitude'] >= lat_min) & (df['latitude'] <= lat_max) &
                           (df['longitude'] >= lon_min) & (df['longitude'] <= lon_max))

            tectonic_pressure[in_range] += boundary['activity']

        # Combine pressures
        total_pressure = depth_pressure + tectonic_pressure * 0.5
        total_pressure += np.random.normal(0, 0.15, len(df))
        total_pressure = np.clip(total_pressure, 0, 5)

        df['geological_pressure'] = total_pressure
        return df

    def compute_tectonic_activity(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute tectonic plate movement features:
        - Plate boundary proximity
        - Subduction zones
        - Rift zones
        """
        subduction_score = np.zeros(len(df))
        rift_score = np.zeros(len(df))

        for boundary in self.PLATE_BOUNDARIES:
            lat_min, lat_max = boundary['lat_range']
            lon_min, lon_max = boundary['lon_range']

            if lon_min > lon_max:
                in_range = ((df['latitude'] >= lat_min) & (df['latitude'] <= lat_max) &
                           ((df['longitude'] >= lon_min) | (df['longitude'] <= lon_max)))
            else:
                in_range = ((df['latitude'] >= lat_min) & (df['latitude'] <= lat_max) &
                           (df['longitude'] >= lon_min) & (df['longitude'] <= lon_max))

            if boundary['type'] == 'subduction':
                subduction_score[in_range] += boundary['activity']
            elif boundary['type'] in ['divergent', 'rift']:
                rift_score[in_range] += boundary['activity']

        df['subduction_proximity'] = np.clip(subduction_score + np.random.normal(0, 0.1, len(df)), 0, 1)
        df['rift_proximity'] = np.clip(rift_score + np.random.normal(0, 0.1, len(df)), 0, 1)

        return df

    def compute_temperature_gradient(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute geothermal gradient (important for oil maturation)
        """
        # Base gradient from tectonic activity
        base_gradient = (df['subduction_proximity'] * 0.4 +
                        df['rift_proximity'] * 0.6)

        # Depth-related gradient
        depth_gradient = df['geological_pressure'] * 0.3

        # Total gradient
        temperature_gradient = base_gradient + depth_gradient
        temperature_gradient += np.random.normal(0, 0.1, len(df))
        temperature_gradient = np.clip(temperature_gradient, 0, 2)

        df['temperature_gradient'] = temperature_gradient
        return df

    def compute_cap_rock_presence(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Estimate cap rock presence (sealing layer for oil traps)
        Based on geological structure and pressure
        """
        # Sedimentary basins more likely to have cap rocks
        cap_rock_prob = df['biomass_accumulation'] * 0.4

        # Moderate pressure indicates good preservation
        optimal_pressure = 1 - np.abs(df['geological_pressure'] - 2.0) / 3.0
        cap_rock_prob += optimal_pressure * 0.3

        cap_rock_prob += np.random.normal(0, 0.15, len(df))
        df['cap_rock_probability'] = np.clip(cap_rock_prob, 0, 1)

        return df

    def compute_porosity_permeability(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Estimate reservoir rock quality (porosity and permeability)
        """
        # Moderate pressure creates good porosity
        optimal_porosity = 1 - np.abs(df['geological_pressure'] - 1.8) / 2.5

        # Not too much tectonic deformation
        deformation_penalty = (df['subduction_proximity'] * 0.5)

        porosity = optimal_porosity - deformation_penalty
        porosity += np.random.normal(0, 0.15, len(df))
        df['porosity_index'] = np.clip(porosity, 0, 1)

        return df

    def label_oil_reserves(self, df: pd.DataFrame,
                          test_reserves_ratio: float = 0.3) -> Tuple[pd.DataFrame, List[str]]:
        """
        Label known oil reserves and split into train/test

        Args:
            df: DataFrame with geological features
            test_reserves_ratio: Fraction of reserves to hold out for testing

        Returns:
            Tuple of (labeled dataframe, list of test reserve names)
        """
        df['has_oil'] = 0
        df['reserve_size'] = 0.0
        df['is_test_reserve'] = False
        df['reserve_name'] = ''

        # Randomly select test reserves
        n_test = int(len(self.KNOWN_RESERVES) * test_reserves_ratio)
        test_indices = np.random.choice(len(self.KNOWN_RESERVES), n_test, replace=False)
        test_reserve_names = [self.KNOWN_RESERVES[i].name for i in test_indices]

        for idx, reserve in enumerate(self.KNOWN_RESERVES):
            # Find closest grid points to reserve
            distances = np.array([
                self.calculate_distance(row['latitude'], row['longitude'],
                                      reserve.latitude, reserve.longitude)
                for _, row in df.iterrows()
            ])

            # Label points within ~100 km of reserve
            nearby = distances < 100

            if nearby.any():
                # Gaussian distribution of oil around reserve center
                weights = np.exp(-(distances[nearby] / 50)**2)

                df.loc[nearby, 'has_oil'] = 1
                df.loc[nearby, 'reserve_size'] = reserve.reserves_billion_barrels * weights[weights > 0]
                df.loc[nearby, 'reserve_name'] = reserve.name

                if idx in test_indices:
                    df.loc[nearby, 'is_test_reserve'] = True

        return df, test_reserve_names

    def generate_full_dataset(self, test_ratio: float = 0.3) -> Tuple[pd.DataFrame, List[str]]:
        """
        Generate complete geological dataset with all features

        Returns:
            Tuple of (complete dataframe, list of test reserve names)
        """
        print("Generating global grid...")
        df = self.generate_global_grid()

        print("Computing biomass accumulation...")
        df = self.compute_biomass_accumulation(df)

        print("Computing geological pressure...")
        df = self.compute_geological_pressure(df)

        print("Computing tectonic activity...")
        df = self.compute_tectonic_activity(df)

        print("Computing temperature gradient...")
        df = self.compute_temperature_gradient(df)

        print("Computing cap rock presence...")
        df = self.compute_cap_rock_presence(df)

        print("Computing porosity/permeability...")
        df = self.compute_porosity_permeability(df)

        print("Labeling oil reserves...")
        df, test_reserves = self.label_oil_reserves(df, test_ratio)

        print(f"\nDataset generated:")
        print(f"  Total points: {len(df):,}")
        print(f"  Points with oil: {df['has_oil'].sum():,}")
        print(f"  Test reserves: {len(test_reserves)}")
        print(f"  Test reserve names: {', '.join(test_reserves)}")

        return df, test_reserves


if __name__ == "__main__":
    # Test the generator
    generator = GeologicalDataGenerator(grid_resolution=2.0)
    df, test_reserves = generator.generate_full_dataset()

    print("\nSample data:")
    print(df.head(10))
    print("\nFeature statistics:")
    print(df.describe())
