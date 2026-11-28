// primeva_cli — offline tools for the Primeva world core.
//
//   bake     --out macro.pvm [--res 4096] [--seed N] [--area-km2 301340]
//   stats    --macro macro.pvm
//   map      --macro macro.pvm --out map.png [--layer relief|biome|era|precip|temp] [--px 2048]
//   find     --macro macro.pvm [--biome name] [--top 10]
//   section  --macro macro.pvm --x X --z Z --width 512 --ymin -300 --ymax 300 --out s.png [--mpp 0.5]
//   export   --macro macro.pvm --x X --z Z --size 96 --out area.glb [--lod 0] [--depth 8] [--ymin Y --ymax Y] [--dig]
//   bench    --macro macro.pvm [--chunks 2000]
//   heightmap --macro macro.pvm --x X --z Z --size 64 --res 0.25 --out terrain (writes terrain.f32 + terrain.json)

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "primeva/chunk_codec.hpp"
#include "primeva/hash.hpp"
#include "primeva/image.hpp"
#include "primeva/macro_map.hpp"
#include "primeva/mesh_export.hpp"
#include "primeva/mesher.hpp"
#include "primeva/parallel.hpp"
#include "primeva/voxel_world.hpp"
#include "primeva/world_generator.hpp"

using namespace primeva;

