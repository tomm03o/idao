#pragma once

#include <array>
#include <cstdint>
#include <vector>

#include "primeva/config.hpp"
#include "primeva/material.hpp"
#include "primeva/math.hpp"

namespace primeva {

static_assert(kMaterialCount <= 256, "per-chunk palette uses 8-bit indices");

// A voxel: quantised signed distance (negative = inside solid) and material.
// Invariant maintained by every writer:
//   sdf <  0  -> material is solid (rock, soil, ...)
//   sdf >= 0  -> material is Air or a fluid (Water, Lava) filling the space
struct Voxel {
  int8_t sdf = kSdfMax;
  Material material = Material::Air;
  constexpr bool solid() const { return sdf < 0; }
  constexpr bool operator==(const Voxel& o) const = default;
};

inline int8_t quantize_sdf(double distance_m, double voxel_size_m) {
  const double q = distance_m / voxel_size_m * kSdfStepsPerVoxel;
  const double r = q >= 0 ? std::floor(q + 0.5) : -std::floor(-q + 0.5);
  return static_cast<int8_t>(clamp(r, static_cast<double>(kSdfMin), static_cast<double>(kSdfMax)));
}
inline double sdf_to_metres(int8_t q, double voxel_size_m) { return q * voxel_size_m / kSdfStepsPerVoxel; }

// Volume fraction of a voxel occupied by solid, from its signed distance
// (linear ramp over one voxel width centred on the surface).
inline double solid_fraction(int8_t q) {
  const double d = static_cast<double>(q) / kSdfStepsPerVoxel;  // in voxels
  return clamp(0.5 - d, 0.0, 1.0);
}

// Material volume (in voxel units) owned by a voxel. This is THE conserved
// quantity for resource accounting: only solid voxels own material, so every
// dig yield and every fill cost is attributable to exactly one material and a
// dig/fill cycle can never create or destroy resources.
inline double occupancy(int8_t q) { return q < 0 ? solid_fraction(q) : 0.0; }

// 32^3 voxel chunk. Uniform chunks (all air, all one rock) store a single
// voxel and allocate nothing; mixed chunks store 32 KiB of SDF plus 32 KiB of
// palette indices.
class Chunk {
 public:
  Chunk() = default;
  explicit Chunk(ChunkCoord c, int lod = 0) : coord_(c), lod_(lod) {}

  ChunkCoord coord() const { return coord_; }
  int lod() const { return lod_; }
  double voxel_size() const { return kVoxelSize * static_cast<double>(1 << lod_); }

  bool is_uniform() const { return uniform_; }
  Voxel uniform_value() const { return uniform_value_; }

  Voxel get(int x, int y, int z) const {
    if (uniform_) return uniform_value_;
    const int i = voxel_index(x, y, z);
    return {sdf_[i], palette_[mat_[i]]};
  }
  int8_t sdf(int x, int y, int z) const { return uniform_ ? uniform_value_.sdf : sdf_[voxel_index(x, y, z)]; }
  Material material(int x, int y, int z) const { return uniform_ ? uniform_value_.material : palette_[mat_[voxel_index(x, y, z)]]; }

  void fill(Voxel v);
  void set(int x, int y, int z, Voxel v);
  // Bulk write used by the generator: arrays in voxel_index order.
  void assign(const std::vector<int8_t>& sdf, const std::vector<Material>& mats);
  // Collapse to uniform storage if every voxel is identical.
  bool try_make_uniform();

  size_t memory_bytes() const;
  uint64_t content_hash() const;
  bool contains_surface() const;  // has both solid and non-solid voxels

  uint32_t revision() const { return revision_; }
  void bump_revision() { ++revision_; }
  bool modified() const { return modified_; }
  void set_modified(bool m) { modified_ = m; }

  // Raw access for codecs / meshers (only valid when !is_uniform()).
  const std::vector<int8_t>& raw_sdf() const { return sdf_; }
  const std::vector<uint8_t>& raw_palette_index() const { return mat_; }
  const std::vector<Material>& palette() const { return palette_; }

 private:
  void expand();
  uint8_t palette_index(Material m);

  ChunkCoord coord_{};
  int lod_ = 0;
  bool uniform_ = true;
  Voxel uniform_value_{};
  std::vector<int8_t> sdf_;
  std::vector<uint8_t> mat_;
  std::vector<Material> palette_;
  std::array<int16_t, kMaterialCount> lookup_{};
  uint32_t revision_ = 0;
  bool modified_ = false;
};

}  // namespace primeva
