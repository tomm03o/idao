#include <array>
#include <cmath>
#include <filesystem>
#include <map>
#include <memory>
#include <set>
#include <tuple>

#include "primeva/chunk_codec.hpp"
#include "primeva/dmath.hpp"
#include "primeva/hash.hpp"
#include "primeva/macro_map.hpp"
#include "primeva/mesher.hpp"
#include "primeva/noise.hpp"
#include "primeva/voxel_world.hpp"
#include "primeva/world_generator.hpp"
#include "test.hpp"

using namespace primeva;

namespace {

// A small, fast world (64 km, 256 cells of 256 m) with the same physics as
// the full bake. Shared by tests; baked once.
std::shared_ptr<const MacroMap> test_macro() {
  static std::shared_ptr<const MacroMap> m = [] {
    MacroBakeParams p;
    p.world_size_m = 65536.0;
    p.resolution = 256;
    p.target_land_km2 = 0.2874 * 65.536 * 65.536;
    p.continent_wavelength_m = 30000.0;
    p.coast_warp_m = 4000.0;
    p.mountain_wavelength_m = 12000.0;
    p.mountain_height_m = 1800.0;
    p.region_size_m = 9000.0;
    p.volcano_count = 3;
    return std::make_shared<const MacroMap>(MacroMap::bake(p));
  }();
  return m;
}

std::shared_ptr<const WorldGenerator> test_gen() {
  static std::shared_ptr<const WorldGenerator> g = [] {
    GeneratorParams gp;
    gp.seed = test_macro()->seed();
    return std::make_shared<const WorldGenerator>(test_macro(), gp);
  }();
  return g;
}

// Finds a land column well above sea level.
Vec3d find_land_point(double min_h) {
  const auto& m = *test_macro();
  for (int j = 20; j < m.resolution() - 20; ++j)
    for (int i = 20; i < m.resolution() - 20; ++i)
      if (m.elevation(i, j) > min_h && !m.is_lake(i, j) && m.discharge(i, j) < 1.0) {
        const double x = (i + 0.5) * m.cell_size_m(), z = (j + 0.5) * m.cell_size_m();
        return {x, test_gen()->column(x, z).surface_m, z};
      }
  return {0, 0, 0};
}

}  // namespace

PTEST(dmath_matches_libm) {
  double worst_sin = 0, worst_exp = 0, worst_log = 0, worst_atan = 0;
  Rng rng(7);
  for (int i = 0; i < 200000; ++i) {
    const double x = rng.uniform(-50.0, 50.0);
    worst_sin = std::max(worst_sin, std::abs(dmath::sin(x) - std::sin(x)));
    worst_sin = std::max(worst_sin, std::abs(dmath::cos(x) - std::cos(x)));
    const double e = rng.uniform(-30.0, 30.0);
    worst_exp = std::max(worst_exp, std::abs(dmath::exp(e) - std::exp(e)) / std::exp(e));
    const double l = rng.uniform(1e-6, 1e6);
    worst_log = std::max(worst_log, std::abs(dmath::log(l) - std::log(l)));
    const double ay = rng.uniform(-10, 10), ax = rng.uniform(-10, 10);
    worst_atan = std::max(worst_atan, std::abs(dmath::atan2(ay, ax) - std::atan2(ay, ax)));
  }
  CHECK(worst_sin < 1e-13);
  CHECK(worst_exp < 1e-14);
  CHECK(worst_log < 1e-13);
  CHECK(worst_atan < 1e-14);
  CHECK_NEAR(dmath::pow(2.0, 10.0), 1024.0, 1e-10);
}

PTEST(noise_range_and_determinism) {
  double mn = 1e9, mx = -1e9;
  for (int i = 0; i < 100000; ++i) {
    const double x = i * 0.0731 + 1e6, y = i * 0.0517 - 3e5, z = i * 0.0299;
    const double a = noise::perlin3(42, x, y, z), b = noise::perlin3(42, x, y, z);
    CHECK(a == b);
    mn = std::min(mn, a);
    mx = std::max(mx, a);
    const double c = noise::perlin2(42, x, y);
    CHECK(c >= -1.05 && c <= 1.05);
  }
  CHECK(mn >= -1.05 && mx <= 1.05);
  CHECK(mn < -0.5 && mx > 0.5);
  // continuity at continental coordinates: tiny step -> tiny change
  const double x = 1048000.3 / 0.25;
  CHECK(std::abs(noise::perlin2(9, x, 7.0) - noise::perlin2(9, x + 1e-6, 7.0)) < 1e-4);
  // different seeds decorrelate
  CHECK(noise::perlin2(1, 10.3, 4.7) != noise::perlin2(2, 10.3, 4.7));
}