namespace {

struct Args {
  std::map<std::string, std::string> kv;
  std::string get(const std::string& k, const std::string& d = "") const {
    auto it = kv.find(k);
    return it == kv.end() ? d : it->second;
  }
  double num(const std::string& k, double d) const {
    auto it = kv.find(k);
    return it == kv.end() ? d : std::atof(it->second.c_str());
  }
  bool has(const std::string& k) const { return kv.count(k) != 0; }
};

Args parse(int argc, char** argv, int start) {
  Args a;
  for (int i = start; i < argc; ++i) {
    std::string k = argv[i];
    if (k.rfind("--", 0) != 0) continue;
    k = k.substr(2);
    if (i + 1 < argc && std::strncmp(argv[i + 1], "--", 2) != 0) a.kv[k] = argv[++i];
    else a.kv[k] = "1";
  }
  return a;
}

double now_s() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

void progress(const char* s) { std::fprintf(stderr, "[bake %.1fs] %s\n", now_s(), s); }

std::shared_ptr<MacroMap> load_macro(const Args& a) {
  auto m = std::make_shared<MacroMap>();
  const std::string path = a.get("macro", "macro.pvm");
  if (!MacroMap::load(path, *m)) {
    std::fprintf(stderr, "cannot load macro map '%s' (run `primeva_cli bake` first)\n", path.c_str());
    std::exit(2);
  }
  return m;
}

GeneratorParams gen_params(const MacroMap& m) {
  GeneratorParams g;
  g.seed = m.seed();
  return g;
}

// ---------------------------------------------------------------------------
int cmd_bake(const Args& a) {
  MacroBakeParams p;
  p.resolution = static_cast<int>(a.num("res", p.resolution));
  if (a.has("seed")) p.seed = std::strtoull(a.get("seed").c_str(), nullptr, 0);
  p.target_land_km2 = a.num("area-km2", p.target_land_km2);
  p.world_size_m = a.num("world-km", p.world_size_m / 1000.0) * 1000.0;
  const double t0 = now_s();
  MacroMap m = MacroMap::bake(p, progress);
  const std::string out = a.get("out", "macro.pvm");
  if (!m.save(out)) { std::fprintf(stderr, "write failed: %s\n", out.c_str()); return 1; }
  std::printf("baked %dx%d (%.0f m cells) in %.1f s -> %s\n", m.resolution(), m.resolution(), m.cell_size_m(), now_s() - t0, out.c_str());
  std::printf("land area: %.0f km2 (target %.0f)\n", m.land_area_km2(), p.target_land_km2);
  return 0;
}

int cmd_stats(const Args& a) {
  auto m = load_macro(a);
  std::printf("macro map %dx%d, cell %.1f m, world %.1f km, seed 0x%llx\n", m->resolution(), m->resolution(), m->cell_size_m(),
              m->world_size_m() / 1000.0, static_cast<unsigned long long>(m->seed()));
  std::printf("land area: %.0f km2\n", m->land_area_km2());
  double emin = 1e30, emax = -1e30, lakes = 0, river_km = 0;
  const double ca = m->cell_size_m() * m->cell_size_m() * 1e-6;
  int big_rivers = 0;
  for (int j = 0; j < m->resolution(); ++j)
    for (int i = 0; i < m->resolution(); ++i) {
      emin = std::min<double>(emin, m->elevation(i, j));
      emax = std::max<double>(emax, m->elevation(i, j));
      if (m->is_lake(i, j)) lakes += ca;
      if (!m->is_ocean(i, j) && m->discharge(i, j) > 4.0) river_km += m->cell_size_m() / 1000.0;
      if (!m->is_ocean(i, j) && m->discharge(i, j) > 500.0 && m->flow_dir(i, j) != MacroMap::kNoFlow) {
        const int ni = i + MacroMap::kDx[m->flow_dir(i, j)], nj = j + MacroMap::kDz[m->flow_dir(i, j)];
        if (m->is_ocean(ni, nj)) ++big_rivers;
      }
    }
  std::printf("elevation range: %.0f .. %.0f m\n", emin, emax);
  std::printf("lakes: %.0f km2, river network (Q>4 m3/s): ~%.0f km, river mouths with Q>500 m3/s: %d\n", lakes, river_km, big_rivers);
  std::printf("volcanoes: %zu\n", m->volcanoes().size());
  const auto ba = m->biome_area_km2();
  std::printf("\n%-34s %12s\n", "biome", "km2");
  for (int b = 0; b < kBiomeCount; ++b)
    if (ba[b] > 0) std::printf("%-34s %12.0f\n", std::string(biome_def(static_cast<Biome>(b)).name).c_str(), ba[b]);
  const auto ea = m->era_area_km2();
  std::printf("\n%-14s %12s %6s\n", "era (land)", "km2", "%");
  const double land = m->land_area_km2();
  for (int e = 0; e < kEraCount; ++e)
    std::printf("%-14s %12.0f %5.1f%%\n", std::string(era_name(static_cast<Era>(e))).c_str(), ea[e], 100.0 * ea[e] / land);
  return 0;
}

void era_color(Era e, uint8_t& r, uint8_t& g, uint8_t& b) {
  static const uint8_t c[kEraCount][3] = {{60, 110, 60}, {200, 100, 60}, {190, 150, 90}, {80, 150, 110},
                                          {90, 120, 170}, {40, 140, 60}, {200, 180, 90}, {220, 230, 240}};
  r = c[static_cast<int>(e)][0]; g = c[static_cast<int>(e)][1]; b = c[static_cast<int>(e)][2];
}

int cmd_map(const Args& a) {
  auto m = load_macro(a);
  const std::string layer = a.get("layer", "relief");
  const int px = std::min(static_cast<int>(a.num("px", 2048)), m->resolution());
  const double step = static_cast<double>(m->resolution()) / px;
  Image img(px, px);
  parallel_for(0, static_cast<size_t>(px), [&](size_t yy) {
    const int y = static_cast<int>(yy);
    for (int x = 0; x < px; ++x) {
      const int i = static_cast<int>(x * step), j = static_cast<int>(y * step);
      const double e = m->elevation(i, j);
      // hillshade from NW
      const double dzdx = (m->elevation(i + 1, j) - m->elevation(i - 1, j)) / (2 * m->cell_size_m());
      const double dzdz = (m->elevation(i, j + 1) - m->elevation(i, j - 1)) / (2 * m->cell_size_m());
      const double nx = -dzdx * 8, nz = -dzdz * 8, ny = 1.0;
      const double nl = std::sqrt(nx * nx + ny * ny + nz * nz);
      const double shade = std::clamp(0.55 + 0.45 * ((nx * -0.6 + ny * 0.6 + nz * -0.5) / nl), 0.25, 1.15);
      double r = 0, g = 0, b = 0;
      if (m->is_ocean(i, j)) {
        const double d = std::clamp(-e / 4000.0, 0.0, 1.0);
        r = 30 * (1 - d) + 8 * d; g = 110 * (1 - d) + 24 * d; b = 170 * (1 - d) + 70 * d;
        if (-e < 160) { r += 30; g += 50; b += 30; }
        img.set(x, y, static_cast<uint8_t>(r), static_cast<uint8_t>(g), static_cast<uint8_t>(b));
        continue;
      }
      if (layer == "biome") {
        const auto& bd = biome_def(m->biome(i, j));
        r = bd.r; g = bd.g; b = bd.b;
      } else if (layer == "era") {
        uint8_t rr, gg, bb; era_color(m->era(i, j), rr, gg, bb); r = rr; g = gg; b = bb;
      } else if (layer == "precip") {
        const double p = std::clamp(m->precipitation_mm(i, j) / 3000.0, 0.0, 1.0);
        r = 230 * (1 - p) + 20 * p; g = 200 * (1 - p) + 90 * p; b = 120 * (1 - p) + 200 * p;
      } else if (layer == "temp") {
        const double t = std::clamp((m->temperature_c(i, j) + 10.0) / 35.0, 0.0, 1.0);
        r = 40 + 210 * t; g = 80 + 80 * (1 - std::abs(t - 0.5) * 2); b = 230 * (1 - t) + 20;
      } else {  // relief: hypsometric tint
        const double h = std::clamp(e / 3500.0, 0.0, 1.0);
        if (h < 0.15) { r = 90 + 300 * h; g = 140 + 200 * h; b = 80; }
        else if (h < 0.5) { r = 135 + 120 * (h - 0.15); g = 170 - 100 * (h - 0.15); b = 90 - 40 * (h - 0.15); }
        else { r = 170 + 160 * (h - 0.5); g = 140 + 200 * (h - 0.5); b = 80 + 300 * (h - 0.5); }
      }
      r *= shade; g *= shade; b *= shade;
      if (m->is_lake(i, j)) { r = 50; g = 120; b = 180; }
      const double q = m->discharge(i, j);
      if (q > 25.0) {
        const double w = std::clamp(std::log10(q / 25.0) / 2.0, 0.25, 1.0);
        r = r * (1 - w) + 40 * w; g = g * (1 - w) + 110 * w; b = b * (1 - w) + 200 * w;
      }
      img.set(x, y, static_cast<uint8_t>(std::clamp(r, 0.0, 255.0)), static_cast<uint8_t>(std::clamp(g, 0.0, 255.0)),
              static_cast<uint8_t>(std::clamp(b, 0.0, 255.0)));
    }
  });
  const std::string out = a.get("out", "map.png");
  if (!img.write_png(out)) return 1;
  std::printf("wrote %s (%dx%d, %.2f km/px)\n", out.c_str(), px, px, step * m->cell_size_m() / 1000.0);
  return 0;
}

int cmd_find(const Args& a) {
  auto m = load_macro(a);
  const std::string bname = a.get("biome", "");
  const auto want = bname.empty() ? std::nullopt : biome_from_name(bname);
  if (!bname.empty() && !want) { std::fprintf(stderr, "unknown biome %s\n", bname.c_str()); return 2; }
  const int top = static_cast<int>(a.num("top", 10));
  // Score 4x4 km windows: biome diversity + a river + relief + volcanic/karst bonus.
  const int win = std::max(1, static_cast<int>(4000.0 / m->cell_size_m()));
  struct Cand { double score; int i, j; int nb; double q; };
  std::vector<Cand> cands;
  std::mutex mu;
  const int res = m->resolution();
  parallel_for(0, static_cast<size_t>((res - win) / win), [&](size_t jj) {
    const int j = static_cast<int>(jj) * win;
    for (int i = 0; i + win < res; i += win) {
      bool seen[kBiomeCount] = {};
      int nb = 0, ocean = 0;
      double qmax = 0, emin = 1e30, emax = -1e30;
      bool has_want = !want.has_value();
      for (int dj = 0; dj < win; ++dj)
        for (int di = 0; di < win; ++di) {
          if (m->is_ocean(i + di, j + dj)) { ++ocean; continue; }
          const Biome b = m->biome(i + di, j + dj);
          if (!seen[static_cast<int>(b)]) { seen[static_cast<int>(b)] = true; ++nb; }
          if (want && b == *want) has_want = true;
          qmax = std::max<double>(qmax, m->discharge(i + di, j + dj));
          emin = std::min<double>(emin, m->elevation(i + di, j + dj));
          emax = std::max<double>(emax, m->elevation(i + di, j + dj));
        }
      if (!has_want || ocean > win * win / 2) continue;
      const double score = nb * 2.0 + (qmax > 20 ? 2.0 : 0.0) + std::min(3.0, (emax - emin) / 300.0) +
                           m->volcanic(i + win / 2, j + win / 2) * 2.0;
      std::lock_guard<std::mutex> l(mu);
      cands.push_back({score, i, j, nb, qmax});
    }
  });
  std::sort(cands.begin(), cands.end(), [](const Cand& x, const Cand& y) {
    return x.score != y.score ? x.score > y.score : (x.j != y.j ? x.j < y.j : x.i < y.i);
  });
  std::printf("%-8s %-10s %-10s %-7s %-9s %s\n", "score", "x_m", "z_m", "biomes", "Qmax", "centre biome");
  for (int k = 0; k < std::min<int>(top, static_cast<int>(cands.size())); ++k) {
    const auto& c = cands[k];
    const double x = (c.i + win / 2.0) * m->cell_size_m(), z = (c.j + win / 2.0) * m->cell_size_m();
    std::printf("%-8.2f %-10.0f %-10.0f %-7d %-9.1f %s\n", c.score, x, z, c.nb, c.q,
                std::string(biome_def(m->biome(c.i + win / 2, c.j + win / 2)).name).c_str());
  }
  return 0;
}

// Chunk map for LOD > 0 exports (VoxelWorld handles LOD 0 with edits).
struct LodChunks {
  const WorldGenerator* gen;
  int lod;
  std::mutex mu;
  std::unordered_map<ChunkCoord, std::shared_ptr<Chunk>, ChunkCoordHash> map;
  std::shared_ptr<Chunk> get(ChunkCoord c) {
    {
      std::lock_guard<std::mutex> l(mu);
      auto it = map.find(c);
      if (it != map.end()) return it->second;
    }
    auto sp = std::make_shared<Chunk>();
    gen->generate(c, *sp, lod);
    std::lock_guard<std::mutex> l(mu);
    return map.emplace(c, sp).first->second;
  }
  void gather(ChunkCoord c, SampleGrid& out) {
    for (int y = -1; y <= kChunkSize; ++y)
      for (int z = -1; z <= kChunkSize; ++z)
        for (int x = -1; x <= kChunkSize; ++x) {
          const int ox = x < 0 ? -1 : (x >= kChunkSize ? 1 : 0);
          const int oy = y < 0 ? -1 : (y >= kChunkSize ? 1 : 0);
          const int oz = z < 0 ? -1 : (z >= kChunkSize ? 1 : 0);
          auto ch = get({c.x + ox, c.y + oy, c.z + oz});
          const Voxel v = ch->get(x - ox * kChunkSize, y - oy * kChunkSize, z - oz * kChunkSize);
          out.sdf[SampleGrid::index(x, y, z)] = v.sdf;
          out.mat[SampleGrid::index(x, y, z)] = v.material;
        }
  }
};

int cmd_section(const Args& a) {
  auto m = load_macro(a);
  auto gen = std::make_shared<WorldGenerator>(m, gen_params(*m));
  const double x0 = a.num("x", m->world_size_m() / 2), z = a.num("z", m->world_size_m() / 2);
  const double width = a.num("width", 512), ymin = a.num("ymin", -300), ymax = a.num("ymax", 300);
  const double mpp = a.num("mpp", 0.5);
  const int lod = std::max(0, static_cast<int>(std::floor(std::log2(std::max(mpp / kVoxelSize, 1.0)))));
  LodChunks chunks{gen.get(), lod, {}, {}};
  const double vs = kVoxelSize * (1 << lod);
  const int w = static_cast<int>(width / mpp), h = static_cast<int>((ymax - ymin) / mpp);
  Image img(w, h);
  const double t0 = now_s();
  parallel_for(0, static_cast<size_t>(w), [&](size_t xx) {
    const int px = static_cast<int>(xx);
    const double wx = x0 - width / 2 + (px + 0.5) * mpp;
    const double surface = gen->column(wx, z).surface_m;
    for (int py = 0; py < h; ++py) {
      const double wy = ymax - (py + 0.5) * mpp;
      const IVec3 v{static_cast<int32_t>(std::floor(wx / vs)), static_cast<int32_t>(std::floor(wy / vs)),
                    static_cast<int32_t>(std::floor(z / vs))};
      const ChunkCoord cc = ChunkCoord::from_voxel(v);
      const Voxel vox = chunks.get(cc)->get(v.x & kChunkMask, v.y & kChunkMask, v.z & kChunkMask);
      const auto& mi = material_info(vox.material);
      uint8_t r = mi.r, g = mi.g, b = mi.b;
      if (vox.material == Material::Air) { r = 150; g = 190; b = 230; if (wy < surface - 1) { r = 25; g = 22; b = 20; } }
      img.set(px, py, r, g, b);
    }
  }, 2);
  const std::string out = a.get("out", "section.png");
  img.write_png(out);
  std::printf("wrote %s (%dx%d, %.2f m/px, lod %d, %zu chunks, %.1f s)\n", out.c_str(), w, h, mpp, lod, chunks.map.size(), now_s() - t0);
  return 0;
}

int cmd_export(const Args& a) {
  auto m = load_macro(a);
  auto gen = std::make_shared<WorldGenerator>(m, gen_params(*m));
  const double cxm = a.num("x", m->world_size_m() / 2), czm = a.num("z", m->world_size_m() / 2);
  const double size = a.num("size", 96);
  const int lod = static_cast<int>(a.num("lod", 0));
  const double vs = kVoxelSize * (1 << lod);
  const double cw = kChunkSize * vs;
  // vertical extent from the surface envelope
  double hmin = 1e30, hmax = -1e30;
  for (double z = czm - size / 2; z <= czm + size / 2; z += std::max(2.0, size / 48))
    for (double x = cxm - size / 2; x <= cxm + size / 2; x += std::max(2.0, size / 48)) {
      const ColumnInfo c = gen->column(x, z);
      hmin = std::min(hmin, std::min(c.surface_m, c.water_m > -1e29 ? c.water_m : 1e30));
      hmax = std::max(hmax, std::max(c.surface_m, c.water_m));
    }
  const double ylo = a.has("ymin") ? a.num("ymin", 0) : hmin - a.num("depth", 8);
  const double yhi = a.has("ymax") ? a.num("ymax", 0) : hmax + 4;
  const ChunkCoord c0{static_cast<int>(std::floor((cxm - size / 2) / cw)), static_cast<int>(std::floor(ylo / cw)),
                      static_cast<int>(std::floor((czm - size / 2) / cw))};
  const ChunkCoord c1{static_cast<int>(std::floor((cxm + size / 2) / cw)), static_cast<int>(std::floor(yhi / cw)),
                      static_cast<int>(std::floor((czm + size / 2) / cw))};
  std::vector<ChunkCoord> list;
  for (int y = c0.y; y <= c1.y; ++y)
    for (int z = c0.z; z <= c1.z; ++z)
      for (int x = c0.x; x <= c1.x; ++x) list.push_back({x, y, z});
  std::printf("area %.0fx%.0f m at (%.0f, %.0f), y %.1f..%.1f, lod %d (%.3f m voxels), %zu chunks\n", size, size, cxm, czm, ylo, yhi, lod,
              vs, list.size());

  const double t0 = now_s();
  VoxelWorld world(gen);
  LodChunks lodc{gen.get(), lod, {}, {}};
  if (a.has("dig") && lod == 0) {
    // Demonstrate editing: a curved tunnel bored into the terrain plus a chamber.
    const ColumnInfo c = gen->column(cxm, czm);
    Vec3d prev{cxm - size * 0.35, c.surface_m - 1.0, czm};
    EditResult total;
    for (int k = 1; k <= 24; ++k) {
      const double t = k / 24.0;
      const Vec3d p{cxm - size * 0.35 + t * size * 0.5, c.surface_m - 1.0 - t * 7.0, czm + std::sin(t * 3.0) * 6.0};
      EditOp op;
      op.shape = EditShape::Capsule;
      op.mode = EditMode::Dig;
      op.a = prev; op.b = p; op.radius = 1.6; op.max_hardness = 9.5f;
      const EditResult r = world.apply(op);
      for (int i = 0; i < kMaterialCount; ++i) total.removed_m3[i] += r.removed_m3[i];
      total.voxels_changed += r.voxels_changed;
      total.voxels_blocked += r.voxels_blocked;
      prev = p;
    }
    EditOp room;
    room.shape = EditShape::Sphere; room.mode = EditMode::Dig; room.a = prev; room.radius = 4.5; room.max_hardness = 9.5f;
    const EditResult rr = world.apply(room);
    for (int i = 0; i < kMaterialCount; ++i) total.removed_m3[i] += rr.removed_m3[i];
    std::printf("dig: %zu voxels changed, %zu blocked (too hard). Excavated:\n", total.voxels_changed + rr.voxels_changed, total.voxels_blocked);
    for (int i = 0; i < kMaterialCount; ++i)
      if (total.removed_m3[i] > 0.01) std::printf("   %-18s %8.2f m3  (%7.0f kg)\n", std::string(material_info(static_cast<Material>(i)).name).c_str(),
                                                  total.removed_m3[i], total.removed_m3[i] * material_info(static_cast<Material>(i)).density_kg_m3);
  }

  std::vector<ChunkMesh> meshes(list.size());
  parallel_for(0, list.size(), [&](size_t k) {
    SampleGrid g;
    if (lod == 0) world.gather(list[k], g);
    else lodc.gather(list[k], g);
    mesh_chunk(g, vs, meshes[k]);
  });
  const Vec3d origin{cxm, 0.0, czm};
  MeshData terrain, fluid;
  for (size_t k = 0; k < list.size(); ++k) {
    const Vec3f off{static_cast<float>(list[k].x * cw - origin.x), static_cast<float>(list[k].y * cw - origin.y),
                    static_cast<float>(list[k].z * cw - origin.z)};
    append_mesh(terrain, meshes[k].terrain, off);
    append_mesh(fluid, meshes[k].fluid, off);
  }
  const double t1 = now_s();
  std::vector<ExportMesh> em;
  ExportMesh et; et.name = "terrain"; et.mesh = &terrain; em.push_back(et);
  ExportMesh ef; ef.name = "water"; ef.mesh = &fluid; ef.vertex_colors = false;
  ef.base_color[0] = 0.05f; ef.base_color[1] = 0.22f; ef.base_color[2] = 0.30f; ef.base_color[3] = 0.75f; ef.roughness = 0.05f;
  em.push_back(ef);
  const std::string out = a.get("out", "area.glb");
  if (!write_glb(out, em, Vec3d{0, 0, 0})) { std::fprintf(stderr, "write failed\n"); return 1; }
  std::printf("generated+meshed in %.2f s: terrain %zu tris, fluid %zu tris -> %s\n", t1 - t0, terrain.indices.size() / 3,
              fluid.indices.size() / 3, out.c_str());
  return 0;
}

int cmd_bench(const Args& a) {
  auto m = load_macro(a);
  auto gen = std::make_shared<WorldGenerator>(m, gen_params(*m));
  const int n = static_cast<int>(a.num("chunks", 2000));
  // Sample chunks around the surface at random land points, plus deep ones.
  Rng rng(1234);
  std::vector<ChunkCoord> list;
  while (static_cast<int>(list.size()) < n) {
    const double x = rng.uniform(0.2, 0.8) * m->world_size_m(), z = rng.uniform(0.2, 0.8) * m->world_size_m();
    const ColumnInfo c = gen->column(x, z);
    if (c.surface_m < 0) continue;
    const double y = (list.size() % 4 == 3) ? c.surface_m - rng.uniform(5, 900) : c.surface_m + rng.uniform(-4, 4);
    list.push_back({static_cast<int>(std::floor(x / kChunkWorldSize)), static_cast<int>(std::floor(y / kChunkWorldSize)),
                    static_cast<int>(std::floor(z / kChunkWorldSize))});
  }
  std::vector<Chunk> chunks(list.size());
  double t0 = now_s();
  for (size_t k = 0; k < list.size(); ++k) gen->generate(list[k], chunks[k]);
  const double gen_single = (now_s() - t0) / list.size();
  t0 = now_s();
  parallel_for(0, list.size(), [&](size_t k) { gen->generate(list[k], chunks[k]); });
  const double gen_mt = (now_s() - t0) / list.size();
  size_t uniform = 0, enc = 0, mem = 0;
  for (const auto& c : chunks) { uniform += c.is_uniform(); enc += encode_chunk(c).size(); mem += c.memory_bytes(); }
  VoxelWorld world(gen);
  t0 = now_s();
  size_t tris = 0;
  const size_t nm = std::min<size_t>(list.size(), 400);
  for (size_t k = 0; k < nm; ++k) {
    SampleGrid g;
    world.gather(list[k], g);
    ChunkMesh cm;
    mesh_chunk(g, kVoxelSize, cm);
    tris += cm.terrain.indices.size() / 3;
  }
  const double mesh_t = (now_s() - t0) / nm;
  std::printf("chunks: %zu (%zu uniform)\n", list.size(), uniform);
  std::printf("generate: %.3f ms/chunk single-thread, %.3f ms/chunk on %u threads (%.0f chunks/s)\n", gen_single * 1e3, gen_mt * 1e3,
              worker_count(), 1.0 / gen_mt);
  std::printf("gather+mesh (incl. neighbour generation): %.3f ms/chunk, avg %.0f tris\n", mesh_t * 1e3, static_cast<double>(tris) / nm);
  std::printf("memory: %.1f KiB/chunk avg, encoded: %.2f KiB/chunk avg\n", mem / 1024.0 / list.size(), enc / 1024.0 / list.size());
  return 0;
}

// Terrain patch for physics gyms (MuJoCo / Isaac): row-major float32 heights
// (rows along +z, columns along +x) relative to the patch minimum, plus a JSON
// sidecar with metadata. Water surface and surface material are exported too
// so gyms can randomise friction / buoyancy by material.
int cmd_heightmap(const Args& a) {
  auto m = load_macro(a);
  auto gen = std::make_shared<WorldGenerator>(m, gen_params(*m));
  const double cxm = a.num("x", m->world_size_m() / 2), czm = a.num("z", m->world_size_m() / 2);
  const double size = a.num("size", 64), res = a.num("res", 0.25);
  const int n = static_cast<int>(std::lround(size / res)) + 1;
  std::vector<double> h(static_cast<size_t>(n) * n), w(static_cast<size_t>(n) * n);
  std::vector<uint16_t> mat(static_cast<size_t>(n) * n);
  parallel_for(0, static_cast<size_t>(n), [&](size_t jj) {
    const int j = static_cast<int>(jj);
    for (int i = 0; i < n; ++i) {
      const double x = cxm - size / 2 + i * res, z = czm - size / 2 + j * res;
      const ColumnInfo c = gen->column(x, z);
      h[static_cast<size_t>(j) * n + i] = c.surface_m;
      w[static_cast<size_t>(j) * n + i] = c.water_m;
      const PointInfo pi = gen->point(x, c.surface_m - 0.06, z);
      mat[static_cast<size_t>(j) * n + i] = static_cast<uint16_t>(pi.voxel.material);
    }
  });
  double hmin = 1e30, hmax = -1e30, wmax = -1e30;
  for (size_t k = 0; k < h.size(); ++k) { hmin = std::min(hmin, h[k]); hmax = std::max(hmax, h[k]); wmax = std::max(wmax, w[k]); }
  const std::string base = a.get("out", "terrain");
  {
    std::vector<float> hf(h.size());
    for (size_t k = 0; k < h.size(); ++k) hf[k] = static_cast<float>(h[k] - hmin);
    std::FILE* f = std::fopen((base + ".f32").c_str(), "wb");
    if (!f) return 1;
    std::fwrite(hf.data(), sizeof(float), hf.size(), f);
    std::fclose(f);
    std::FILE* fm = std::fopen((base + ".mat.u16").c_str(), "wb");
    std::fwrite(mat.data(), sizeof(uint16_t), mat.size(), fm);
    std::fclose(fm);
  }
  std::map<int, int> counts;
  for (uint16_t v : mat) counts[v]++;
  std::FILE* j = std::fopen((base + ".json").c_str(), "w");
  std::fprintf(j, "{\n  \"samples\": %d,\n  \"resolution_m\": %.6f,\n  \"size_m\": %.3f,\n  \"origin_world_m\": [%.3f, %.3f, %.3f],\n",
               n, res, size, cxm - size / 2, hmin, czm - size / 2);
  std::fprintf(j, "  \"height_range_m\": %.4f,\n  \"water_level_rel_m\": %s,\n  \"layout\": \"row-major, rows +z, cols +x, float32 metres above origin y\",\n",
               hmax - hmin, wmax > -1e29 ? std::to_string(wmax - hmin).c_str() : "null");
  std::fprintf(j, "  \"materials\": {");
  bool first = true;
  for (const auto& [id, cnt] : counts) {
    const auto& mi = material_info(static_cast<Material>(id));
    std::fprintf(j, "%s\n    \"%d\": {\"name\": \"%s\", \"fraction\": %.4f, \"friction_angle_deg\": %.1f, \"hardness\": %.2f}",
                 first ? "" : ",", id, std::string(mi.name).c_str(), static_cast<double>(cnt) / mat.size(), mi.friction_angle_deg, mi.hardness);
    first = false;
  }
  std::fprintf(j, "\n  }\n}\n");
  std::fclose(j);
  std::printf("heightmap %dx%d @ %.3f m, relief %.2f m -> %s.{f32,mat.u16,json}\n", n, n, res, hmax - hmin, base.c_str());
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: primeva_cli <bake|stats|map|find|section|export|bench|heightmap> [--options]\n");
    return 2;
  }
  const std::string cmd = argv[1];
  const Args a = parse(argc, argv, 2);
  if (cmd == "bake") return cmd_bake(a);
  if (cmd == "stats") return cmd_stats(a);
  if (cmd == "map") return cmd_map(a);
  if (cmd == "find") return cmd_find(a);
  if (cmd == "section") return cmd_section(a);
  if (cmd == "export") return cmd_export(a);
  if (cmd == "bench") return cmd_bench(a);
  if (cmd == "heightmap") return cmd_heightmap(a);
  std::fprintf(stderr, "unknown command %s\n", cmd.c_str());
  return 2;
}
