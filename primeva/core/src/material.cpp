#include "primeva/material.hpp"

namespace primeva {
namespace {

using P = MaterialPhase;
constexpr float kNever = 1e9f;

// Physical values are representative engineering/geology figures:
// densities (bulk, kg/m3), Mohr-Coulomb cohesion and friction angles for
// soils, tensile strength for rock masses (rock-mass values, i.e. ~1/10 of
// intact lab samples, which is what governs cave roof stability).
constexpr std::array<MaterialInfo, kMaterialCount> kTable = {{
    //  id                      name               phase       dens   hard  coh_kPa  phi  tens_kPa  poro  melt     r    g    b   dig
    {Material::Air,             "air",             P::Gas,        1.2f, 0.0f,    0.f,  0.f,      0.f, 1.00f, kNever,   0,   0,   0, false},
    {Material::Water,           "water",           P::Liquid,  1000.f, 0.0f,    0.f,  0.f,      0.f, 1.00f,    0.f,  38,  92, 140, false},
    {Material::Lava,            "lava",            P::Liquid,  2600.f, 0.0f,    0.f,  0.f,      0.f, 0.00f, kNever, 255,  96,  16, false},
    {Material::Ice,             "ice",             P::Rigid,    917.f, 3.0f,  500.f, 30.f,   1000.f, 0.00f,    0.f, 196, 222, 240, true},
    {Material::Snow,            "snow",            P::Granular, 350.f, 0.5f,    2.f, 38.f,      1.f, 0.60f,    0.f, 240, 244, 250, true},
    {Material::Topsoil,         "topsoil",         P::Cohesive,1300.f, 1.0f,   10.f, 30.f,      5.f, 0.50f, kNever,  92,  70,  48, true},
    {Material::GrassSoil,       "grass_soil",      P::Cohesive,1300.f, 1.0f,   15.f, 32.f,      8.f, 0.50f, kNever,  86, 110,  50, true},
    {Material::Peat,            "peat",            P::Cohesive,1050.f, 1.0f,    8.f, 28.f,      4.f, 0.85f, kNever,  58,  44,  30, true},
    {Material::Mud,             "mud",             P::Cohesive,1700.f, 0.8f,    5.f, 18.f,      1.f, 0.60f, kNever,  84,  66,  50, true},
    {Material::Clay,            "clay",            P::Cohesive,1750.f, 3.0f,   40.f, 22.f,     25.f, 0.45f, kNever, 150, 110,  84, true},
    {Material::Sand,            "sand",            P::Granular,1600.f, 1.0f,    0.f, 34.f,      0.f, 0.40f, kNever, 214, 194, 150, true},
    {Material::RedSand,         "red_sand",        P::Granular,1600.f, 1.0f,    0.f, 33.f,      0.f, 0.40f, kNever, 190, 100,  60, true},
    {Material::Gravel,          "gravel",          P::Granular,1800.f, 3.0f,    0.f, 40.f,      0.f, 0.30f, kNever, 130, 126, 118, true},
    {Material::Salt,            "salt",            P::Rigid,   2160.f, 3.0f,  800.f, 35.f,    500.f, 0.05f,  801.f, 236, 232, 226, true},
    {Material::Chalk,           "chalk",           P::Rigid,   1900.f, 4.0f,  600.f, 35.f,    300.f, 0.35f, kNever, 232, 230, 218, true},
    {Material::Limestone,       "limestone",       P::Rigid,   2600.f, 5.0f, 2000.f, 40.f,   1500.f, 0.10f, kNever, 200, 192, 172, true},
    {Material::Sandstone,       "sandstone",       P::Rigid,   2300.f, 5.0f, 1500.f, 38.f,   1000.f, 0.20f, kNever, 196, 160, 110, true},
    {Material::RedSandstone,    "red_sandstone",   P::Rigid,   2300.f, 5.0f, 1500.f, 38.f,   1000.f, 0.20f, kNever, 166,  82,  56, true},
    {Material::Shale,           "shale",           P::Rigid,   2500.f, 4.5f, 1000.f, 30.f,    600.f, 0.08f, kNever,  96,  96, 100, true},
    {Material::Coal,            "coal",            P::Rigid,   1350.f, 4.0f,  800.f, 35.f,    400.f, 0.10f, kNever,  34,  32,  30, true},
    {Material::Basalt,          "basalt",          P::Rigid,   2900.f, 7.0f, 4000.f, 45.f,   3000.f, 0.05f, 1200.f,  58,  58,  62, true},
    {Material::Obsidian,        "obsidian",        P::Rigid,   2400.f, 7.5f, 3000.f, 45.f,   2000.f, 0.00f, 1000.f,  24,  20,  30, true},
    {Material::Granite,         "granite",         P::Rigid,   2700.f, 7.0f, 5000.f, 48.f,   3500.f, 0.01f, 1250.f, 160, 150, 146, true},
    {Material::Marble,          "marble",          P::Rigid,   2700.f, 6.0f, 3500.f, 42.f,   2500.f, 0.01f, kNever, 228, 226, 222, true},
    {Material::Tuff,            "tuff",            P::Rigid,   1500.f, 4.0f,  700.f, 36.f,    400.f, 0.40f, 1100.f, 170, 150, 120, true},
    {Material::Ash,             "ash",             P::Granular, 900.f, 1.0f,    1.f, 35.f,      0.f, 0.55f, 1100.f, 110, 106, 104, true},
    {Material::IronOre,         "iron_ore",        P::Rigid,   5000.f, 8.0f, 4000.f, 42.f,   2500.f, 0.03f, 1538.f, 140,  80,  60, true},
    {Material::CopperOre,       "copper_ore",      P::Rigid,   4200.f, 8.0f, 3500.f, 42.f,   2200.f, 0.03f, 1085.f,  70, 140, 120, true},
    {Material::Sulfur,          "sulfur",          P::Rigid,   2070.f, 3.0f,  300.f, 35.f,    150.f, 0.05f,  115.f, 230, 210,  40, true},
    {Material::QuartzCrystal,   "quartz_crystal",  P::Rigid,   2650.f, 9.0f, 6000.f, 50.f,   4000.f, 0.00f, 1670.f, 236, 240, 244, true},
    {Material::AmethystCrystal, "amethyst_crystal",P::Rigid,   2650.f, 9.0f, 6000.f, 50.f,   4000.f, 0.00f, 1670.f, 150,  90, 190, true},
    {Material::Bedrock,         "bedrock",         P::Rigid,   3000.f,10.0f,  1e6f,  60.f,    1e6f,  0.00f, kNever,  28,  26,  28, false},
    {Material::FungalMat,       "fungal_mat",      P::Cohesive, 600.f, 1.5f,   20.f, 30.f,     10.f, 0.70f, kNever,  80, 150, 140, true},
    {Material::Coral,           "coral",           P::Rigid,   1500.f, 4.0f,  600.f, 38.f,    300.f, 0.45f, kNever, 230, 140, 120, true},
    {Material::Wood,            "wood",            P::Rigid,    600.f, 3.0f, 1000.f, 30.f,   4000.f, 0.50f, kNever, 120,  84,  52, true},
}};

constexpr bool table_is_ordered() {
  for (int i = 0; i < kMaterialCount; ++i)
    if (static_cast<int>(kTable[i].id) != i) return false;
  return true;
}
static_assert(table_is_ordered(), "material table must be indexed by Material id");

}  // namespace

const MaterialInfo& material_info(Material m) { return kTable[static_cast<size_t>(m) < kTable.size() ? static_cast<size_t>(m) : 0]; }
const std::array<MaterialInfo, kMaterialCount>& material_table() { return kTable; }

std::optional<Material> material_from_name(std::string_view name) {
  for (const auto& m : kTable)
    if (m.name == name) return m.id;
  return std::nullopt;
}

}  // namespace primeva
