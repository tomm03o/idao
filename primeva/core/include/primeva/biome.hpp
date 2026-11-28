#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string_view>

#include "primeva/material.hpp"

namespace primeva {

enum class Era : uint8_t {
  Carboniferous = 0,
  Permian,
  Triassic,
  Jurassic,
  Cretaceous,
  Paleogene,
  Neogene,
  Pleistocene,
  Count
};
inline constexpr int kEraCount = static_cast<int>(Era::Count);
std::string_view era_name(Era e);

enum class BiomeLayer : uint8_t { Surface, Aquatic, Underground };

// Stable ids (append only). Names match data/world/biomes.json and
// data/creatures/creatures.json.
enum class Biome : uint8_t {
  CarboniferousCoalSwamp = 0,
  CarboniferousGiantFernForest,
  PermianRedDesert,
  PermianSaltFlats,
  TriassicConiferBadlands,
  TriassicRiftLakes,
  JurassicFernPrairie,
  JurassicAraucariaForest,
  JurassicLagoonArchipelago,
  CretaceousFloodplainDelta,
  CretaceousAngiospermForest,
  CretaceousVolcanicHighlands,
  CretaceousChalkCoast,
  PaleogeneTropicalRainforest,
  NeogeneSavanna,
  PleistoceneMammothSteppe,
  PleistoceneGlacialAlps,
  ShallowReefSea,
  OpenOceanPelagic,
  KarstCaves,
  LavaTubes,
  CrystalGeodeCaverns,
  UndergroundRivers,
  FungalDeepCaverns,
  AbyssalMagmaDepths,
  Count
};
inline constexpr int kBiomeCount = static_cast<int>(Biome::Count);

struct SurfaceLayer {
  Material material = Material::Air;
  float thickness_m = 0.f;
};

// Parameters consumed by the world generator. Values are authored defaults;
// data/world/biomes.json may override them at load time.
struct BiomeDef {
  Biome id;
  std::string_view name;
  Era era;
  BiomeLayer layer;
  std::array<SurfaceLayer, 3> surface;  // top-down stack below the surface
  Material sediment;                    // fill between surface stack and bedrock
  Material rock_primary;                // dominant sedimentary/igneous bedrock
  Material rock_secondary;              // interbedded strata
  float strata_thickness_m;             // mean bed thickness of interbedding
  // Micro relief (added on top of the baked macro elevation)
  float detail_amp_m;                   // amplitude of local relief
  float detail_wavelength_m;            // largest detail wavelength
  float ridge;                          // 0 = rolling fBm, 1 = sharp ridged
  float billow;                         // 0..1 rounded dunes / hummocks
  float terrace;                        // 0..1 stepped strata (badlands, mesas)
  float cave_density;                   // multiplier on cave carving under this biome
  uint8_t r, g, b;                      // preview colour
};

const BiomeDef& biome_def(Biome b);
const std::array<BiomeDef, kBiomeCount>& biome_table();
std::optional<Biome> biome_from_name(std::string_view name);

}  // namespace primeva
