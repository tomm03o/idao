#pragma once

#include <array>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "primeva/chunk.hpp"
#include "primeva/world_generator.hpp"

namespace primeva {

enum class EditShape : uint8_t { Sphere, Box, Capsule };
enum class EditMode : uint8_t {
  Dig,    // subtract the shape (CSG difference); yields removed material
  Fill,   // add the shape with `material` (CSG union); consumes material
  Paint,  // change the material of solid voxels inside the shape
};

struct EditOp {
  EditShape shape = EditShape::Sphere;
  EditMode mode = EditMode::Dig;
  Vec3d a{};             // sphere centre / box min / capsule start (metres)
  Vec3d b{};             // box max / capsule end
  double radius = 1.0;   // sphere / capsule radius
  Material material = Material::Air;
  float max_hardness = 10.f;  // tool / creature digging power (material hardness scale)
};

struct EditResult {
  std::array<double, kMaterialCount> removed_m3{};  // per material
  std::array<double, kMaterialCount> placed_m3{};
  size_t voxels_changed = 0;
  size_t voxels_blocked = 0;  // too hard for the tool
  std::vector<ChunkCoord> dirty_chunks;  // need remeshing (includes apron neighbours)
};

// 34^3 neighbourhood sample (chunk voxels plus a 1-voxel apron at -1 and +32)
// used by the mesher so chunk meshes are seamless.
struct SampleGrid {
  static constexpr int kSize = kChunkSize + 2;
  std::vector<int8_t> sdf = std::vector<int8_t>(kSize * kSize * kSize);
  std::vector<Material> mat = std::vector<Material>(kSize * kSize * kSize);
  static constexpr int index(int x, int y, int z) { return ((y + 1) * kSize + (z + 1)) * kSize + (x + 1); }  // x,y,z in [-1, 32]
};

// The authoritative voxel world: a cache of generated chunks + persistent
// player edits. Unedited chunks are always regenerated from the seed; only
// modified chunks are stored (region files of 16^3 chunks).
class VoxelWorld {
 public:
  explicit VoxelWorld(std::shared_ptr<const WorldGenerator> gen, std::string save_dir = "");

  std::shared_ptr<const Chunk> chunk(ChunkCoord c);
  Voxel voxel(const IVec3& v);
  void gather(ChunkCoord c, SampleGrid& out);

  EditResult apply(const EditOp& op);

  // Writes all modified chunks to region files. Returns false on IO error.
  bool save();
  // Drops cached chunks that are unmodified (or already saved) and not in `keep`.
  size_t evict_except(const std::unordered_set<ChunkCoord, ChunkCoordHash>& keep);

  size_t cached_chunks() const;
  size_t modified_chunks() const;
  const WorldGenerator& generator() const { return *gen_; }

  static constexpr int kRegionShift = 4;  // 16 chunks per region edge

 private:
  std::shared_ptr<Chunk> load_or_generate(ChunkCoord c);
  std::shared_ptr<Chunk> mutable_chunk(ChunkCoord c);
  bool load_region_index(const ChunkCoord& region);
  std::string region_path(const ChunkCoord& region) const;

  std::shared_ptr<const WorldGenerator> gen_;
  std::string save_dir_;
  mutable std::mutex mu_;
  std::unordered_map<ChunkCoord, std::shared_ptr<Chunk>, ChunkCoordHash> cache_;
  std::unordered_set<ChunkCoord, ChunkCoordHash> dirty_save_;
  // region -> (local index -> encoded blob), loaded lazily from disk
  std::unordered_map<ChunkCoord, std::unordered_map<uint16_t, std::vector<uint8_t>>, ChunkCoordHash> regions_;
};

}  // namespace primeva
