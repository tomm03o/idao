#pragma once

#include <cstdint>
#include <vector>

#include "primeva/material.hpp"
#include "primeva/math.hpp"
#include "primeva/voxel_world.hpp"

namespace primeva {

// Coordinates are chunk-local metres in Primeva's frame: right-handed, +Y up,
// +X east, +Z south (same as glTF). The Unreal plugin converts to UE's
// left-handed Z-up centimetre frame: UE(X, Y, Z) = (x, z, y) * 100.
struct MeshData {
  std::vector<Vec3f> positions;
  std::vector<Vec3f> normals;
  std::vector<uint16_t> materials;  // per-vertex dominant material id
  std::vector<uint32_t> indices;    // CCW front faces
  void clear() { positions.clear(); normals.clear(); materials.clear(); indices.clear(); }
  bool empty() const { return indices.empty(); }
};

struct ChunkMesh {
  MeshData terrain;
  MeshData fluid;  // water/lava surfaces against air only
};

// Naive Surface Nets (Gibson 1998) over the signed distance field.
// The chunk owns every grid edge whose lower endpoint lies inside it, so
// neighbouring chunk meshes share vertices exactly on the boundary.
void mesh_chunk(const SampleGrid& grid, double voxel_size, ChunkMesh& out);

}  // namespace primeva