PTEST(chunk_uniform_and_codec_roundtrip) {
  Chunk c({1, -2, 3});
  CHECK(c.is_uniform());
  c.fill({-127, Material::Granite});
  CHECK(c.is_uniform());
  c.set(5, 6, 7, {12, Material::Air});
  CHECK(!c.is_uniform());
  CHECK(c.get(5, 6, 7).material == Material::Air);
  CHECK(c.get(0, 0, 0).material == Material::Granite);
  Rng rng(3);
  for (int i = 0; i < 5000; ++i) {
    const int x = static_cast<int>(rng.below(32)), y = static_cast<int>(rng.below(32)), z = static_cast<int>(rng.below(32));
    c.set(x, y, z, {static_cast<int8_t>(-static_cast<int>(rng.below(120)) - 1), static_cast<Material>(5 + rng.below(25))});
  }
  const auto enc = encode_chunk(c);
  const auto dec = decode_chunk(enc.data(), enc.size(), c.coord());
  CHECK(dec.has_value());
  if (dec) CHECK(dec->content_hash() == c.content_hash());
  // corrupted data must be rejected, never crash
  auto bad = enc;
  bad.resize(bad.size() / 2);
  CHECK(!decode_chunk(bad.data(), bad.size(), c.coord()).has_value());
  c.fill({-127, Material::Granite});
  c.set(1, 1, 1, {-127, Material::Granite});
  CHECK(c.is_uniform());
}

PTEST(macro_bake_hits_target_area_and_drains) {
  const auto& m = *test_macro();
  const double target = 0.2874 * 65.536 * 65.536;
  CHECK(std::abs(m.land_area_km2() - target) / target < 0.03);
  // border is ocean
  CHECK(m.is_ocean(0, 0) && m.is_ocean(m.resolution() - 1, m.resolution() / 2));
  // Every land cell drains to a sink (ocean or border) and discharge never
  // decreases downstream; the filled surface never rises downstream.
  int checked = 0, bad = 0;
  for (int j = 1; j < m.resolution() - 1; j += 7)
    for (int i = 1; i < m.resolution() - 1; i += 7) {
      if (m.is_ocean(i, j)) continue;
      int ci = i, cj = j, steps = 0;
      while (m.flow_dir(ci, cj) != MacroMap::kNoFlow && steps < 100000) {
        const int ni = ci + MacroMap::kDx[m.flow_dir(ci, cj)], nj = cj + MacroMap::kDz[m.flow_dir(ci, cj)];
        if (m.discharge(ni, nj) + 1e-6 < m.discharge(ci, cj) && !m.is_ocean(ni, nj)) ++bad;
        if (m.filled_surface(ni, nj) > m.filled_surface(ci, cj) + 1e-3f) ++bad;
        ci = ni; cj = nj; ++steps;
      }
      const bool at_sink = m.is_ocean(ci, cj) || ci == 0 || cj == 0 || ci == m.resolution() - 1 || cj == m.resolution() - 1;
      if (!at_sink) ++bad;
      ++checked;
    }
  CHECK(checked > 100);
  CHECK(bad == 0);
  // all eras present
  const auto ea = m.era_area_km2();
  for (int e = 0; e < kEraCount; ++e) CHECK(ea[e] > 0);
}

PTEST(macro_save_load_roundtrip) {
  const auto& m = *test_macro();
  const auto path = (std::filesystem::temp_directory_path() / "primeva_test_macro.pvm").string();
  CHECK(m.save(path));
  MacroMap l;
  CHECK(MacroMap::load(path, l));
  CHECK(l.resolution() == m.resolution());
  CHECK(l.sample_elevation(12345.6, 23456.7) == m.sample_elevation(12345.6, 23456.7));
  CHECK(l.biome(100, 100) == m.biome(100, 100));
  std::filesystem::remove(path);
}

