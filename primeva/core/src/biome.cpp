#include "primeva/biome.hpp"

namespace primeva {
namespace {

using M = Material;
using E = Era;
using L = BiomeLayer;
using B = Biome;

constexpr std::array<std::string_view, kEraCount> kEraNames = {
    "carboniferous", "permian", "triassic", "jurassic", "cretaceous", "paleogene", "neogene", "pleistocene"};

// Surface stacks follow real pedology for the analogous modern/ancient
// environment: e.g. coal swamps = peat over mud over shale/coal measures;
// red desert = red sand over red sandstone with evaporites; chalk coast =
// thin rendzina soil over chalk.
constexpr std::array<BiomeDef, kBiomeCount> kBiomes = {{
    {B::CarboniferousCoalSwamp, "carboniferous_coal_swamp", E::Carboniferous, L::Surface,
     {{{M::Peat, 1.5f}, {M::Mud, 2.0f}, {M::Clay, 3.0f}}}, M::Clay, M::Shale, M::Coal, 3.0f,
     2.0f, 60.f, 0.0f, 0.3f, 0.0f, 0.6f, 52, 78, 46},
    {B::CarboniferousGiantFernForest, "carboniferous_giant_fern_forest", E::Carboniferous, L::Surface,
     {{{M::GrassSoil, 0.4f}, {M::Topsoil, 1.2f}, {M::Clay, 2.5f}}}, M::Clay, M::Shale, M::Sandstone, 4.0f,
     8.0f, 220.f, 0.2f, 0.2f, 0.0f, 0.8f, 46, 104, 44},
    {B::PermianRedDesert, "permian_red_desert", E::Permian, L::Surface,
     {{{M::RedSand, 3.0f}, {M::RedSand, 2.0f}, {M::Gravel, 1.0f}}}, M::RedSand, M::RedSandstone, M::Sandstone, 6.0f,
     14.0f, 300.f, 0.1f, 0.9f, 0.15f, 0.7f, 200, 104, 64},
    {B::PermianSaltFlats, "permian_salt_flats", E::Permian, L::Surface,
     {{{M::Salt, 0.6f}, {M::Clay, 2.0f}, {M::Salt, 4.0f}}}, M::Clay, M::RedSandstone, M::Salt, 5.0f,
     0.4f, 400.f, 0.0f, 0.0f, 0.0f, 0.3f, 232, 226, 214},
    {B::TriassicConiferBadlands, "triassic_conifer_badlands", E::Triassic, L::Surface,
     {{{M::Topsoil, 0.3f}, {M::Clay, 1.0f}, {M::Gravel, 1.0f}}}, M::Clay, M::Sandstone, M::RedSandstone, 2.5f,
     28.0f, 180.f, 0.6f, 0.0f, 0.75f, 1.0f, 176, 120, 84},
    {B::TriassicRiftLakes, "triassic_rift_lakes", E::Triassic, L::Surface,
     {{{M::GrassSoil, 0.4f}, {M::Mud, 1.5f}, {M::Clay, 3.0f}}}, M::Clay, M::Shale, M::Limestone, 3.0f,
     10.0f, 260.f, 0.3f, 0.1f, 0.2f, 0.8f, 98, 132, 92},
    {B::JurassicFernPrairie, "jurassic_fern_prairie", E::Jurassic, L::Surface,
     {{{M::GrassSoil, 0.5f}, {M::Topsoil, 1.5f}, {M::Clay, 2.0f}}}, M::Clay, M::Limestone, M::Shale, 4.0f,
     6.0f, 350.f, 0.0f, 0.3f, 0.0f, 1.0f, 128, 150, 70},
    {B::JurassicAraucariaForest, "jurassic_araucaria_forest", E::Jurassic, L::Surface,
     {{{M::GrassSoil, 0.4f}, {M::Topsoil, 1.4f}, {M::Clay, 2.0f}}}, M::Clay, M::Limestone, M::Sandstone, 5.0f,
     16.0f, 240.f, 0.3f, 0.1f, 0.0f, 1.3f, 40, 86, 52},
    {B::JurassicLagoonArchipelago, "jurassic_lagoon_archipelago", E::Jurassic, L::Surface,
     {{{M::Sand, 1.5f}, {M::Mud, 1.0f}, {M::Limestone, 2.0f}}}, M::Sand, M::Limestone, M::Limestone, 1.0f,
     3.0f, 200.f, 0.0f, 0.6f, 0.0f, 1.2f, 220, 206, 160},
    {B::CretaceousFloodplainDelta, "cretaceous_floodplain_delta", E::Cretaceous, L::Surface,
     {{{M::GrassSoil, 0.5f}, {M::Mud, 2.5f}, {M::Sand, 3.0f}}}, M::Sand, M::Shale, M::Sandstone, 3.0f,
     1.5f, 150.f, 0.0f, 0.2f, 0.0f, 0.4f, 112, 140, 76},
    {B::CretaceousAngiospermForest, "cretaceous_angiosperm_forest", E::Cretaceous, L::Surface,
     {{{M::GrassSoil, 0.5f}, {M::Topsoil, 1.8f}, {M::Clay, 2.0f}}}, M::Clay, M::Sandstone, M::Shale, 4.0f,
     12.0f, 260.f, 0.2f, 0.2f, 0.0f, 1.0f, 56, 112, 48},
    {B::CretaceousVolcanicHighlands, "cretaceous_volcanic_highlands", E::Cretaceous, L::Surface,
     {{{M::Ash, 0.8f}, {M::Tuff, 2.0f}, {M::Basalt, 2.0f}}}, M::Tuff, M::Basalt, M::Tuff, 6.0f,
     40.0f, 300.f, 0.7f, 0.0f, 0.1f, 1.1f, 70, 64, 62},
    {B::CretaceousChalkCoast, "cretaceous_chalk_coast", E::Cretaceous, L::Surface,
     {{{M::GrassSoil, 0.3f}, {M::Topsoil, 0.4f}, {M::Chalk, 2.0f}}}, M::Chalk, M::Chalk, M::Limestone, 2.0f,
     10.0f, 250.f, 0.2f, 0.1f, 0.3f, 1.2f, 200, 214, 170},
    {B::PaleogeneTropicalRainforest, "paleogene_tropical_rainforest", E::Paleogene, L::Surface,
     {{{M::GrassSoil, 0.6f}, {M::Topsoil, 2.5f}, {M::Clay, 4.0f}}}, M::Clay, M::Limestone, M::Clay, 5.0f,
     18.0f, 200.f, 0.4f, 0.3f, 0.0f, 1.4f, 24, 96, 40},
    {B::NeogeneSavanna, "neogene_savanna", E::Neogene, L::Surface,
     {{{M::GrassSoil, 0.4f}, {M::Topsoil, 1.0f}, {M::Clay, 2.0f}}}, M::Sand, M::Sandstone, M::Limestone, 5.0f,
     5.0f, 500.f, 0.0f, 0.4f, 0.1f, 0.8f, 184, 168, 88},
    {B::PleistoceneMammothSteppe, "pleistocene_mammoth_steppe", E::Pleistocene, L::Surface,
     {{{M::GrassSoil, 0.4f}, {M::Topsoil, 0.8f}, {M::Gravel, 3.0f}}}, M::Gravel, M::Granite, M::Shale, 8.0f,
     7.0f, 450.f, 0.1f, 0.4f, 0.0f, 0.6f, 150, 156, 110},
    {B::PleistoceneGlacialAlps, "pleistocene_glacial_alps", E::Pleistocene, L::Surface,
     {{{M::Snow, 1.0f}, {M::Ice, 3.0f}, {M::Gravel, 1.0f}}}, M::Gravel, M::Granite, M::Marble, 10.0f,
     35.0f, 260.f, 0.9f, 0.0f, 0.0f, 0.7f, 226, 232, 240},
    {B::ShallowReefSea, "shallow_reef_sea", E::Jurassic, L::Aquatic,
     {{{M::Sand, 1.0f}, {M::Coral, 2.0f}, {M::Limestone, 3.0f}}}, M::Sand, M::Limestone, M::Chalk, 3.0f,
     3.0f, 120.f, 0.2f, 0.5f, 0.0f, 0.6f, 64, 170, 190},
    {B::OpenOceanPelagic, "open_ocean_pelagic", E::Cretaceous, L::Aquatic,
     {{{M::Mud, 2.0f}, {M::Clay, 4.0f}, {M::Chalk, 6.0f}}}, M::Clay, M::Basalt, M::Chalk, 8.0f,
     6.0f, 800.f, 0.3f, 0.2f, 0.0f, 0.3f, 20, 48, 96},
    // Underground biomes are chosen in 3D by depth + host rock, not from the
    // macro map; their stacks describe floor/wall coatings.
    {B::KarstCaves, "karst_caves", E::Jurassic, L::Underground,
     {{{M::Clay, 0.3f}, {M::Limestone, 1.0f}, {M::Limestone, 1.0f}}}, M::Limestone, M::Limestone, M::Marble, 4.0f,
     0.f, 1.f, 0.f, 0.f, 0.f, 1.6f, 180, 170, 150},
    {B::LavaTubes, "lava_tubes", E::Cretaceous, L::Underground,
     {{{M::Basalt, 0.5f}, {M::Obsidian, 0.3f}, {M::Basalt, 1.0f}}}, M::Basalt, M::Basalt, M::Obsidian, 4.0f,
     0.f, 1.f, 0.f, 0.f, 0.f, 1.0f, 90, 40, 30},
    {B::CrystalGeodeCaverns, "crystal_geode_caverns", E::Permian, L::Underground,
     {{{M::QuartzCrystal, 1.0f}, {M::AmethystCrystal, 0.5f}, {M::Granite, 1.0f}}}, M::Granite, M::Granite, M::Marble, 8.0f,
     0.f, 1.f, 0.f, 0.f, 0.f, 1.0f, 170, 120, 210},
    {B::UndergroundRivers, "underground_rivers", E::Neogene, L::Underground,
     {{{M::Gravel, 0.5f}, {M::Sand, 0.5f}, {M::Limestone, 1.0f}}}, M::Gravel, M::Limestone, M::Sandstone, 4.0f,
     0.f, 1.f, 0.f, 0.f, 0.f, 1.0f, 60, 110, 160},
    {B::FungalDeepCaverns, "fungal_deep_caverns", E::Carboniferous, L::Underground,
     {{{M::FungalMat, 0.6f}, {M::Clay, 0.5f}, {M::Shale, 1.0f}}}, M::Shale, M::Shale, M::Granite, 6.0f,
     0.f, 1.f, 0.f, 0.f, 0.f, 1.3f, 60, 160, 140},
    {B::AbyssalMagmaDepths, "abyssal_magma_depths", E::Permian, L::Underground,
     {{{M::Obsidian, 0.5f}, {M::Basalt, 1.0f}, {M::Sulfur, 0.3f}}}, M::Basalt, M::Basalt, M::Granite, 10.0f,
     0.f, 1.f, 0.f, 0.f, 0.f, 1.2f, 140, 30, 20},
}};

constexpr bool biome_table_ordered() {
  for (int i = 0; i < kBiomeCount; ++i)
    if (static_cast<int>(kBiomes[i].id) != i) return false;
  return true;
}
static_assert(biome_table_ordered(), "biome table must be indexed by Biome id");

}  // namespace

std::string_view era_name(Era e) { return kEraNames[static_cast<size_t>(e) % kEraNames.size()]; }
const BiomeDef& biome_def(Biome b) { return kBiomes[static_cast<size_t>(b) % kBiomes.size()]; }
const std::array<BiomeDef, kBiomeCount>& biome_table() { return kBiomes; }
std::optional<Biome> biome_from_name(std::string_view name) {
  for (const auto& b : kBiomes)
    if (b.name == name) return b.id;
  return std::nullopt;
}

}  // namespace primeva
