#include "primeva/voxel_world.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <map>

#include "primeva/chunk_codec.hpp"

namespace primeva {

namespace {
constexpr uint32_t kRegionMagic = 0x47525650;  // "PVRG"
constexpr uint32_t kRegionVersion = 1;

ChunkCoord region_of(const ChunkCoord& c) {
  return {c.x >> VoxelWorld::kRegionShift, c.y >> VoxelWorld::kRegionShift, c.z >> VoxelWorld::kRegionShift};
}
uint16_t local_index(const ChunkCoord& c) {
  constexpr int m = (1 << VoxelWorld::kRegionShift) - 1;
  return static_cast<uint16_t>((((c.y & m) << VoxelWorld::kRegionShift) + (c.z & m)) << VoxelWorld::kRegionShift | (c.x & m));
}

// Signed distance (metres) from point p to the edit shape; negative inside.
double shape_distance(const EditOp& op, const Vec3d& p) {
  switch (op.shape) {
    case EditShape::Sphere: return length(p - op.a) - op.radius;
    case EditShape::Box: {
      const Vec3d c = (op.a + op.b) * 0.5, h = (op.b - op.a) * 0.5;
      const Vec3d q{std::abs(p.x - c.x) - h.x, std::abs(p.y - c.y) - h.y, std::abs(p.z - c.z) - h.z};
      const Vec3d mq{std::max(q.x, 0.0), std::max(q.y, 0.0), std::max(q.z, 0.0)};
      return length(mq) + std::min(std::max(q.x, std::max(q.y, q.z)), 0.0);
    }
    case EditShape::Capsule: {
      const Vec3d pa = p - op.a, ba = op.b - op.a;
      const double bb = dot(ba, ba);
      const double t = bb > 0 ? clamp(dot(pa, ba) / bb, 0.0, 1.0) : 0.0;
      return length(pa - ba * t) - op.radius;
    }
  }
  return 1e9;
}

void shape_bounds(const EditOp& op, Vec3d& lo, Vec3d& hi) {
  switch (op.shape) {
    case EditShape::Sphere:
      lo = op.a - Vec3d{op.radius, op.radius, op.radius};
      hi = op.a + Vec3d{op.radius, op.radius, op.radius};
      break;
    case EditShape::Box:
      lo = {std::min(op.a.x, op.b.x), std::min(op.a.y, op.b.y), std::min(op.a.z, op.b.z)};
      hi = {std::max(op.a.x, op.b.x), std::max(op.a.y, op.b.y), std::max(op.a.z, op.b.z)};
      break;
    case EditShape::Capsule:
      lo = {std::min(op.a.x, op.b.x) - op.radius, std::min(op.a.y, op.b.y) - op.radius, std::min(op.a.z, op.b.z) - op.radius};
      hi = {std::max(op.a.x, op.b.x) + op.radius, std::max(op.a.y, op.b.y) + op.radius, std::max(op.a.z, op.b.z) + op.radius};
      break;
  }
}
}  // namespace

VoxelWorld::VoxelWorld(std::shared_ptr<const WorldGenerator> gen, std::string save_dir)
    : gen_(std::move(gen)), save_dir_(std::move(save_dir)) {
  if (!save_dir_.empty()) std::filesystem::create_directories(save_dir_);
}

std::string VoxelWorld::region_path(const ChunkCoord& r) const {
  char buf[96];
  std::snprintf(buf, sizeof(buf), "r.%d.%d.%d.pvr", r.x, r.y, r.z);
  return (std::filesystem::path(save_dir_) / buf).string();
}

// Must be called with mu_ held.
bool VoxelWorld::load_region_index(const ChunkCoord& region) {
  if (regions_.count(region)) return true;
  auto& entries = regions_[region];
  if (save_dir_.empty()) return true;
  std::ifstream f(region_path(region), std::ios::binary);
  if (!f) return true;  // no edits stored in this region
  uint32_t magic = 0, version = 0, count = 0;
  f.read(reinterpret_cast<char*>(&magic), 4);
  f.read(reinterpret_cast<char*>(&version), 4);
  f.read(reinterpret_cast<char*>(&count), 4);
  if (!f || magic != kRegionMagic || version != kRegionVersion) return false;
  for (uint32_t k = 0; k < count; ++k) {
    uint16_t li = 0;
    uint32_t size = 0;
    f.read(reinterpret_cast<char*>(&li), 2);
    f.read(reinterpret_cast<char*>(&size), 4);
    if (!f || size > (1u << 20)) return false;
    std::vector<uint8_t> blob(size);
    f.read(reinterpret_cast<char*>(blob.data()), size);
    if (!f) return false;
    entries[li] = std::move(blob);
  }
  return true;
}

std::shared_ptr<Chunk> VoxelWorld::load_or_generate(ChunkCoord c) {
  {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = cache_.find(c);
    if (it != cache_.end()) return it->second;
    const ChunkCoord r = region_of(c);
    load_region_index(r);
    auto& entries = regions_[r];
    auto e = entries.find(local_index(c));
    if (e != entries.end()) {
      auto decoded = decode_chunk(e->second.data(), e->second.size(), c);
      if (decoded) {
        auto sp = std::make_shared<Chunk>(std::move(*decoded));
        sp->set_modified(true);
        cache_[c] = sp;
        return sp;
      }
    }
  }
  // Generate outside the lock (pure function), then publish.
  auto sp = std::make_shared<Chunk>();
  gen_->generate(c, *sp, 0);
  std::lock_guard<std::mutex> lock(mu_);
  auto [it, inserted] = cache_.emplace(c, sp);
  return it->second;
}

std::shared_ptr<const Chunk> VoxelWorld::chunk(ChunkCoord c) { return load_or_generate(c); }
std::shared_ptr<Chunk> VoxelWorld::mutable_chunk(ChunkCoord c) { return load_or_generate(c); }

Voxel VoxelWorld::voxel(const IVec3& v) {
  const auto ch = chunk(ChunkCoord::from_voxel(v));
  const IVec3 l = voxel_local(v);
  return ch->get(l.x, l.y, l.z);
}

void VoxelWorld::gather(ChunkCoord c, SampleGrid& out) {
  // Up to 27 source chunks; fetch each once.
  std::shared_ptr<const Chunk> nb[3][3][3];
  for (int dy = -1; dy <= 1; ++dy)
    for (int dz = -1; dz <= 1; ++dz)
      for (int dx = -1; dx <= 1; ++dx) nb[dy + 1][dz + 1][dx + 1] = chunk({c.x + dx, c.y + dy, c.z + dz});
  auto sel = [](int v, int& local) {
    if (v < 0) { local = v + kChunkSize; return 0; }
    if (v >= kChunkSize) { local = v - kChunkSize; return 2; }
    local = v;
    return 1;
  };
  for (int y = -1; y <= kChunkSize; ++y) {
    int ly; const int cy = sel(y, ly);
    for (int z = -1; z <= kChunkSize; ++z) {
      int lz; const int cz = sel(z, lz);
      for (int x = -1; x <= kChunkSize; ++x) {
        int lx; const int cx = sel(x, lx);
        const Voxel v = nb[cy][cz][cx]->get(lx, ly, lz);
        const int i = SampleGrid::index(x, y, z);
        out.sdf[i] = v.sdf;
        out.mat[i] = v.material;
      }
    }
  }
}

EditResult VoxelWorld::apply(const EditOp& op) {
  EditResult res;
  Vec3d lo, hi;
  shape_bounds(op, lo, hi);
  const double vs = kVoxelSize;
  // Extend by the SDF band so the distance field stays consistent around the edit.
  const double band = (kSdfMax + 1.0) / kSdfStepsPerVoxel * vs;
  const IVec3 vlo = voxel_at_m(lo - Vec3d{band, band, band});
  const IVec3 vhi = voxel_at_m(hi + Vec3d{band, band, band});
  const double voxel_volume = vs * vs * vs;

  IVec3 changed_lo{INT32_MAX, INT32_MAX, INT32_MAX}, changed_hi{INT32_MIN, INT32_MIN, INT32_MIN};
  const ChunkCoord clo = ChunkCoord::from_voxel(vlo), chi = ChunkCoord::from_voxel(vhi);
  for (int cy = clo.y; cy <= chi.y; ++cy)
    for (int cz = clo.z; cz <= chi.z; ++cz)
      for (int cx = clo.x; cx <= chi.x; ++cx) {
        const ChunkCoord cc{cx, cy, cz};
        auto ch = mutable_chunk(cc);
        const IVec3 o = cc.origin_voxel();
        bool chunk_changed = false;
        std::lock_guard<std::mutex> lock(mu_);  // serialise writers on the shared chunk
        for (int y = std::max(vlo.y, o.y); y <= std::min(vhi.y, o.y + kChunkMask); ++y)
          for (int z = std::max(vlo.z, o.z); z <= std::min(vhi.z, o.z + kChunkMask); ++z)
            for (int x = std::max(vlo.x, o.x); x <= std::min(vhi.x, o.x + kChunkMask); ++x) {
              const int lx = x - o.x, ly = y - o.y, lz = z - o.z;
              const Voxel old = ch->get(lx, ly, lz);
              const double ds = shape_distance(op, voxel_center_m({x, y, z}));
              const double old_m = sdf_to_metres(old.sdf, vs);
              Voxel nv = old;
              switch (op.mode) {
                case EditMode::Dig: {
                  if (old.solid() && material_info(old.material).hardness > op.max_hardness) {
                    if (ds < 0) ++res.voxels_blocked;
                    continue;
                  }
                  if (!material_info(old.material).diggable && old.solid()) continue;
                  nv.sdf = quantize_sdf(std::max(old_m, -ds), vs);
                  if (!nv.solid() && old.solid()) nv.material = Material::Air;
                  if (old.solid()) {
                    const double removed = (occupancy(old.sdf) - occupancy(nv.sdf)) * voxel_volume;
                    res.removed_m3[static_cast<size_t>(old.material)] += removed;
                  }
                  break;
                }
                case EditMode::Fill: {
                  if (!is_solid(op.material)) continue;
                  // Existing solid of another material is left untouched so all
                  // placed volume is genuinely `op.material`; the shared face is
                  // interior (solid on both sides) and produces no geometry.
                  if (old.solid() && old.material != op.material) continue;
                  nv.sdf = quantize_sdf(std::min(old_m, ds), vs);
                  if (nv.solid() && !old.solid()) nv.material = op.material;
                  res.placed_m3[static_cast<size_t>(op.material)] += (occupancy(nv.sdf) - occupancy(old.sdf)) * voxel_volume;
                  break;
                }
                case EditMode::Paint:
                  if (ds < 0 && old.solid() && is_solid(op.material)) nv.material = op.material;
                  break;
              }
              if (nv == old) continue;
              ch->set(lx, ly, lz, nv);
              chunk_changed = true;
              ++res.voxels_changed;
              changed_lo = {std::min(changed_lo.x, x), std::min(changed_lo.y, y), std::min(changed_lo.z, z)};
              changed_hi = {std::max(changed_hi.x, x), std::max(changed_hi.y, y), std::max(changed_hi.z, z)};
            }
        if (chunk_changed) {
          ch->try_make_uniform();
          ch->set_modified(true);
          ch->bump_revision();
          dirty_save_.insert(cc);
        }
      }

  if (res.voxels_changed > 0) {
    // A voxel v appears in the sample grid of chunk c iff c*32-1 <= v <= c*32+32.
    auto lo_c = [](int v) { return floor_div(v - kChunkSize + kChunkSize - 1, kChunkSize); };  // ceil((v-32)/32)
    auto hi_c = [](int v) { return floor_div(v + 1, kChunkSize); };
    for (int cy = lo_c(changed_lo.y); cy <= hi_c(changed_hi.y); ++cy)
      for (int cz = lo_c(changed_lo.z); cz <= hi_c(changed_hi.z); ++cz)
        for (int cx = lo_c(changed_lo.x); cx <= hi_c(changed_hi.x); ++cx) res.dirty_chunks.push_back({cx, cy, cz});
  }
  return res;
}

bool VoxelWorld::save() {
  if (save_dir_.empty()) return false;
  std::lock_guard<std::mutex> lock(mu_);
  std::map<std::tuple<int, int, int>, ChunkCoord> touched_regions;
  for (const ChunkCoord& c : dirty_save_) {
    const ChunkCoord r = region_of(c);
    if (!load_region_index(r)) return false;
    auto it = cache_.find(c);
    if (it == cache_.end()) continue;
    regions_[r][local_index(c)] = encode_chunk(*it->second);
    touched_regions[{r.x, r.y, r.z}] = r;
  }
  for (const auto& [key, r] : touched_regions) {
    const auto& entries = regions_[r];
    std::map<uint16_t, const std::vector<uint8_t>*> ordered;  // deterministic file layout
    for (const auto& [li, blob] : entries) ordered[li] = &blob;
    const std::string path = region_path(r);
    const std::string tmp = path + ".tmp";
    {
      std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
      if (!f) return false;
      const uint32_t count = static_cast<uint32_t>(ordered.size());
      f.write(reinterpret_cast<const char*>(&kRegionMagic), 4);
      f.write(reinterpret_cast<const char*>(&kRegionVersion), 4);
      f.write(reinterpret_cast<const char*>(&count), 4);
      for (const auto& [li, blob] : ordered) {
        const uint32_t size = static_cast<uint32_t>(blob->size());
        f.write(reinterpret_cast<const char*>(&li), 2);
        f.write(reinterpret_cast<const char*>(&size), 4);
        f.write(reinterpret_cast<const char*>(blob->data()), size);
      }
      if (!f) return false;
    }
    std::error_code ec;
    std::filesystem::rename(tmp, path, ec);  // atomic replace: no torn region files on crash
    if (ec) return false;
  }
  dirty_save_.clear();
  return true;
}

size_t VoxelWorld::evict_except(const std::unordered_set<ChunkCoord, ChunkCoordHash>& keep) {
  std::lock_guard<std::mutex> lock(mu_);
  size_t n = 0;
  for (auto it = cache_.begin(); it != cache_.end();) {
    if (!keep.count(it->first) && !dirty_save_.count(it->first)) {
      it = cache_.erase(it);
      ++n;
    } else {
      ++it;
    }
  }
  return n;
}

size_t VoxelWorld::cached_chunks() const {
  std::lock_guard<std::mutex> lock(mu_);
  return cache_.size();
}
size_t VoxelWorld::modified_chunks() const {
  std::lock_guard<std::mutex> lock(mu_);
  size_t n = 0;
  for (const auto& [c, ch] : cache_) n += ch->modified() ? 1 : 0;
  return n;
}

}  // namespace primeva
