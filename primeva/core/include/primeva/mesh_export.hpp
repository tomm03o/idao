#pragma once

#include <string>
#include <vector>

#include "primeva/mesher.hpp"

namespace primeva {

struct ExportMesh {
  std::string name;
  const MeshData* mesh = nullptr;
  Vec3d offset{};          // world offset of the mesh's local frame (metres)
  float base_color[4] = {1, 1, 1, 1};
  float roughness = 0.9f;
  bool vertex_colors = true;  // material preview albedo as COLOR_0
};

// Binary glTF 2.0 (.glb). Positions are written relative to `origin` so float
// precision is preserved even at continental coordinates.
bool write_glb(const std::string& path, const std::vector<ExportMesh>& meshes, const Vec3d& origin);

// Merges chunk-local meshes into one mesh in a common local frame.
void append_mesh(MeshData& dst, const MeshData& src, const Vec3f& offset);

}  // namespace primeva
