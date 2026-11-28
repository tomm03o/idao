#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>

#include "primeva/config.hpp"

namespace primeva {

struct IVec3 {
  int32_t x = 0, y = 0, z = 0;
  constexpr IVec3() = default;
  constexpr IVec3(int32_t x_, int32_t y_, int32_t z_) : x(x_), y(y_), z(z_) {}
  constexpr IVec3 operator+(const IVec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
  constexpr IVec3 operator-(const IVec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
  constexpr IVec3 operator*(int32_t s) const { return {x * s, y * s, z * s}; }
  constexpr bool operator==(const IVec3& o) const = default;
};

template <typename T>
struct TVec3 {
  T x = 0, y = 0, z = 0;
  constexpr TVec3() = default;
  constexpr TVec3(T x_, T y_, T z_) : x(x_), y(y_), z(z_) {}
  constexpr TVec3 operator+(const TVec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
  constexpr TVec3 operator-(const TVec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
  constexpr TVec3 operator*(T s) const { return {x * s, y * s, z * s}; }
  constexpr TVec3 operator/(T s) const { return {x / s, y / s, z / s}; }
  constexpr TVec3& operator+=(const TVec3& o) { x += o.x; y += o.y; z += o.z; return *this; }
  constexpr TVec3& operator-=(const TVec3& o) { x -= o.x; y -= o.y; z -= o.z; return *this; }
  constexpr TVec3& operator*=(T s) { x *= s; y *= s; z *= s; return *this; }
  constexpr bool operator==(const TVec3& o) const = default;
};
using Vec3f = TVec3<float>;
using Vec3d = TVec3<double>;

template <typename T> constexpr T dot(const TVec3<T>& a, const TVec3<T>& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
template <typename T> constexpr TVec3<T> cross(const TVec3<T>& a, const TVec3<T>& b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
template <typename T> inline T length(const TVec3<T>& v) { return std::sqrt(dot(v, v)); }
template <typename T> inline TVec3<T> normalize(const TVec3<T>& v) {
  const T l = length(v);
  return l > T(0) ? v / l : TVec3<T>{T(0), T(1), T(0)};
}

// Floor division / modulo that behave correctly for negative coordinates.
constexpr int32_t floor_div(int32_t a, int32_t b) {
  const int32_t q = a / b;
  return (a % b != 0 && ((a < 0) != (b < 0))) ? q - 1 : q;
}
constexpr int32_t floor_mod(int32_t a, int32_t b) { return a - floor_div(a, b) * b; }
constexpr int32_t floor_shift(int32_t a, int s) { return a >> s; }  // arithmetic shift == floor for powers of 2

template <typename T> constexpr T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }
template <typename T> constexpr T lerp(T a, T b, T t) { return a + (b - a) * t; }
constexpr double smoothstep(double e0, double e1, double x) {
  const double t = clamp((x - e0) / (e1 - e0), 0.0, 1.0);
  return t * t * (3.0 - 2.0 * t);
}
// Polynomial smooth minimum (Quilez), k = blend radius in field units.
inline double smin(double a, double b, double k) {
  if (k <= 0.0) return std::min(a, b);
  const double h = std::max(k - std::abs(a - b), 0.0) / k;
  return std::min(a, b) - h * h * k * 0.25;
}
inline double smax(double a, double b, double k) { return -smin(-a, -b, k); }

// --- Coordinates -------------------------------------------------------------
// Voxel coordinates are integer indices at LOD 0. Voxel (i,j,k) covers
// [i*s, (i+1)*s) and its sample point is its centre (i+0.5)*s.
struct ChunkCoord {
  int32_t x = 0, y = 0, z = 0;
  constexpr bool operator==(const ChunkCoord& o) const = default;
  constexpr IVec3 origin_voxel() const { return {x << kChunkShift, y << kChunkShift, z << kChunkShift}; }
  static constexpr ChunkCoord from_voxel(const IVec3& v) {
    return {floor_shift(v.x, kChunkShift), floor_shift(v.y, kChunkShift), floor_shift(v.z, kChunkShift)};
  }
};

constexpr IVec3 voxel_local(const IVec3& v) { return {v.x & kChunkMask, v.y & kChunkMask, v.z & kChunkMask}; }
constexpr int voxel_index(int x, int y, int z) { return (y * kChunkSize + z) * kChunkSize + x; }  // x fastest, y slowest
inline Vec3d voxel_center_m(const IVec3& v) {
  return {(v.x + 0.5) * kVoxelSize, (v.y + 0.5) * kVoxelSize, (v.z + 0.5) * kVoxelSize};
}
inline IVec3 voxel_at_m(const Vec3d& p) {
  return {static_cast<int32_t>(std::floor(p.x * kVoxelsPerMetre)),
          static_cast<int32_t>(std::floor(p.y * kVoxelsPerMetre)),
          static_cast<int32_t>(std::floor(p.z * kVoxelsPerMetre))};
}

struct ChunkCoordHash {
  size_t operator()(const ChunkCoord& c) const noexcept {
    uint64_t h = static_cast<uint32_t>(c.x);
    h = h * 0x9E3779B97F4A7C15ULL ^ static_cast<uint32_t>(c.y);
    h = h * 0xC2B2AE3D27D4EB4FULL ^ static_cast<uint32_t>(c.z);
    h ^= h >> 31;
    return static_cast<size_t>(h * 0x165667B19E3779F9ULL);
  }
};

}  // namespace primeva