PTEST(generator_deterministic_and_invariants) {
  const auto gen = test_gen();
  const Vec3d p = find_land_point(150.0);
  const ChunkCoord cc = ChunkCoord::from_voxel(voxel_at_m(p));
  Chunk a, b;
  gen->generate(cc, a);
  GeneratorParams gp;
  gp.seed = test_macro()->seed();
  WorldGenerator other(test_macro(), gp);
  other.generate(cc, b);
  CHECK(a.content_hash() == b.content_hash());
  CHECK(a.contains_surface());
  int bad = 0;
  for (int dy = -3; dy <= 1; ++dy) {
    Chunk c;
    gen->generate({cc.x, cc.y + dy * 7, cc.z}, c);
    for (int y = 0; y < kChunkSize; ++y)
      for (int z = 0; z < kChunkSize; ++z)
        for (int x = 0; x < kChunkSize; ++x) {
          const Voxel v = c.get(x, y, z);
          if (v.solid() != is_solid(v.material)) ++bad;
        }
  }
  CHECK(bad == 0);
}

PTEST(mesh_seams_match_between_chunks) {
  const auto gen = test_gen();
  VoxelWorld world(gen);
  const Vec3d p = find_land_point(200.0);
  const ChunkCoord a = ChunkCoord::from_voxel(voxel_at_m(p));
  const ChunkCoord b{a.x + 1, a.y, a.z};
  SampleGrid ga, gb;
  world.gather(a, ga);
  world.gather(b, gb);
  ChunkMesh ma, mb;
  mesh_chunk(ga, kVoxelSize, ma);
  mesh_chunk(gb, kVoxelSize, mb);
  // A's cell 31 == B's cell -1: both meshes must produce identical vertices there.
  const double cw = kChunkWorldSize;
  auto key = [](double x, double y, double z) {
    return std::make_tuple(std::llround(x * 1e4), std::llround(y * 1e4), std::llround(z * 1e4));
  };
  std::set<std::tuple<long long, long long, long long>> sa, sb;
  for (const auto& v : ma.terrain.positions)
    if (v.x > 31.5 * kVoxelSize && v.x < 32.5 * kVoxelSize) sa.insert(key(v.x, v.y, v.z));
  for (const auto& v : mb.terrain.positions)
    if (v.x > -0.5 * kVoxelSize && v.x < 0.5 * kVoxelSize) sb.insert(key(v.x + cw, v.y, v.z));
  CHECK(!sa.empty());
  CHECK(sa == sb);
}

PTEST(mesh_closed_surface_is_watertight) {
  SampleGrid g;
  const double vs = kVoxelSize;
  for (int y = -1; y <= kChunkSize; ++y)
    for (int z = -1; z <= kChunkSize; ++z)
      for (int x = -1; x <= kChunkSize; ++x) {
        const double d = std::sqrt(std::pow((x - 15.3) * vs, 2) + std::pow((y - 16.1) * vs, 2) + std::pow((z - 15.7) * vs, 2)) - 1.3;
        const int i = SampleGrid::index(x, y, z);
        g.sdf[i] = quantize_sdf(d, vs);
        g.mat[i] = g.sdf[i] < 0 ? Material::Basalt : Material::Air;
      }
  ChunkMesh m;
  mesh_chunk(g, vs, m);
  std::map<std::pair<uint32_t, uint32_t>, int> edges;
  const auto& idx = m.terrain.indices;
  for (size_t t = 0; t < idx.size(); t += 3)
    for (int e = 0; e < 3; ++e) {
      uint32_t a = idx[t + e], b = idx[t + (e + 1) % 3];
      ++edges[{std::min(a, b), std::max(a, b)}];
    }
  int nonmanifold = 0;
  for (const auto& [e, n] : edges) nonmanifold += (n != 2);
  CHECK(nonmanifold == 0);
  const long long V = static_cast<long long>(m.terrain.positions.size()), E = static_cast<long long>(edges.size()),
                  F = static_cast<long long>(idx.size() / 3);
  CHECK(V - E + F == 2);  // sphere topology
  // outward normals: vertex normal points away from the centre
  int inward = 0;
  for (size_t k = 0; k < m.terrain.positions.size(); ++k) {
    const Vec3f c{static_cast<float>(15.8 * vs), static_cast<float>(16.6 * vs), static_cast<float>(16.2 * vs)};
    if (dot(m.terrain.positions[k] - c, m.terrain.normals[k]) < 0) ++inward;
  }
  CHECK(inward == 0);
  // triangle winding agrees with normals (CCW front faces)
  int flipped = 0;
  for (size_t t = 0; t < idx.size(); t += 3) {
    const Vec3f& a = m.terrain.positions[idx[t]];
    const Vec3f fn = cross(m.terrain.positions[idx[t + 1]] - a, m.terrain.positions[idx[t + 2]] - a);
    if (dot(fn, m.terrain.normals[idx[t]]) < 0) ++flipped;
  }
  CHECK(flipped == 0);
}

