#include "primeva/mesher.hpp"

#include <array>
#include <cmath>

namespace primeva {
namespace {

constexpr int G = SampleGrid::kSize;  // 34: voxel coords -1..32
constexpr int C = kChunkSize + 1;     // 33 cells per axis: cell min corner -1..31

// Cell corner k: bit0 = +x, bit1 = +y, bit2 = +z
constexpr int kCorner[8][3] = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {1, 1, 0}, {0, 0, 1}, {1, 0, 1}, {0, 1, 1}, {1, 1, 1}};
constexpr int kEdges[12][2] = {{0, 1}, {2, 3}, {4, 5}, {6, 7}, {0, 2}, {1, 3}, {4, 6}, {5, 7}, {0, 4}, {1, 5}, {2, 6}, {3, 7}};

inline int cell_index(int cx, int cy, int cz) { return ((cy + 1) * C + (cz + 1)) * C + (cx + 1); }

void emit_quad(MeshData& m, uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
  // Split along the shorter diagonal for better triangle quality.
  const Vec3f& pa = m.positions[a];
  const Vec3f& pb = m.positions[b];
  const Vec3f& pc = m.positions[c];
  const Vec3f& pd = m.positions[d];
  const Vec3f ac = pc - pa, bd = pd - pb;
  if (dot(ac, ac) <= dot(bd, bd)) {
    m.indices.insert(m.indices.end(), {a, b, c, a, c, d});
  } else {
    m.indices.insert(m.indices.end(), {a, b, d, b, c, d});
  }
}

template <typename IsInside, typename Value, typename EdgeAllowed, typename MatOf>
void surface_nets(const SampleGrid& /*grid*/, double vs, MeshData& m, IsInside inside, Value value, EdgeAllowed edge_allowed, MatOf mat_of,
                  bool compute_gradient_normals) {
  std::vector<int32_t> cell_vertex(static_cast<size_t>(C) * C * C, -1);
  for (int cy = -1; cy < kChunkSize; ++cy)
    for (int cz = -1; cz < kChunkSize; ++cz)
      for (int cx = -1; cx < kChunkSize; ++cx) {
        int idx[8];
        double val[8];
        int mask = 0;
        for (int k = 0; k < 8; ++k) {
          idx[k] = SampleGrid::index(cx + kCorner[k][0], cy + kCorner[k][1], cz + kCorner[k][2]);
          val[k] = value(idx[k]);
          if (inside(idx[k])) mask |= 1 << k;
        }
        if (mask == 0 || mask == 0xFF) continue;
        double px = 0, py = 0, pz = 0;
        int n = 0;
        for (const auto& e : kEdges) {
          const bool ia = (mask >> e[0]) & 1, ib = (mask >> e[1]) & 1;
          if (ia == ib || !edge_allowed(idx[e[0]], idx[e[1]])) continue;
          const double va = val[e[0]], vb = val[e[1]];
          double t = (va == vb) ? 0.5 : va / (va - vb);
          t = clamp(t, 0.0, 1.0);
          px += kCorner[e[0]][0] + t * (kCorner[e[1]][0] - kCorner[e[0]][0]);
          py += kCorner[e[0]][1] + t * (kCorner[e[1]][1] - kCorner[e[0]][1]);
          pz += kCorner[e[0]][2] + t * (kCorner[e[1]][2] - kCorner[e[0]][2]);
          ++n;
        }
        if (n == 0) continue;
        px /= n; py /= n; pz /= n;
        // Trilinear gradient of the field at the vertex -> outward normal.
        Vec3f normal{0, 1, 0};
        if (compute_gradient_normals) {
          const double gx = (1 - py) * (1 - pz) * (val[1] - val[0]) + py * (1 - pz) * (val[3] - val[2]) +
                            (1 - py) * pz * (val[5] - val[4]) + py * pz * (val[7] - val[6]);
          const double gy = (1 - px) * (1 - pz) * (val[2] - val[0]) + px * (1 - pz) * (val[3] - val[1]) +
                            (1 - px) * pz * (val[6] - val[4]) + px * pz * (val[7] - val[5]);
          const double gz = (1 - px) * (1 - py) * (val[4] - val[0]) + px * (1 - py) * (val[5] - val[1]) +
                            (1 - px) * py * (val[6] - val[2]) + px * py * (val[7] - val[3]);
          normal = normalize(Vec3f{static_cast<float>(gx), static_cast<float>(gy), static_cast<float>(gz)});
        }
        // Material: the most interior corner.
        int best = -1;
        double bestv = 1e300;
        for (int k = 0; k < 8; ++k)
          if (((mask >> k) & 1) && val[k] < bestv) { bestv = val[k]; best = k; }
        cell_vertex[cell_index(cx, cy, cz)] = static_cast<int32_t>(m.positions.size());
        // Voxel centres sit at (v + 0.5) * vs in chunk-local metres.
        m.positions.push_back({static_cast<float>((cx + 0.5 + px) * vs), static_cast<float>((cy + 0.5 + py) * vs),
                               static_cast<float>((cz + 0.5 + pz) * vs)});
        m.normals.push_back(normal);
        m.materials.push_back(static_cast<uint16_t>(mat_of(idx[best])));
      }

  // Quads for owned edges: lower endpoint p in [0, 32)^3, edge along +axis.
  for (int y = 0; y < kChunkSize; ++y)
    for (int z = 0; z < kChunkSize; ++z)
      for (int x = 0; x < kChunkSize; ++x) {
        const int i0 = SampleGrid::index(x, y, z);
        const bool in0 = inside(i0);
        for (int axis = 0; axis < 3; ++axis) {
          const int nx = x + (axis == 0), ny = y + (axis == 1), nz = z + (axis == 2);
          const int i1 = SampleGrid::index(nx, ny, nz);
          const bool in1 = inside(i1);
          if (in0 == in1 || !edge_allowed(i0, i1)) continue;
          // The four cells around the edge, ordered so (u, v) follow the
          // right-handed cyclic order (x->y->z): axis x: u=y, v=z; y: u=z, v=x; z: u=x, v=y.
          int c[4][3];
          const int du[3][3] = {{0, 1, 0}, {0, 0, 1}, {1, 0, 0}};
          const int dv[3][3] = {{0, 0, 1}, {1, 0, 0}, {0, 1, 0}};
          const int corner_uv[4][2] = {{-1, -1}, {0, -1}, {0, 0}, {-1, 0}};
          for (int q = 0; q < 4; ++q) {
            c[q][0] = x + corner_uv[q][0] * du[axis][0] + corner_uv[q][1] * dv[axis][0];
            c[q][1] = y + corner_uv[q][0] * du[axis][1] + corner_uv[q][1] * dv[axis][1];
            c[q][2] = z + corner_uv[q][0] * du[axis][2] + corner_uv[q][1] * dv[axis][2];
          }
          int32_t vi[4];
          bool ok = true;
          for (int q = 0; q < 4; ++q) {
            vi[q] = cell_vertex[cell_index(c[q][0], c[q][1], c[q][2])];
            if (vi[q] < 0) { ok = false; break; }
          }
          if (!ok) continue;
          // in0 (lower endpoint inside) => surface faces +axis => keep order.
          if (in0) emit_quad(m, static_cast<uint32_t>(vi[0]), static_cast<uint32_t>(vi[1]), static_cast<uint32_t>(vi[2]), static_cast<uint32_t>(vi[3]));
          else emit_quad(m, static_cast<uint32_t>(vi[3]), static_cast<uint32_t>(vi[2]), static_cast<uint32_t>(vi[1]), static_cast<uint32_t>(vi[0]));
        }
      }
}

}  // namespace

