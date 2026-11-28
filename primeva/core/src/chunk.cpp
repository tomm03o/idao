#include "primeva/chunk.hpp"

#include "primeva/hash.hpp"

namespace primeva {

void Chunk::fill(Voxel v) {
  uniform_ = true;
  uniform_value_ = v;
  sdf_.clear(); sdf_.shrink_to_fit();
  mat_.clear(); mat_.shrink_to_fit();
  palette_.clear();
}

void Chunk::expand() {
  if (!uniform_) return;
  uniform_ = false;
  sdf_.assign(kChunkVolume, uniform_value_.sdf);
  palette_.clear();
  lookup_.fill(-1);
  const uint8_t pi = palette_index(uniform_value_.material);
  mat_.assign(kChunkVolume, pi);
}

uint8_t Chunk::palette_index(Material m) {
  const auto mi = static_cast<size_t>(m);
  if (lookup_[mi] < 0) {
    lookup_[mi] = static_cast<int16_t>(palette_.size());
    palette_.push_back(m);
  }
  return static_cast<uint8_t>(lookup_[mi]);
}

void Chunk::set(int x, int y, int z, Voxel v) {
  if (uniform_) {
    if (v == uniform_value_) return;
    expand();
  }
  const int i = voxel_index(x, y, z);
  sdf_[i] = v.sdf;
  mat_[i] = palette_index(v.material);
}

void Chunk::assign(const std::vector<int8_t>& sdf, const std::vector<Material>& mats) {
  uniform_ = false;
  sdf_ = sdf;
  palette_.clear();
  lookup_.fill(-1);
  mat_.resize(kChunkVolume);
  for (int i = 0; i < kChunkVolume; ++i) mat_[i] = palette_index(mats[i]);
  try_make_uniform();
}

bool Chunk::try_make_uniform() {
  if (uniform_) return true;
  const int8_t s0 = sdf_[0];
  const uint8_t m0 = mat_[0];
  for (int i = 1; i < kChunkVolume; ++i)
    if (sdf_[i] != s0 || mat_[i] != m0) return false;
  const Voxel v{s0, palette_[m0]};
  fill(v);
  return true;
}

size_t Chunk::memory_bytes() const {
  return sizeof(Chunk) + sdf_.capacity() + mat_.capacity() + palette_.capacity() * sizeof(Material);
}

uint64_t Chunk::content_hash() const {
  uint64_t h = hash3(0xC0FFEEULL, coord_.x, coord_.y, coord_.z) ^ static_cast<uint64_t>(lod_);
  for (int i = 0; i < kChunkVolume; ++i) {
    const Voxel v = uniform_ ? uniform_value_ : Voxel{sdf_[i], palette_[mat_[i]]};
    h = (h ^ (static_cast<uint64_t>(static_cast<uint8_t>(v.sdf)) | (static_cast<uint64_t>(v.material) << 8))) * 0x100000001B3ULL;
  }
  return mix64(h);
}

bool Chunk::contains_surface() const {
  if (uniform_) return false;
  bool any_solid = false, any_empty = false;
  for (int8_t s : sdf_) {
    if (s < 0) any_solid = true; else any_empty = true;
    if (any_solid && any_empty) return true;
  }
  return false;
}

}  // namespace primeva
