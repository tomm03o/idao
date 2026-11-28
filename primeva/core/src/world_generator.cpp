#include "primeva/world_generator.hpp"

#include <algorithm>
#include <cmath>
#include <vector>

#include "primeva/dmath.hpp"
#include "primeva/hash.hpp"
#include "primeva/noise.hpp"

namespace primeva {

namespace {

constexpr double kBig = 1e9;
constexpr double kNoWater = -1e30;

struct Blend {
  double amp = 0, wavelength = 1, ridge = 0, billow = 0, terrace = 0, cave_density = 1, strata_thick = 4, karst = 0;
  Biome dominant = Biome::JurassicFernPrairie;
};

Blend blend_biomes(const MacroMap::BiomeWeights& w) {
  Blend b;
  b.amp = b.wavelength = b.ridge = b.billow = b.terrace = b.cave_density = b.strata_thick = 0;
  double best = -1;
  for (int k = 0; k < w.count; ++k) {
    const BiomeDef& d = biome_def(w.biome[k]);
    const double ww = w.weight[k];
    b.amp += ww * d.detail_amp_m;
    b.wavelength += ww * d.detail_wavelength_m;
    b.ridge += ww * d.ridge;
    b.billow += ww * d.billow;
    b.terrace += ww * d.terrace;
    b.cave_density += ww * d.cave_density;
    b.strata_thick += ww * d.strata_thickness_m;
    if (d.rock_primary == Material::Limestone || d.rock_primary == Material::Chalk) b.karst += ww;
    if (ww > best) { best = ww; b.dominant = w.biome[k]; }
  }
  b.wavelength = std::max(b.wavelength, 1.0);
  return b;
}

inline double lerp_d(double a, double b, double t) { return a + (b - a) * t; }

}  // namespace

WorldGenerator::WorldGenerator(std::shared_ptr<const MacroMap> macro, GeneratorParams params)
    : macro_(std::move(macro)), params_(params) {}

// ---------------------------------------------------------------------------
// Columns: macro elevation + biome-blended micro relief + rivers + water.
// ---------------------------------------------------------------------------
void WorldGenerator::column_into(double x, double z, ColumnInfo& col, double vs) const {
  const MacroMap& m = *macro_;
  const uint64_t s = params_.seed;
  const double macro = m.sample_elevation(x, z);
  const Blend b = blend_biomes(m.sample_biomes(x, z));
  const MacroMap::StandingWater sw = m.sample_standing_water(x, z);

  col.macro_elevation_m = macro;
  col.biome = b.dominant;
  col.era = biome_def(b.dominant).era;
  col.volcanic = m.sample_volcanic(x, z);
  col.precip_mm = m.sample_precip(x, z);
  col.temperature_c = m.sample_temperature(x, z);
  col.karst = b.karst;
  col.cave_density = b.cave_density;

  // Micro relief is evaluated PER BIOME with that biome's fixed wavelength and
  // the resulting heights are blended. Blending the wavelength itself would
  // make the noise phase x / lambda(x) sweep wildly at continental x
  // (x ~ 1e6 m), producing discontinuous noise in every biome transition.
  const MacroMap::BiomeWeights bw = m.sample_biomes(x, z);
  double att = 1.0;
  // Calmer relief near water, faded in with the water coverage so it is
  // continuous where the coverage starts (fraction 0 -> no effect).
  if (sw.fraction > 0.0)
    att = lerp_d(1.0, 0.2 + 0.8 * smoothstep(0.0, 10.0, std::abs(macro - sw.level)), smoothstep(0.0, 0.4, sw.fraction));
  double h = 0.0;
  for (int k = 0; k < bw.count; ++k) {
    const BiomeDef& d = biome_def(bw.biome[k]);
    const double lambda = std::max(1.0, static_cast<double>(d.detail_wavelength_m));
    // Band-limit: stop once the wavelength drops below two voxels at this LOD.
    int oct = 0;
    for (double w = lambda; w > 2.0 * vs && oct < 16; w *= 0.5) ++oct;
    oct = std::max(oct, 1);
    const double fx = x / lambda, fz = z / lambda;
    const double w_r = d.ridge * (1.0 - d.billow), w_b = d.billow, w_f = (1.0 - d.ridge) * (1.0 - d.billow);
    double n = 0.0;
    if (w_f > 1e-6) n += w_f * noise::fbm2(s + 81, fx, fz, oct, 2.0, 0.5);
    if (w_r > 1e-6) n += w_r * (noise::ridged2(s + 82, fx, fz, oct, 2.0, 0.5) * 2.0 - 1.0);
    if (w_b > 1e-6) n += w_b * (noise::billow2(s + 83, fx, fz, oct, 2.0, 0.5) * 2.0 - 1.0);
    double hk = macro + d.detail_amp_m * att * n;
    if (d.terrace > 1e-3) {
      const double step = std::max(1.0, d.strata_thickness_m * 1.5);
      const double t = hk / step;
      const double fl = std::floor(t);
      hk = lerp_d(hk, (fl + smoothstep(0.25, 0.75, t - fl)) * step, static_cast<double>(d.terrace));
    }
    h += bw.weight[k] * hk;
  }
  if (vs < 0.5) h += params_.micro_roughness_m * noise::perlin2(s + 84, x / 1.7, z / 1.7);

  // Shorelines: inside the water body (coverage >= 0.5) the bed is kept below
  // the surface and deepens inward; in the shore band the land is raised
  // smoothly above the water level, so water is always contained by terrain
  // (no free-standing water walls) and beaches / banks form naturally.
  double water = kNoWater;
  if (sw.fraction > 0.0) {
    // Shore profile g(f): continuous through the shoreline (f = 0.5 -> level).
    const double g = sw.fraction < 0.5 ? sw.level + 4.0 * (0.5 - sw.fraction) : sw.level - 6.0 * (sw.fraction - 0.5);
    double hb = sw.fraction < 0.5 ? h + smoothstep(0.0, 0.15, sw.fraction) * std::max(0.0, g - h)  // raise banks
                                  : std::min(h, g);                                                  // keep bed submerged
    const double pin = 1.0 - smoothstep(0.0, 0.1, std::abs(sw.fraction - 0.5));  // pin to g at the shoreline
    h = lerp_d(hb, g, pin);
    if (sw.fraction >= 0.5) water = sw.level;
  }
  col.river = false;
  col.river_discharge_m3s = 0;
  const MacroMap::RiverSample rs = m.sample_river(x, z);
  if (rs.in_influence) {
    const double bank = std::max(6.0, rs.half_width_m * 1.5);
    if (rs.distance_m < rs.half_width_m) {
      const double u = rs.distance_m / rs.half_width_m;
      h = rs.surface_m - rs.depth_m * (1.0 - u * u) - 0.15;
      water = std::max(water, rs.surface_m);
      col.river = true;
      col.river_discharge_m3s = rs.discharge_m3s;
    } else {
      const double w = smoothstep(rs.half_width_m, rs.half_width_m + bank, rs.distance_m);
      h = lerp_d(rs.surface_m + 0.4, h, w);
    }
  }
  col.surface_m = h;
  col.water_m = water;
  // Water table: a subdued replica of the topography, pinned to surface
  // water / sea level where present.
  double wt = 0.4 * h - 25.0;
  if (water > -1e29) wt = std::max(wt, water);
  col.water_table_m = std::min(wt, h - 4.0);
  col.magma_m = kBedrockTopM + 330.0 + 50.0 * noise::perlin2(s + 90, x / 800.0, z / 800.0);
  col.stack_scale = 1.0 + 0.3 * noise::perlin2(s + 91, x / 40.0, z / 40.0);
  col.sediment_m = 2.0 + 10.0 * (0.5 + 0.5 * noise::perlin2(s + 92, x / 300.0, z / 300.0));
}

ColumnInfo WorldGenerator::column(double x_m, double z_m) const {
  ColumnInfo c;
  column_into(x_m, z_m, c, kVoxelSize);
  // slope estimate by central differences at 0.5 m
  ColumnInfo a, b2, d, e;
  column_into(x_m + 0.5, z_m, a, kVoxelSize);
  column_into(x_m - 0.5, z_m, b2, kVoxelSize);
  column_into(x_m, z_m + 0.5, d, kVoxelSize);
  column_into(x_m, z_m - 0.5, e, kVoxelSize);
  const double gx = (a.surface_m - b2.surface_m), gz = (d.surface_m - e.surface_m);
  c.slope = std::sqrt(gx * gx + gz * gz);
  c.inv_grad_norm = 1.0 / std::sqrt(1.0 + c.slope * c.slope);
  c.sediment_m *= 1.0 - smoothstep(0.6, 1.4, c.slope);
  return c;
}

// ---------------------------------------------------------------------------
// Caves. All components are approximate signed distances in metres
// (field value / gradient magnitude) so they combine with min() and with the
// terrain SDF.
// ---------------------------------------------------------------------------
WorldGenerator::CaveSample WorldGenerator::cave_field(double x, double y, double z, const ColumnInfo& col) const {
  CaveSample out;
  const uint64_t s = params_.seed;
  const double depth = col.surface_m - y;
  if (params_.ores && depth > 8.0) {
    out.ore_a = noise::perlin3(s + 101, x / 14.0, y / 11.0, z / 14.0);
    out.ore_b = noise::perlin3(s + 102, x / 22.0, y / 18.0, z / 22.0);
    // Deposits: veins exist only inside discrete ore bodies (~10% of rock),
    // like real mineralised zones, instead of the space-filling zero-set
    // network that raw vein noise would give.
    out.ore_body = noise::perlin3(s + 103, x / 90.0, y / 70.0, z / 90.0);
  }
  if (!params_.caves || depth < -2.0) return out;
  const double bedrock = kBedrockTopM + 4.0 * noise::perlin2(s + 93, x / 50.0, z / 50.0);
  if (y < bedrock) return out;

  double c = kBig;
  // (a) Spaghetti tunnels: intersection of two noise zero-surfaces.
  if (depth > 3.0 && depth < 1300.0) {
    constexpr double f = 1.0 / 95.0;
    const double n1 = noise::perlin3(s + 61, x * f, y * f * 1.7, z * f);
    const double n2 = noise::perlin3(s + 62, x * f, y * f * 1.7, z * f);
    const double rvar = 0.7 + 0.6 * (0.5 + 0.5 * noise::perlin3(s + 64, x / 160.0, y / 160.0, z / 160.0));
    const double r = 0.075 * rvar * std::min(col.cave_density, 1.8);
    double ct = (std::sqrt(n1 * n1 + n2 * n2) - r) / (f * 2.2);
    // Near the surface tunnels close up except at entrances.
    const double entrance = smoothstep(0.62, 0.8, 0.5 + 0.5 * noise::perlin2(s + 63, x / 600.0, z / 600.0));
    ct += std::max(0.0, 12.0 - depth) * 0.6 * (1.0 - entrance);
    c = std::min(c, ct);
  }
  // (b) Cheese caverns: large chambers, growing into the fungal deep zone.
  if (depth > 25.0) {
    constexpr double f = 1.0 / 220.0;
    const double nv = noise::fbm3(s + 65, x * f, y * f * 1.4, z * f, 3);
    double theta = lerp_d(0.60, 0.40, smoothstep(500.0, 900.0, depth));
    theta += 0.2 * (1.0 - smoothstep(25.0, 90.0, depth));
    theta -= 0.04 * (col.cave_density - 1.0);
    c = std::min(c, (theta - nv) / (f * 1.6));
  }
  // (c) Karst shafts and dolines in carbonate terrain.
  if (col.karst > 0.05 && depth > -2.0 && depth < 170.0) {
    const auto w = noise::worley2(s + 66, x / 350.0, z / 350.0, 0.9);
    const double u = to_unit(w.cell_hash);
    if (u < 0.28 * col.karst) {
      const double u2 = to_unit(mix64(w.cell_hash));
      const double R = 3.0 + 9.0 * u2;
      const double D = 25.0 + 140.0 * to_unit(mix64(w.cell_hash ^ 7));
      if (depth < D) {
        const double funnel = std::max(0.0, 8.0 - depth) * 1.2;
        c = std::min(c, w.f1 * 350.0 - (R + funnel));
      }
    }
  }
  // (d) Lava tubes under volcanic terrain: horizontal tubes along palaeo-flow lines.
  if (col.volcanic > 0.15 && depth > 4.0 && depth < 60.0) {
    const double l = noise::perlin2(s + 67, x / 420.0, z / 420.0);
    const double hd = std::abs(l) * 420.0 / 1.6;
    const double dc = 14.0 + 10.0 * (0.5 + 0.5 * noise::perlin2(s + 68, x / 900.0, z / 900.0));
    const double vd = (depth - dc) * 1.5;
    const double R = 2.5 + 3.0 * col.volcanic;
    out.lava = std::sqrt(hd * hd + vd * vd) - R;
    c = std::min(c, out.lava);
  }
  // (e) Geodes: rare spherical voids lined with crystal.
  if (depth > 250.0 && depth < 1000.0) {
    const auto w = noise::worley3(s + 69, x / 45.0, y / 45.0, z / 45.0, 0.8);
    if (to_unit(w.cell_hash) < 0.12) {
      const double R = 3.0 + 9.0 * to_unit(mix64(w.cell_hash));
      out.geode = w.f1 * 45.0 - R;
      c = std::min(c, out.geode);
    }
  }
  // (f) Magma chambers near the base of the world.
  if (y < kBedrockTopM + 600.0) {
    const double nv = noise::fbm3(s + 70, x / 300.0, y / 200.0, z / 300.0, 2);
    c = std::min(c, (0.35 - nv) * 300.0 / 1.6);
  }
  // (g) Underground rivers: tubes running along the water table in wet terrain.
  if (col.precip_mm > 700.0 && depth > 15.0 && col.water_table_m > -1e29) {
    const double l = noise::perlin2(s + 71, x / 700.0, z / 700.0);
    const double hd = std::abs(l) * 700.0 / 1.6;
    const double vd = (y - (col.water_table_m + 1.0)) * 1.2;
    c = std::min(c, std::sqrt(hd * hd + vd * vd) - 3.5);
  }
  out.total = c;
  return out;
}

Biome WorldGenerator::underground_biome_for(double y, double depth, const ColumnInfo& col, const CaveSample& cs) const {
  if (depth > 1400.0 || y < kBedrockTopM + 600.0) return Biome::AbyssalMagmaDepths;
  if (cs.geode < 3.0) return Biome::CrystalGeodeCaverns;
  if (depth > 600.0) return Biome::FungalDeepCaverns;
  if (col.volcanic > 0.25 && depth < 70.0) return Biome::LavaTubes;
  if (y < col.water_table_m + 2.0) return Biome::UndergroundRivers;
  return Biome::KarstCaves;
}

Biome WorldGenerator::underground_biome(double x, double y, double z) const {
  const ColumnInfo col = column(x, z);
  return underground_biome_for(y, col.surface_m - y, col, cave_field(x, y, z, col));
}

Material WorldGenerator::fluid_material(double y, const ColumnInfo& col, bool above_terrain, double depth) const {
  if (above_terrain) return y < col.water_m ? Material::Water : Material::Air;
  if (y < col.magma_m) return Material::Lava;
  if (y < col.water_table_m && depth < 600.0) return Material::Water;
  return Material::Air;
}

// ---------------------------------------------------------------------------
// Geology: soil horizons -> sediment -> folded sedimentary strata (with coal
// seams, ore veins) -> crystalline basement (granite, contact marble) ->
// bedrock. Cave floors receive a biome coating; geode walls crystallise.
// ---------------------------------------------------------------------------
Material WorldGenerator::solid_material(double x, double y, double z, const ColumnInfo& col, double depth, const CaveSample& cs,
                                        bool cave_above) const {
  const uint64_t s = params_.seed;
  const double bedrock = kBedrockTopM + 4.0 * noise::perlin2(s + 93, x / 50.0, z / 50.0);
  if (y < bedrock) return Material::Bedrock;

  if (cs.geode > -0.05 && cs.geode < 0.7) return Material::AmethystCrystal;
  if (cs.geode >= 0.7 && cs.geode < 1.8) return Material::QuartzCrystal;
  if (cs.lava > -0.05 && cs.lava < 0.45) return Material::Obsidian;

  const BiomeDef& bd = biome_def(col.biome);
  if (cave_above && depth > 3.0) {
    const BiomeDef& ub = biome_def(underground_biome_for(y, depth, col, cs));
    return ub.surface[0].material;
  }

  // Soil horizons.
  const bool underwater = col.surface_m < col.water_m - 0.3;
  const bool cliff = col.slope > 1.0;
  double acc = 0.0;
  if (!cliff) {
    for (int k = 0; k < 3; ++k) {
      acc += bd.surface[k].thickness_m * col.stack_scale;
      if (depth < acc) {
        if (k == 0 && underwater) {
          if (col.river) return Material::Gravel;
          return (col.water_m - col.surface_m) > 60.0 ? Material::Mud : Material::Sand;
        }
        if (k == 0 && col.temperature_c - 0.0065 * std::max(0.0, col.surface_m - col.macro_elevation_m) < -3.0 &&
            col.slope < 0.6 && bd.layer == BiomeLayer::Surface)
          return Material::Snow;
        return bd.surface[k].material;
      }
    }
    acc += col.sediment_m;
    if (depth < acc) return bd.sediment;
  }

  // Crystalline basement with a contact-metamorphic marble aureole.
  const double basement = -650.0 + 250.0 * noise::fbm2(s + 94, x / 30000.0, z / 30000.0, 3);
  if (y < basement) {
    if (params_.ores && cs.ore_body > 0.42) {
      if (depth > 60.0 && std::abs(cs.ore_b) < 0.03) return Material::CopperOre;
      if (std::abs(cs.ore_b) >= 0.03 && std::abs(cs.ore_b) < 0.045) return Material::QuartzCrystal;
      if ((y < kBedrockTopM + 300.0 || depth > 1300.0) && std::abs(cs.ore_a) >= 0.035 && std::abs(cs.ore_a) < 0.05)
        return Material::Sulfur;
    }
    return Material::Granite;
  }
  if (y < basement + 40.0 && col.karst > 0.3) return Material::Marble;

  // Folded / tilted sedimentary strata.
  const double fold = 35.0 * noise::fbm2(s + 95, x / 2500.0, z / 2500.0, 3) + 0.012 * x + 0.007 * z;
  const double thick = std::max(0.5, static_cast<double>(bd.strata_thickness_m));
  const int64_t layer = static_cast<int64_t>(std::floor((y + fold) / thick));
  const uint64_t lh = hash2(s + 96, layer, static_cast<int64_t>(col.biome));
  Material host = to_unit(lh) < 0.68 ? bd.rock_primary : bd.rock_secondary;
  if (col.volcanic > 0.4) host = to_unit(lh) < 0.6 ? Material::Basalt : Material::Tuff;
  if (host == Material::Shale && to_unit(mix64(lh)) < 0.08) host = Material::Coal;  // coal seams

  if (params_.ores && depth > 12.0 && cs.ore_body > 0.42) {
    const double a = std::abs(cs.ore_a);
    if ((host == Material::Sandstone || host == Material::RedSandstone || host == Material::Basalt || host == Material::Shale) &&
        a < 0.035)
      return Material::IronOre;
    if ((col.volcanic > 0.3 || depth > 1300.0) && a >= 0.035 && a < 0.05) return Material::Sulfur;
    if ((host == Material::Granite || host == Material::Basalt || host == Material::Marble) && depth > 60.0 &&
        std::abs(cs.ore_b) < 0.03)
      return Material::CopperOre;
  }
  return host;
}

PointInfo WorldGenerator::point(double x, double y, double z) const {
  const ColumnInfo col = column(x, z);
  const double depth = col.surface_m - y;
  const CaveSample cs = cave_field(x, y, z, col);
  const double dt = (y - col.surface_m) * col.inv_grad_norm;
  const double sdf = std::max(dt, -cs.total);
  PointInfo pi;
  pi.depth_m = depth;
  pi.voxel.sdf = quantize_sdf(sdf, kVoxelSize);
  if (pi.voxel.sdf < 0) {
    const CaveSample above = cave_field(x, y + 2 * kVoxelSize, z, col);
    pi.voxel.material = solid_material(x, y, z, col, depth, cs, above.total < 0.0);
  } else {
    pi.voxel.material = fluid_material(y, col, dt >= 0.0, depth);
  }
  pi.underground_biome = underground_biome_for(y, depth, col, cs);
  return pi;
}

// ---------------------------------------------------------------------------
// Chunk generation
// ---------------------------------------------------------------------------
void WorldGenerator::generate(ChunkCoord cc, Chunk& out, int lod) const {
  out = Chunk(cc, lod);
  const double vs = kVoxelSize * static_cast<double>(1 << lod);
  const double ox = static_cast<double>(cc.x) * kChunkSize * vs;
  const double oy = static_cast<double>(cc.y) * kChunkSize * vs;
  const double oz = static_cast<double>(cc.z) * kChunkSize * vs;
  constexpr int G = kChunkSize + 2;  // columns with a one-voxel apron for gradients

  std::vector<ColumnInfo> cols(G * G);
  for (int j = 0; j < G; ++j)
    for (int i = 0; i < G; ++i)
      column_into(ox + (i - 0.5) * vs, oz + (j - 0.5) * vs, cols[j * G + i], vs);

  double hmin = 1e30, hmax = -1e30, wmin = 1e30, wmax = -1e30;
  for (int j = 0; j < G; ++j)
    for (int i = 0; i < G; ++i) {
      ColumnInfo& c = cols[j * G + i];
      const int il = std::clamp(i, 1, G - 2), jl = std::clamp(j, 1, G - 2);
      const double gx = (cols[jl * G + il + 1].surface_m - cols[jl * G + il - 1].surface_m) / (2.0 * vs);
      const double gz = (cols[(jl + 1) * G + il].surface_m - cols[(jl - 1) * G + il].surface_m) / (2.0 * vs);
      c.slope = std::sqrt(gx * gx + gz * gz);
      c.inv_grad_norm = 1.0 / std::sqrt(1.0 + c.slope * c.slope);
      c.sediment_m *= 1.0 - smoothstep(0.6, 1.4, c.slope);
      hmin = std::min(hmin, c.surface_m);
      hmax = std::max(hmax, c.surface_m);
      wmin = std::min(wmin, c.water_m);
      wmax = std::max(wmax, c.water_m);
    }

  const double band = (kSdfMax + 1.0) / kSdfStepsPerVoxel * vs;  // distance at which the SDF saturates
  const double y_lo = oy + 0.5 * vs, y_hi = oy + (kChunkSize - 0.5) * vs;

  // Entirely above the terrain band: air and/or surface water only.
  if (y_lo - hmax > band) {
    if (y_lo >= wmax) { out.fill({kSdfMax, Material::Air}); return; }
    if (y_hi < wmin) { out.fill({kSdfMax, Material::Water}); return; }
  }

  // Coarse cave/ore lattice: every 4 voxels (9^3 samples), trilinear in between.
  constexpr int S = 4, N = kChunkSize / S + 1;
  const bool need_sub = y_lo < hmax + band;  // any voxel can be underground
  std::vector<CaveSample> lattice;
  if (need_sub) {
    lattice.resize(N * N * N);
    for (int b = 0; b < N; ++b)
      for (int c = 0; c < N; ++c)
        for (int a = 0; a < N; ++a) {
          const ColumnInfo& col = cols[(c * S + 1) * G + (a * S + 1)];
          lattice[(b * N + c) * N + a] =
              cave_field(ox + (a * S + 0.5) * vs, oy + (b * S + 0.5) * vs, oz + (c * S + 0.5) * vs, col);
        }
  }
  auto interp = [&](int x, int y, int z, CaveSample& r) {
    const double gx = std::min(x / static_cast<double>(S), N - 1.0);
    const double gy = std::min(y / static_cast<double>(S), N - 1.0);
    const double gz = std::min(z / static_cast<double>(S), N - 1.0);
    const int a = std::min(static_cast<int>(gx), N - 2), b = std::min(static_cast<int>(gy), N - 2), c = std::min(static_cast<int>(gz), N - 2);
    const double tx = gx - a, ty = gy - b, tz = gz - c;
    auto L = [&](int aa, int bb, int ccc) -> const CaveSample& { return lattice[(bb * N + ccc) * N + aa]; };
    auto tri = [&](double CaveSample::*f) {
      const double c00 = lerp_d(L(a, b, c).*f, L(a + 1, b, c).*f, tx);
      const double c10 = lerp_d(L(a, b + 1, c).*f, L(a + 1, b + 1, c).*f, tx);
      const double c01 = lerp_d(L(a, b, c + 1).*f, L(a + 1, b, c + 1).*f, tx);
      const double c11 = lerp_d(L(a, b + 1, c + 1).*f, L(a + 1, b + 1, c + 1).*f, tx);
      return lerp_d(lerp_d(c00, c10, ty), lerp_d(c01, c11, ty), tz);
    };
    r.total = tri(&CaveSample::total);
    r.geode = tri(&CaveSample::geode);
    r.lava = tri(&CaveSample::lava);
    r.ore_a = tri(&CaveSample::ore_a);
    r.ore_b = tri(&CaveSample::ore_b);
    r.ore_body = tri(&CaveSample::ore_body);
  };

  std::vector<int8_t> sdf(kChunkVolume);
  std::vector<Material> mats(kChunkVolume);
  CaveSample cs, above;
  for (int y = 0; y < kChunkSize; ++y) {
    const double wy = oy + (y + 0.5) * vs;
    for (int z = 0; z < kChunkSize; ++z) {
      const double wz = oz + (z + 0.5) * vs;
      for (int x = 0; x < kChunkSize; ++x) {
        const double wx = ox + (x + 0.5) * vs;
        const ColumnInfo& col = cols[(z + 1) * G + (x + 1)];
        const double depth = col.surface_m - wy;
        const double dt = (wy - col.surface_m) * col.inv_grad_norm;
        double d = dt;
        if (need_sub && dt < band) {
          interp(x, y, z, cs);
          d = std::max(dt, -cs.total);
        } else {
          cs = CaveSample{};
        }
        const int idx = voxel_index(x, y, z);
        const int8_t q = quantize_sdf(d, vs);
        sdf[idx] = q;
        if (q < 0) {
          bool cave_above = false;
          if (need_sub && depth > 3.0) {
            interp(x, y + 2, z, above);
            cave_above = above.total < 0.0;
          }
          mats[idx] = solid_material(wx, wy, wz, col, depth, cs, cave_above);
        } else {
          mats[idx] = fluid_material(wy, col, dt >= 0.0, depth);
        }
      }
    }
  }
  out.assign(sdf, mats);
}

}  // namespace primeva