PTEST(edit_dig_conserves_volume_and_respects_hardness) {
  const auto gen = test_gen();
  VoxelWorld world(gen);
  const Vec3d p = find_land_point(150.0);
  const Vec3d c{p.x, p.y - 40.0, p.z};  // inside bedrock strata
  // Exact solid volume (per material) in the edit's region, by voxel scan.
  auto solid_volume = [&](std::array<double, kMaterialCount>& per) {
    per.fill(0.0);
    const IVec3 lo = voxel_at_m({c.x - 3.5, c.y - 3.5, c.z - 3.5}), hi = voxel_at_m({c.x + 3.5, c.y + 3.5, c.z + 3.5});
    for (int y = lo.y; y <= hi.y; ++y)
      for (int z = lo.z; z <= hi.z; ++z)
        for (int x = lo.x; x <= hi.x; ++x) {
          const Voxel v = world.voxel({x, y, z});
          per[static_cast<size_t>(v.material)] += occupancy(v.sdf) * kVoxelSize * kVoxelSize * kVoxelSize;
        }
  };
  std::array<double, kMaterialCount> before{}, after_dig{}, after_fill{};
  solid_volume(before);
  EditOp op;
  op.mode = EditMode::Dig;
  op.a = c;
  op.radius = 2.0;
  op.max_hardness = 10.f;
  const EditResult r = world.apply(op);
  solid_volume(after_dig);
  double removed = 0;
  for (int m = 0; m < kMaterialCount; ++m) {
    // Reported yield per material equals the solid actually lost.
    CHECK_NEAR(r.removed_m3[m], before[m] - after_dig[m], 1e-9);
    removed += r.removed_m3[m];
  }
  const double sphere = 4.0 / 3.0 * 3.14159265358979 * 8.0;
  CHECK(removed > 0.0);
  CHECK(removed <= sphere * 1.05);  // natural cavities may already occupy part of it
  CHECK(!r.dirty_chunks.empty());
  const Voxel centre = world.voxel(voxel_at_m(c));
  CHECK(!centre.solid());
  // Refill with granite: reported placement equals solid actually gained, and
  // the fill restores the whole sphere volume (within quantisation).
  EditOp fill = op;
  fill.mode = EditMode::Fill;
  fill.material = Material::Granite;
  const EditResult f = world.apply(fill);
  solid_volume(after_fill);
  double total_after_dig = 0, total_after_fill = 0;
  for (int m = 0; m < kMaterialCount; ++m) { total_after_dig += after_dig[m]; total_after_fill += after_fill[m]; }
  CHECK_NEAR(f.placed_m3[static_cast<size_t>(Material::Granite)], total_after_fill - total_after_dig, 1e-9);
  CHECK_NEAR(f.placed_m3[static_cast<size_t>(Material::Granite)], sphere, sphere * 0.06);
  CHECK(world.voxel(voxel_at_m(c)).material == Material::Granite);
  // A weak tool cannot dig granite.
  EditOp weak = op;
  weak.max_hardness = 2.0f;
  const EditResult w = world.apply(weak);
  CHECK(w.removed_m3[static_cast<size_t>(Material::Granite)] == 0.0);
  CHECK(w.voxels_blocked > 0);
}

