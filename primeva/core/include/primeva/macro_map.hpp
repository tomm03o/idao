#pragma once

// MacroMap: the offline-baked continental layer of the world.
//
// The world is far too large to author or store at voxel resolution, so it is
// built in two stages:
//   1. bake (offline, minutes): continent shape, mountain belts, volcanoes,
//      hydraulic + thermal erosion, depression filling (lakes), D8 drainage
//      with physically scaled river discharge, climate (latitude, lapse rate,
//      westerly moisture transport with orographic rain + rain shadow),
//      temporal-refugium regions with an assigned geological era, biomes.
//      The result ships with the game as a data asset (~20 B per cell).
//   2. runtime (WorldGenerator): bicubic sampling of this map + deterministic
//      micro detail, rivers, strata, caves, at voxel resolution.

#include <cstdint>
#include <string>
#include <vector>

#include "primeva/biome.hpp"

namespace primeva {

struct MacroBakeParams {
  uint64_t seed = 0x5052494D455641ULL;  // "PRIMEVA"
  double world_size_m = 1048576.0;      // square side (2^20 m ~ 1049 km)
  int resolution = 4096;                // cells per side -> 256 m cells
  double target_land_km2 = 301340.0;    // area of Italy
  // continent
  double continent_wavelength_m = 420000.0;
  double coast_warp_m = 60000.0;
  double max_ocean_depth_m = 4200.0;
  // relief
  double mountain_height_m = 3600.0;
  double mountain_wavelength_m = 140000.0;
  double hill_height_m = 420.0;
  int volcano_count = 18;
  // erosion (droplet model; heights handled in cell units)
  double erosion_droplets_per_cell = 0.6;
  int erosion_max_steps = 72;
  double erosion_inertia = 0.06;
  double erosion_capacity = 6.0;
  double erosion_min_slope = 0.002;
  double erosion_deposition = 0.25;
  double erosion_erosion = 0.35;
  double erosion_evaporation = 0.015;
  double erosion_gravity = 6.0;
  int erosion_radius = 2;
  int thermal_iterations = 24;
  double thermal_talus_deg = 38.0;
  // climate
  double sea_temp_north_c = 9.0;
  double sea_temp_south_c = 20.5;
  double lapse_rate_c_per_m = 0.0065;
  // regions (temporal refugia)
  double region_size_m = 72000.0;
  // rivers
  double runoff_coefficient = 0.42;
  double river_min_discharge_m3s = 4.0;
};

struct Volcano {
  double x_m, z_m;
  double radius_m;
  double height_m;
};

class MacroMap {
 public:
  MacroMap() = default;

  // Full offline bake. `progress` (optional) receives human readable stages.
  static MacroMap bake(const MacroBakeParams& p, void (*progress)(const char*) = nullptr);

  bool save(const std::string& path) const;
  static bool load(const std::string& path, MacroMap& out);

  // ---- grid access ----
  int resolution() const { return res_; }
  double cell_size_m() const { return cell_; }
  double world_size_m() const { return cell_ * res_; }
  uint64_t seed() const { return seed_; }
  size_t idx(int i, int j) const { return static_cast<size_t>(j) * res_ + i; }

  float elevation(int i, int j) const { return elev_[idx(clampi(i), clampi(j))]; }
  float water_level(int i, int j) const { return water_[idx(clampi(i), clampi(j))]; }
  float discharge(int i, int j) const { return discharge_[idx(clampi(i), clampi(j))]; }
  // Depression-filled surface (monotone non-increasing along flow paths).
  float filled_surface(int i, int j) const { return surface_[idx(clampi(i), clampi(j))]; }
  uint8_t flow_dir(int i, int j) const { return flow_[idx(clampi(i), clampi(j))]; }
  Biome biome(int i, int j) const { return static_cast<Biome>(biome_[idx(clampi(i), clampi(j))]); }
  Era era(int i, int j) const { return static_cast<Era>(era_[idx(clampi(i), clampi(j))]); }
  float temperature_c(int i, int j) const { return temp_[idx(clampi(i), clampi(j))] * 0.01f; }
  float precipitation_mm(int i, int j) const { return precip_[idx(clampi(i), clampi(j))]; }
  float volcanic(int i, int j) const { return volcanic_[idx(clampi(i), clampi(j))] * (1.0f / 255.0f); }
  bool is_ocean(int i, int j) const { return ocean_[idx(clampi(i), clampi(j))] != 0; }
  bool is_lake(int i, int j) const;
  const std::vector<Volcano>& volcanoes() const { return volcanoes_; }

  // ---- continuous sampling in world metres (x east, z south) ----
  double sample_elevation(double x_m, double z_m) const;  // Catmull-Rom bicubic
  struct BiomeWeights {
    Biome biome[4];
    double weight[4];
    int count = 0;
  };
  BiomeWeights sample_biomes(double x_m, double z_m) const;  // bilinear weights
  double sample_volcanic(double x_m, double z_m) const;
  double sample_precip(double x_m, double z_m) const;
  double sample_temperature(double x_m, double z_m) const;

  // Standing water (ocean + lakes): `fraction` is the bilinear coverage of
  // water cells around (x,z) (shoreline at 0.5), `level` the water surface of
  // those cells (0 for ocean). fraction == 0 -> dry land.
  struct StandingWater {
    double fraction = 0.0;
    double level = -1e30;
  };
  StandingWater sample_standing_water(double x_m, double z_m) const;

  struct RiverSample {
    bool in_influence = false;  // within bank zone of a river
    double distance_m = 1e30;   // to channel centreline
    double surface_m = 0.0;     // water surface height on the centreline
    double half_width_m = 0.0;
    double depth_m = 0.0;       // channel depth at the centreline
    double discharge_m3s = 0.0;
  };
  // Channel geometry from Leopold & Maddock hydraulic geometry:
  //   width = 4.0 Q^0.5, depth = 0.32 Q^0.38  (metres, Q in m3/s)
  RiverSample sample_river(double x_m, double z_m) const;

  // Statistics
  double land_area_km2() const;
  std::vector<double> biome_area_km2() const;
  std::vector<double> era_area_km2() const;

  // Neighbour offsets for D8 flow, index 0..7.
  static constexpr int kDx[8] = {1, 1, 0, -1, -1, -1, 0, 1};
  static constexpr int kDz[8] = {0, 1, 1, 1, 0, -1, -1, -1};
  static constexpr uint8_t kNoFlow = 255;

 private:
  int clampi(int v) const { return v < 0 ? 0 : (v >= res_ ? res_ - 1 : v); }

  int res_ = 0;
  double cell_ = 0.0;
  uint64_t seed_ = 0;
  std::vector<float> elev_;       // m, sea level 0
  std::vector<float> water_;      // m, standing water surface or -1e30
  std::vector<float> surface_;    // m, priority-flood filled surface
  std::vector<float> discharge_;  // m3/s mean annual
  std::vector<uint8_t> flow_;     // D8 direction or kNoFlow
  std::vector<uint8_t> biome_;
  std::vector<uint8_t> era_;
  std::vector<int16_t> temp_;     // 0.01 C
  std::vector<float> precip_;     // mm / year
  std::vector<uint8_t> volcanic_; // 0..255 influence
  std::vector<uint8_t> ocean_;
  std::vector<Volcano> volcanoes_;

  friend class MacroBaker;
};

}  // namespace primeva
