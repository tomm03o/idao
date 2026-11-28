#include "primeva/mesh_export.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>

namespace primeva {

void append_mesh(MeshData& dst, const MeshData& src, const Vec3f& offset) {
  const uint32_t base = static_cast<uint32_t>(dst.positions.size());
  for (const auto& p : src.positions) dst.positions.push_back(p + offset);
  dst.normals.insert(dst.normals.end(), src.normals.begin(), src.normals.end());
  dst.materials.insert(dst.materials.end(), src.materials.begin(), src.materials.end());
  for (uint32_t i : src.indices) dst.indices.push_back(base + i);
}

namespace {

inline float srgb_to_linear(uint8_t c) {
  const float v = c / 255.0f;
  return v <= 0.04045f ? v / 12.92f : std::pow((v + 0.055f) / 1.055f, 2.4f);
}

void pad4(std::vector<uint8_t>& b, uint8_t fill) {
  while (b.size() % 4) b.push_back(fill);
}

template <typename T>
size_t append_raw(std::vector<uint8_t>& bin, const std::vector<T>& v) {
  pad4(bin, 0);
  const size_t off = bin.size();
  const auto* p = reinterpret_cast<const uint8_t*>(v.data());
  bin.insert(bin.end(), p, p + v.size() * sizeof(T));
  return off;
}

}  // namespace

bool write_glb(const std::string& path, const std::vector<ExportMesh>& meshes, const Vec3d& origin) {
  std::vector<uint8_t> bin;
  std::ostringstream views, accessors, gmeshes, materials, nodes;
  int view_count = 0, acc_count = 0, mesh_count = 0;
  bool first_mesh = true;

  auto add_view = [&](size_t off, size_t len, int target) {
    if (view_count) views << ",";
    views << "{\"buffer\":0,\"byteOffset\":" << off << ",\"byteLength\":" << len;
    if (target) views << ",\"target\":" << target;
    views << "}";
    return view_count++;
  };
  auto add_acc = [&](int view, int comp, size_t count, const char* type, const std::string& extra) {
    if (acc_count) accessors << ",";
    accessors << "{\"bufferView\":" << view << ",\"componentType\":" << comp << ",\"count\":" << count << ",\"type\":\"" << type
              << "\"" << extra << "}";
    return acc_count++;
  };

  for (const auto& em : meshes) {
    if (!em.mesh || em.mesh->empty()) continue;
    const MeshData& m = *em.mesh;
    const Vec3f off{static_cast<float>(em.offset.x - origin.x), static_cast<float>(em.offset.y - origin.y),
                    static_cast<float>(em.offset.z - origin.z)};
    std::vector<float> pos;
    pos.reserve(m.positions.size() * 3);
    float mn[3] = {1e30f, 1e30f, 1e30f}, mx[3] = {-1e30f, -1e30f, -1e30f};
    for (const auto& p : m.positions) {
      const float v[3] = {p.x + off.x, p.y + off.y, p.z + off.z};
      for (int k = 0; k < 3; ++k) { mn[k] = std::min(mn[k], v[k]); mx[k] = std::max(mx[k], v[k]); pos.push_back(v[k]); }
    }
    std::vector<float> nrm;
    nrm.reserve(m.normals.size() * 3);
    for (const auto& n : m.normals) { nrm.push_back(n.x); nrm.push_back(n.y); nrm.push_back(n.z); }
    std::vector<float> col;
    if (em.vertex_colors) {
      col.reserve(m.materials.size() * 4);
      for (uint16_t mid : m.materials) {
        const auto& mi = material_info(static_cast<Material>(mid));
        col.push_back(srgb_to_linear(mi.r)); col.push_back(srgb_to_linear(mi.g)); col.push_back(srgb_to_linear(mi.b)); col.push_back(1.f);
      }
    }
    const size_t vcount = m.positions.size();
    const int vp = add_view(append_raw(bin, pos), pos.size() * 4, 34962);
    std::ostringstream mm;
    mm << ",\"min\":[" << mn[0] << "," << mn[1] << "," << mn[2] << "],\"max\":[" << mx[0] << "," << mx[1] << "," << mx[2] << "]";
    const int ap = add_acc(vp, 5126, vcount, "VEC3", mm.str());
    const int vn = add_view(append_raw(bin, nrm), nrm.size() * 4, 34962);
    const int an = add_acc(vn, 5126, vcount, "VEC3", "");
    int ac = -1;
    if (em.vertex_colors) {
      const int vc = add_view(append_raw(bin, col), col.size() * 4, 34962);
      ac = add_acc(vc, 5126, vcount, "VEC4", "");
    }
    const int vi = add_view(append_raw(bin, m.indices), m.indices.size() * 4, 34963);
    const int ai = add_acc(vi, 5125, m.indices.size(), "SCALAR", "");

    if (!first_mesh) { gmeshes << ","; materials << ","; nodes << ","; }
    first_mesh = false;
    materials << "{\"name\":\"" << em.name << "\",\"pbrMetallicRoughness\":{\"baseColorFactor\":[" << em.base_color[0] << ","
              << em.base_color[1] << "," << em.base_color[2] << "," << em.base_color[3] << "],\"metallicFactor\":0,\"roughnessFactor\":"
              << em.roughness << "}" << (em.base_color[3] < 1.f ? ",\"alphaMode\":\"BLEND\"" : "") << ",\"doubleSided\":false}";
    gmeshes << "{\"name\":\"" << em.name << "\",\"primitives\":[{\"attributes\":{\"POSITION\":" << ap << ",\"NORMAL\":" << an;
    if (ac >= 0) gmeshes << ",\"COLOR_0\":" << ac;
    gmeshes << "},\"indices\":" << ai << ",\"material\":" << mesh_count << ",\"mode\":4}]}";
    nodes << "{\"name\":\"" << em.name << "\",\"mesh\":" << mesh_count << "}";
    ++mesh_count;
  }
  pad4(bin, 0);

  std::ostringstream json;
  json << "{\"asset\":{\"version\":\"2.0\",\"generator\":\"primeva_core\"},\"scene\":0,\"scenes\":[{\"nodes\":[";
  for (int i = 0; i < mesh_count; ++i) json << (i ? "," : "") << i;
  json << "]}],\"nodes\":[" << nodes.str() << "],\"meshes\":[" << gmeshes.str() << "],\"materials\":[" << materials.str()
       << "],\"accessors\":[" << accessors.str() << "],\"bufferViews\":[" << views.str() << "],\"buffers\":[{\"byteLength\":"
       << bin.size() << "}]}";
  std::string js = json.str();
  while (js.size() % 4) js.push_back(' ');

  std::ofstream f(path, std::ios::binary | std::ios::trunc);
  if (!f) return false;
  auto u32 = [&](uint32_t v) { f.write(reinterpret_cast<const char*>(&v), 4); };
  const uint32_t total = 12 + 8 + static_cast<uint32_t>(js.size()) + 8 + static_cast<uint32_t>(bin.size());
  u32(0x46546C67); u32(2); u32(total);
  u32(static_cast<uint32_t>(js.size())); u32(0x4E4F534A);
  f.write(js.data(), static_cast<std::streamsize>(js.size()));
  u32(static_cast<uint32_t>(bin.size())); u32(0x004E4942);
  f.write(reinterpret_cast<const char*>(bin.data()), static_cast<std::streamsize>(bin.size()));
  return static_cast<bool>(f);
}

}  // namespace primeva
