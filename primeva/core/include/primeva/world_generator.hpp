#pragma once

#include <memory>

#include "primeva/biome.hpp"
#include "primeva/chunk.hpp"
#include "primeva/macro_map.hpp"

namespace primeva {

struct GeneratorParams {
  uint64_t seed = 0x5052494D455641ULL;
  bool caves = true;
  bool ores = true;
  double micro_roughness_m = 0.06;  // sub-metre surface grain
};

// Everything the generator knows about one vertical column of the world.
struct ColumnInfo {
  double macro_elevation_m = 0;
  double surface_m = 0;        // final terrain surface height
  double water_m = -1e30;      // surface water level (sea, lake, river) or -1e30
  double water_table_m = -1e30;
  double slope = 0;            // |grad h| (filled by chunk generation; single-column query estimates it)
  bool river = false;
  double river_discharge_m3s = 0;
  Biome biome = Biome::JurassicFernPrairie;  // dominant macro biome
  Era era = Era::Jurassic;
  double volcanic = 0;
  double karst = 0;            // weight of limestone/chalk-hosted biomes
  double cave_density = 1;
  double precip_mm = 0;
  double temperature_c = 0;
  double magma_m = -1e30;      // top of molten rock pools in the deep caverns
  double stack_scale = 1;      // local variation of soil horizon thickness
  double sediment_m = 4;       // unconsolidated sediment thickness below the soil stack
  double inv_grad_norm = 1;    // 1/sqrt(1+|grad h|^2): heightfield -> distance correction
};

// What occupies a given point after full generation (debug / gameplay queries).
struct PointInfo {
  Voxel voxel;
  Biome underground_biome;  // meaningful when below the surface
  double depth_m;           // below terrain surface (negative above)
};

// Deterministic world generator. generate() is a pure function of
// (macro map, params, chunk coordinate, lod): thread safe, no shared state.
class WorldGenerator {
 public:
  WorldGenerator(std::shared_ptr<const MacroMap> macro, GeneratorParams params);

  void generate(ChunkCoord c, Chunk& out, int lod = 0) const;

  ColumnInfo column(double x_m, double z_m) const;
  PointInfo point(double x_m, double y_m, double z_m) const;
  Biome underground_biome(double x_m, double y_m, double z_m) const;

  const MacroMap& macro() const { return *macro_; }
  const GeneratorParams& params() const { return params_; }

  // Cave field (metres, negative = open cavity) and auxiliary channels.
  struct CaveSample {
    double total = 1e9;   // union of all cavity systems
    double geode = 1e9;   // distance to the nearest active geode void
    double lava = 1e9;    // lava tube field
    double ore_a = 1.0;   // vein noise channels
    double ore_b = 1.0;
    double ore_body = -1.0;  // low-frequency deposit mask: veins only where it is high
  };
  CaveSample cave_field(double x, double y, double z, const ColumnInfo& col) const;

 private:
  void column_into(double x_m, double z_m, ColumnInfo& col, double voxel_size) const;
  Material solid_material(double x, double y, double z, const ColumnInfo& col, double depth, const CaveSample& cs,
                          bool cave_above) const;
  Material fluid_material(double y, const ColumnInfo& col, bool above_terrain, double depth) const;
  Biome underground_biome_for(double y, double depth, const ColumnInfo& col, const CaveSample& cs) const;

  std::shared_ptr<const MacroMap> macro_;
  GeneratorParams params_;
};

}  // namespace primeva