void mesh_chunk(const SampleGrid& grid, double vs, ChunkMesh& out) {
  out.terrain.clear();
  out.fluid.clear();
  // Terrain: solid where sdf < 0. Field value = sdf (crossing at zero).
  surface_nets(
      grid, vs, out.terrain, [&](int i) { return grid.sdf[i] < 0; },
      [&](int i) { return static_cast<double>(grid.sdf[i]) + 0.5; },  // quantised 0 counts as outside: shift so the zero crossing is consistent
      [](int, int) { return true; }, [&](int i) { return static_cast<int>(grid.mat[i]); }, true);

  // Fluids: binary field (fluid -0.5 / air +0.5); only fluid-air interfaces
  // produce faces (fluid-solid contact is hidden by terrain).
  auto is_fluid_v = [&](int i) { return grid.sdf[i] >= 0 && is_fluid(grid.mat[i]); };
  auto is_air_v = [&](int i) { return grid.sdf[i] >= 0 && grid.mat[i] == Material::Air; };
  surface_nets(
      grid, vs, out.fluid, is_fluid_v, [&](int i) { return is_fluid_v(i) ? -0.5 : 0.5; },
      [&](int a, int b) { return (is_fluid_v(a) && is_air_v(b)) || (is_fluid_v(b) && is_air_v(a)); },
      [&](int i) { return static_cast<int>(grid.mat[i]); }, true);
}

}  // namespace primeva