PTEST(edits_persist_across_save_and_reload) {
  const auto gen = test_gen();
  const auto dir = (std::filesystem::temp_directory_path() / "primeva_test_save").string();
  std::filesystem::remove_all(dir);
  const Vec3d p = find_land_point(150.0);
  std::map<std::tuple<int, int, int>, Voxel> expect;
  {
    VoxelWorld world(gen, dir);
    EditOp op;
    op.shape = EditShape::Capsule;
    op.a = {p.x - 5, p.y - 2, p.z};
    op.b = {p.x + 5, p.y - 3, p.z + 2};
    op.radius = 1.5;
    world.apply(op);
    for (int k = -40; k <= 40; k += 3) {
      const IVec3 v = voxel_at_m({p.x + k * 0.125, p.y - 2.5, p.z + 1});
      expect[{v.x, v.y, v.z}] = world.voxel(v);
    }
    CHECK(world.save());
  }
  VoxelWorld reloaded(gen, dir);
  int mismatch = 0;
  for (const auto& [k, v] : expect)
    if (!(reloaded.voxel({std::get<0>(k), std::get<1>(k), std::get<2>(k)}) == v)) ++mismatch;
  CHECK(mismatch == 0);
  CHECK(reloaded.modified_chunks() > 0);
  std::filesystem::remove_all(dir);
}

PTEST(underground_layers_exist) {
  const auto gen = test_gen();
  const Vec3d p = find_land_point(100.0);
  std::map<Material, int> seen;
  for (double y = p.y - 1; y > kBedrockTopM - 20; y -= 3.7) seen[gen->point(p.x, y, p.z).voxel.material]++;
  CHECK(seen.count(Material::Bedrock) > 0);
  CHECK(seen.count(Material::Granite) > 0);
  CHECK(seen.size() >= 4);
  CHECK(gen->underground_biome(p.x, kBedrockTopM + 200, p.z) == Biome::AbyssalMagmaDepths);
}

PTEST(terrain_heightfield_is_continuous) {
  // Regression: blending noise wavelengths across biome borders made the
  // phase x/lambda(x) sweep at continental x and produced 10+ m jumps between
  // adjacent voxels. Detail must be continuous everywhere (incl. shorelines).
  const auto gen = test_gen();
  const auto& m = *test_macro();
  int checked_lines = 0;
  double worst = 0.0, worst_x = 0, worst_z = 0;
  for (int j = 30; j < m.resolution() - 30; j += 9)
    for (int i = 30; i < m.resolution() - 30; i += 9) {
      if (m.biome(i, j) == m.biome(i + 1, j)) continue;  // want biome / shore transitions
      const double x0 = (i + 0.5) * m.cell_size_m(), z = (j + 0.5) * m.cell_size_m();
      double prev = gen->column(x0, z).surface_m;
      for (int k = 1; k < 2048; ++k) {  // 256 m across the border
        const ColumnInfo c = gen->column(x0 + k * kVoxelSize, z);
        if (!c.river && std::abs(c.surface_m - prev) > worst) {
          worst = std::abs(c.surface_m - prev);
          worst_x = x0 + k * kVoxelSize;
          worst_z = z;
        }
        prev = c.surface_m;
      }
      ++checked_lines;
    }
  std::printf("    lines=%d worst jump %.3f m at (%.2f, %.2f)\n", checked_lines, worst, worst_x, worst_z);
  CHECK(checked_lines >= 5);
  CHECK(worst < 1.0);  // < 8:1 slope between adjacent voxels (river banks excluded)
}

PTEST(ores_are_localised) {
  const auto gen = test_gen();
  const Vec3d p = find_land_point(150.0);
  int ore = 0, rock = 0;
  for (double y = p.y - 15; y > p.y - 400; y -= 1.3)
    for (double dx = -60; dx <= 60; dx += 3.1) {
      const Material mt = gen->point(p.x + dx, y, p.z).voxel.material;
      if (!is_solid(mt)) continue;
      ++rock;
      ore += (mt == Material::IronOre || mt == Material::CopperOre || mt == Material::Sulfur) ? 1 : 0;
    }
  CHECK(rock > 1000);
  CHECK(ore > 0);
  CHECK(static_cast<double>(ore) / rock < 0.02);  // a few percent at most
}
