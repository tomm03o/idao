#include "primeva/noise.hpp"

#include <algorithm>
#include <array>
#include <cmath>

#include "primeva/dmath.hpp"
#include "primeva/hash.hpp"

namespace primeva::noise {
namespace {

// Gradient tables are built with the deterministic dmath sin/cos so that every
// platform produces bit-identical gradients (see dmath.hpp).
struct GradTables {
  std::array<double, 256 * 2> g2{};
  std::array<double, 256 * 3> g3{};
  GradTables() {
    constexpr double kPi = dmath::kPi;
    for (int i = 0; i < 256; ++i) {
      const double a = (i + 0.5) * (2.0 * kPi / 256.0);
      g2[i * 2 + 0] = dmath::cos(a);
      g2[i * 2 + 1] = dmath::sin(a);
    }
    // Fibonacci sphere: 256 near-uniform unit directions.
    const double golden = kPi * (3.0 - std::sqrt(5.0));
    for (int i = 0; i < 256; ++i) {
      const double y = 1.0 - (i + 0.5) * (2.0 / 256.0);
      const double r = std::sqrt(1.0 - y * y);
      const double t = golden * i;
      g3[i * 3 + 0] = dmath::cos(t) * r;
      g3[i * 3 + 1] = y;
      g3[i * 3 + 2] = dmath::sin(t) * r;
    }
  }
};
const GradTables& tables() {
  static const GradTables t;
  return t;
}

inline double fade(double t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }

inline double grad2(uint64_t seed, int64_t ix, int64_t iy, double dx, double dy) {
  const auto& g = tables().g2;
  const unsigned i = static_cast<unsigned>(hash2(seed, ix, iy) >> 56);
  return g[i * 2] * dx + g[i * 2 + 1] * dy;
}
inline double grad3(uint64_t seed, int64_t ix, int64_t iy, int64_t iz, double dx, double dy, double dz) {
  const auto& g = tables().g3;
  const unsigned i = static_cast<unsigned>(hash3(seed, ix, iy, iz) >> 56);
  return g[i * 3] * dx + g[i * 3 + 1] * dy + g[i * 3 + 2] * dz;
}

inline uint64_t octave_seed(uint64_t seed, int o) { return mix64(seed + 0x632BE59BD9B4E019ULL * static_cast<uint64_t>(o + 1)); }

}  // namespace

double perlin2(uint64_t seed, double x, double y) {
  const double fx = std::floor(x), fy = std::floor(y);
  const int64_t ix = static_cast<int64_t>(fx), iy = static_cast<int64_t>(fy);
  const double dx = x - fx, dy = y - fy;
  const double u = fade(dx), v = fade(dy);
  const double n00 = grad2(seed, ix, iy, dx, dy);
  const double n10 = grad2(seed, ix + 1, iy, dx - 1.0, dy);
  const double n01 = grad2(seed, ix, iy + 1, dx, dy - 1.0);
  const double n11 = grad2(seed, ix + 1, iy + 1, dx - 1.0, dy - 1.0);
  const double nx0 = n00 + u * (n10 - n00);
  const double nx1 = n01 + u * (n11 - n01);
  return (nx0 + v * (nx1 - nx0)) * 1.41421356237;  // max |value| of 2D Perlin with unit gradients ~ 1/sqrt(2)
}

double perlin3(uint64_t seed, double x, double y, double z) {
  const double fx = std::floor(x), fy = std::floor(y), fz = std::floor(z);
  const int64_t ix = static_cast<int64_t>(fx), iy = static_cast<int64_t>(fy), iz = static_cast<int64_t>(fz);
  const double dx = x - fx, dy = y - fy, dz = z - fz;
  const double u = fade(dx), v = fade(dy), w = fade(dz);
  const double n000 = grad3(seed, ix, iy, iz, dx, dy, dz);
  const double n100 = grad3(seed, ix + 1, iy, iz, dx - 1, dy, dz);
  const double n010 = grad3(seed, ix, iy + 1, iz, dx, dy - 1, dz);
  const double n110 = grad3(seed, ix + 1, iy + 1, iz, dx - 1, dy - 1, dz);
  const double n001 = grad3(seed, ix, iy, iz + 1, dx, dy, dz - 1);
  const double n101 = grad3(seed, ix + 1, iy, iz + 1, dx - 1, dy, dz - 1);
  const double n011 = grad3(seed, ix, iy + 1, iz + 1, dx, dy - 1, dz - 1);
  const double n111 = grad3(seed, ix + 1, iy + 1, iz + 1, dx - 1, dy - 1, dz - 1);
  const double x00 = n000 + u * (n100 - n000), x10 = n010 + u * (n110 - n010);
  const double x01 = n001 + u * (n101 - n001), x11 = n011 + u * (n111 - n011);
  const double y0 = x00 + v * (x10 - x00), y1 = x01 + v * (x11 - x01);
  return (y0 + w * (y1 - y0)) * 1.15470053838;  // 1/(sqrt(3)/2)
}

double fbm2(uint64_t seed, double x, double y, int octaves, double lacunarity, double gain) {
  double sum = 0.0, amp = 1.0, norm = 0.0, f = 1.0;
  for (int o = 0; o < octaves; ++o) {
    sum += amp * perlin2(octave_seed(seed, o), x * f, y * f);
    norm += amp;
    amp *= gain;
    f *= lacunarity;
  }
  return norm > 0 ? sum / norm : 0.0;
}

double fbm3(uint64_t seed, double x, double y, double z, int octaves, double lacunarity, double gain) {
  double sum = 0.0, amp = 1.0, norm = 0.0, f = 1.0;
  for (int o = 0; o < octaves; ++o) {
    sum += amp * perlin3(octave_seed(seed, o), x * f, y * f, z * f);
    norm += amp;
    amp *= gain;
    f *= lacunarity;
  }
  return norm > 0 ? sum / norm : 0.0;
}

double ridged2(uint64_t seed, double x, double y, int octaves, double lacunarity, double gain) {
  // Musgrave's ridged multifractal with signal-weighted octaves: detail
  // accumulates on crests and stays smooth in valleys, like real ranges.
  double sum = 0.0, norm = 0.0, amp = 1.0, f = 1.0, weight = 1.0;
  for (int o = 0; o < octaves; ++o) {
    double s = 1.0 - std::abs(perlin2(octave_seed(seed, o), x * f, y * f));
    s *= s;
    s *= weight;
    weight = std::clamp(s * 2.0, 0.0, 1.0);
    sum += s * amp;
    norm += amp;
    amp *= gain;
    f *= lacunarity;
  }
  return norm > 0 ? sum / norm : 0.0;
}

double billow2(uint64_t seed, double x, double y, int octaves, double lacunarity, double gain) {
  double sum = 0.0, amp = 1.0, norm = 0.0, f = 1.0;
  for (int o = 0; o < octaves; ++o) {
    sum += amp * std::abs(perlin2(octave_seed(seed, o), x * f, y * f));
    norm += amp;
    amp *= gain;
    f *= lacunarity;
  }
  return norm > 0 ? sum / norm : 0.0;
}

Worley3 worley3(uint64_t seed, double x, double y, double z, double jitter) {
  const int64_t cx = static_cast<int64_t>(std::floor(x));
  const int64_t cy = static_cast<int64_t>(std::floor(y));
  const int64_t cz = static_cast<int64_t>(std::floor(z));
  Worley3 r;
  double best1 = 1e300, best2 = 1e300;
  for (int64_t k = cz - 1; k <= cz + 1; ++k)
    for (int64_t j = cy - 1; j <= cy + 1; ++j)
      for (int64_t i = cx - 1; i <= cx + 1; ++i) {
        const uint64_t h = hash3(seed, i, j, k);
        const double px = static_cast<double>(i) + 0.5 + (to_unit(h) - 0.5) * jitter;
        const double py = static_cast<double>(j) + 0.5 + (to_unit(mix64(h ^ 0x51ED27A3ULL)) - 0.5) * jitter;
        const double pz = static_cast<double>(k) + 0.5 + (to_unit(mix64(h ^ 0xA24BAED4ULL)) - 0.5) * jitter;
        const double d2 = (px - x) * (px - x) + (py - y) * (py - y) + (pz - z) * (pz - z);
        if (d2 < best1) {
          best2 = best1;
          best1 = d2;
          r.cell_hash = h;
          r.px = px; r.py = py; r.pz = pz;
        } else if (d2 < best2) {
          best2 = d2;
        }
      }
  r.f1 = std::sqrt(best1);
  r.f2 = std::sqrt(best2);
  return r;
}

Worley2 worley2(uint64_t seed, double x, double y, double jitter) {
  const int64_t cx = static_cast<int64_t>(std::floor(x));
  const int64_t cy = static_cast<int64_t>(std::floor(y));
  Worley2 r;
  double best1 = 1e300, best2 = 1e300;
  for (int64_t j = cy - 1; j <= cy + 1; ++j)
    for (int64_t i = cx - 1; i <= cx + 1; ++i) {
      const uint64_t h = hash2(seed, i, j);
      const double px = static_cast<double>(i) + 0.5 + (to_unit(h) - 0.5) * jitter;
      const double py = static_cast<double>(j) + 0.5 + (to_unit(mix64(h ^ 0x51ED27A3ULL)) - 0.5) * jitter;
      const double d2 = (px - x) * (px - x) + (py - y) * (py - y);
      if (d2 < best1) {
        best2 = best1;
        best1 = d2;
        r.cell_hash = h;
        r.px = px; r.py = py;
        r.cx = i; r.cy = j;
      } else if (d2 < best2) {
        best2 = d2;
      }
    }
  r.f1 = std::sqrt(best1);
  r.f2 = std::sqrt(best2);
  return r;
}

}  // namespace primeva::noise
