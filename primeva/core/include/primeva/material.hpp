#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string_view>

namespace primeva {

// Material ids are stable on-disk values: append only, never reorder.
enum class Material : uint16_t {
  Air = 0,
  Water,
  Lava,
  Ice,
  Snow,
  Topsoil,
  GrassSoil,
  Peat,
  Mud,
  Clay,
  Sand,
  RedSand,
  Gravel,
  Salt,
  Chalk,
  Limestone,
  Sandstone,
  RedSandstone,
  Shale,
  Coal,
  Basalt,
  Obsidian,
  Granite,
  Marble,
  Tuff,
  Ash,
  IronOre,
  CopperOre,
  Sulfur,
  QuartzCrystal,
  AmethystCrystal,
  Bedrock,
  FungalMat,
  Coral,
  Wood,
  Count
};
inline constexpr int kMaterialCount = static_cast<int>(Material::Count);

// How a material responds to loss of support and to flow. Consumed by the
// voxel physics stage (structural integrity, granular slumping, fluids).
enum class MaterialPhase : uint8_t {
  Gas,       // air: empty space
  Liquid,    // water, lava: flows, has viscosity
  Granular,  // sand, gravel, ash, snow: slumps to its angle of repose
  Cohesive,  // soils, clay, peat: holds small overhangs, slumps when saturated
  Rigid,     // rock, crystal, ice, wood: breaks into rigid fragments when unsupported
};

struct MaterialInfo {
  Material id;
  std::string_view name;          // stable snake_case id used by data files
  MaterialPhase phase;
  float density_kg_m3;            // bulk density
  float hardness;                 // 0..10 game scale: digging tool / creature tier needed
  float cohesion_kpa;             // shear cohesion (Mohr-Coulomb c)
  float friction_angle_deg;       // internal friction / angle of repose for granular
  float tensile_strength_kpa;     // limits unsupported overhang span for rigid/cohesive
  float porosity;                 // 0..1, water holding / aquifer permeability proxy
  float melt_point_c;             // phase change (ice, rock -> lava); NaN-free: 1e9 = never
  uint8_t r, g, b;                // linear-ish preview albedo (sRGB bytes)
  bool diggable;
};

const MaterialInfo& material_info(Material m);
const std::array<MaterialInfo, kMaterialCount>& material_table();
std::optional<Material> material_from_name(std::string_view name);

inline bool is_solid(Material m) {
  const auto p = material_info(m).phase;
  return p != MaterialPhase::Gas && p != MaterialPhase::Liquid;
}
inline bool is_fluid(Material m) { return material_info(m).phase == MaterialPhase::Liquid; }

}  // namespace primeva
