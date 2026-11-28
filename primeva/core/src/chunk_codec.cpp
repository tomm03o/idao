#include "primeva/chunk_codec.hpp"

namespace primeva {
namespace {

constexpr uint8_t kCodecVersion = 1;

void put_varint(std::vector<uint8_t>& out, uint32_t v) {
  while (v >= 0x80) {
    out.push_back(static_cast<uint8_t>(v | 0x80));
    v >>= 7;
  }
  out.push_back(static_cast<uint8_t>(v));
}

bool get_varint(const uint8_t* d, size_t n, size_t& pos, uint32_t& v) {
  v = 0;
  for (int shift = 0; shift < 35; shift += 7) {
    if (pos >= n) return false;
    const uint8_t b = d[pos++];
    v |= static_cast<uint32_t>(b & 0x7F) << shift;
    if (!(b & 0x80)) return true;
  }
  return false;
}

template <typename T>
void put_rle(std::vector<uint8_t>& out, const std::vector<T>& v) {
  size_t i = 0;
  while (i < v.size()) {
    size_t j = i + 1;
    while (j < v.size() && v[j] == v[i]) ++j;
    put_varint(out, static_cast<uint32_t>(j - i));
    out.push_back(static_cast<uint8_t>(v[i]));
    i = j;
  }
}

template <typename T>
bool get_rle(const uint8_t* d, size_t n, size_t& pos, std::vector<T>& v, size_t count) {
  v.clear();
  v.reserve(count);
  while (v.size() < count) {
    uint32_t run = 0;
    if (!get_varint(d, n, pos, run) || run == 0 || pos >= n) return false;
    if (v.size() + run > count) return false;
    const T val = static_cast<T>(d[pos++]);
    v.insert(v.end(), run, val);
  }
  return true;
}

}  // namespace

std::vector<uint8_t> encode_chunk(const Chunk& c) {
  std::vector<uint8_t> out;
  out.push_back(kCodecVersion);
  out.push_back(static_cast<uint8_t>(c.lod()));
  if (c.is_uniform()) {
    out.push_back(0);
    const Voxel v = c.uniform_value();
    out.push_back(static_cast<uint8_t>(v.sdf));
    const auto m = static_cast<uint16_t>(v.material);
    out.push_back(static_cast<uint8_t>(m & 0xFF));
    out.push_back(static_cast<uint8_t>(m >> 8));
    return out;
  }
  out.push_back(1);
  const auto& pal = c.palette();
  out.push_back(static_cast<uint8_t>(pal.size() - 1));
  for (Material m : pal) {
    const auto mv = static_cast<uint16_t>(m);
    out.push_back(static_cast<uint8_t>(mv & 0xFF));
    out.push_back(static_cast<uint8_t>(mv >> 8));
  }
  put_rle(out, c.raw_sdf());
  put_rle(out, c.raw_palette_index());
  return out;
}

std::optional<Chunk> decode_chunk(const uint8_t* d, size_t n, ChunkCoord coord) {
  if (n < 3 || d[0] != kCodecVersion) return std::nullopt;
  const int lod = d[1];
  Chunk c(coord, lod);
  size_t pos = 3;
  if (d[2] == 0) {
    if (n < 6) return std::nullopt;
    const auto sdf = static_cast<int8_t>(d[3]);
    const uint16_t m = static_cast<uint16_t>(d[4] | (d[5] << 8));
    if (m >= kMaterialCount) return std::nullopt;
    c.fill({sdf, static_cast<Material>(m)});
    return c;
  }
  if (d[2] != 1 || pos >= n) return std::nullopt;
  const size_t pal_len = static_cast<size_t>(d[pos++]) + 1;
  if (pos + pal_len * 2 > n) return std::nullopt;
  std::vector<Material> pal(pal_len);
  for (size_t k = 0; k < pal_len; ++k) {
    const uint16_t m = static_cast<uint16_t>(d[pos] | (d[pos + 1] << 8));
    pos += 2;
    if (m >= kMaterialCount) return std::nullopt;
    pal[k] = static_cast<Material>(m);
  }
  std::vector<int8_t> sdf;
  std::vector<uint8_t> idx;
  if (!get_rle(d, n, pos, sdf, kChunkVolume) || !get_rle(d, n, pos, idx, kChunkVolume)) return std::nullopt;
  std::vector<Material> mats(kChunkVolume);
  for (int i = 0; i < kChunkVolume; ++i) {
    if (idx[i] >= pal_len) return std::nullopt;
    mats[i] = pal[idx[i]];
  }
  c.assign(sdf, mats);
  return c;
}

}  // namespace primeva
