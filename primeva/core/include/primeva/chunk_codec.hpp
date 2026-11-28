#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "primeva/chunk.hpp"

namespace primeva {

// Compact, versioned binary encoding of a chunk:
//   u8 version | u8 lod | u8 kind (0 uniform, 1 mixed)
//   uniform: i8 sdf, u16 material
//   mixed:   u8 palette_len-1, u16 palette[], RLE(sdf), RLE(palette index)
// RLE = sequence of (LEB128 run length, value byte) covering 32768 voxels.
// A typical surface chunk encodes to 3-12 KiB (vs 64 KiB raw).
std::vector<uint8_t> encode_chunk(const Chunk& c);
std::optional<Chunk> decode_chunk(const uint8_t* data, size_t size, ChunkCoord coord);

}  // namespace primeva
