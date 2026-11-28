#include "primeva/macro_map.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <queue>
#include <utility>

#include "primeva/dmath.hpp"
#include "primeva/hash.hpp"
#include "primeva/math.hpp"
#include "primeva/noise.hpp"
#include "primeva/parallel.hpp"

namespace primeva {

namespace {
constexpr float kNoWater = -1e30f;
constexpr double kSecondsPerYear = 31557600.0;
constexpr uint32_t kMagic = 0x4D4D5650;  // "PVMM"
constexpr uint32_t kVersion = 2;
// Peninsula axis direction (NW -> SE in map space: +x east, +z south).
constexpr double kAxisCos = 0.8253356149096783;  // cos(0.6)
constexpr double kAxisSin = 0.5646424733950354;  // sin(0.6)

double trapezoid(double x, double a, double b, double soft) {
  if (x < a) return dmath::exp(-((a - x) / soft) * ((a - x) / soft));
  if (x > b) return dmath::exp(-((x - b) / soft) * ((x - b) / soft));
  return 1.0;
}
}  // namespace

// ---------------------------------------------------------------------------
// Baker: all bake stages operate on the MacroMap's private grids.
// ---------------------------------------------------------------------------
class MacroBaker {
 public:
  MacroBaker(const MacroBakeParams& p, MacroMap& m, void (*progress)(const char*))
      : p_(p), m_(m), progress_(progress) {}

  void run() {
    init();
    stage("continent + relief");
    base_elevation();
    stage("volcanoes");
    volcanoes();
    stage("hydraulic erosion");
    hydraulic_erosion();
    stage("thermal erosion");
    thermal_erosion();
    stage("sea level calibration");
    calibrate_sea_level();
    stage("ocean connectivity");
    ocean_flags();
    stage("distance to coast");
    distance_to_ocean();
    stage("climate");
    climate();
    stage("priority-flood drainage + lakes");
    drainage();
    stage("regions + eras");
    regions_and_eras();
    stage("biomes");
    biomes();
    stage("done");
  }

 private:
  void stage(const char* s) {
    if (progress_) progress_(s);
  }

  void init() {
    m_.res_ = p_.resolution;
    m_.cell_ = p_.world_size_m / p_.resolution;
    m_.seed_ = p_.seed;
    n_ = static_cast<size_t>(m_.res_) * m_.res_;
    m_.elev_.assign(n_, 0.f);
    m_.water_.assign(n_, kNoWater);
    m_.discharge_.assign(n_, 0.f);
    m_.flow_.assign(n_, MacroMap::kNoFlow);
    m_.biome_.assign(n_, 0);
    m_.era_.assign(n_, 0);
    m_.temp_.assign(n_, 0);
    m_.precip_.assign(n_, 0.f);
    m_.volcanic_.assign(n_, 0);
    m_.ocean_.assign(n_, 0);
    belt_.assign(n_, 0.f);
    plain_.assign(n_, 0.f);
    surface_.assign(n_, 0.0);
    dist_ocean_km_.assign(n_, 0.f);
  }

  double cx(int i) const { return (i + 0.5) * m_.cell_; }

  // Continental signal, mountain-belt mask and relief, all pure functions of
  // position so rows can be computed in parallel deterministically.
  void base_elevation() {
    const int res = m_.res_;
    const double size = p_.world_size_m;
    const uint64_t s = p_.seed;
    std::vector<double> cont(n_);
    std::vector<double> relief(n_);
    // Ellipse semi-axes (fractions of the map side) with area = land fraction.
    const double frac = std::clamp(p_.target_land_km2 * 1e6 / (size * size), 0.01, 0.6);
    constexpr double kAspect = 2.3;
    const double axis_b = std::sqrt(frac / (dmath::kPi * kAspect));
    const double axis_a = kAspect * axis_b;
    parallel_for(0, static_cast<size_t>(res), [&](size_t jj) {
      const int j = static_cast<int>(jj);
      for (int i = 0; i < res; ++i) {
        const double x = cx(i), z = cx(j);
        const double cw = p_.continent_wavelength_m;
        const double wx = p_.coast_warp_m * noise::fbm2(s + 11, x / (cw * 0.35), z / (cw * 0.35), 5);
        const double wz = p_.coast_warp_m * noise::fbm2(s + 12, x / (cw * 0.35), z / (cw * 0.35), 5);
        // Continental frame: a bent, elongated ellipse (NW-SE peninsula) whose
        // coastline is broken up by warped fBm into gulfs, capes and islands.
        // The exact land area is fixed afterwards by quantile calibration.
        const double u = x / size - 0.5, v = z / size - 0.5;
        const double cu = (x + wx) / size - 0.5, cv = (z + wz) / size - 0.5;
        const double ur = cu * kAxisCos + cv * kAxisSin;
        const double vr = -cu * kAxisSin + cv * kAxisCos;
        const double vb = vr - 0.055 * dmath::sin(ur / axis_a * dmath::kPi * 1.1);  // sinuous spine
        const double re = std::sqrt((ur / axis_a) * (ur / axis_a) + (vb / axis_b) * (vb / axis_b));
        double c = 0.95 * noise::fbm2(s + 13, (x + wx) / cw, (z + wz) / cw, 9, 2.0, 0.56) + (1.0 - re);
        const double r = std::sqrt(u * u + v * v) * 2.0;
        c -= 1.5 * smoothstep(0.80, 0.99, r);  // ocean margin at the map border
        cont[idx(i, j)] = c;

        // Orogenic belts:
        //  * spine: a longitudinal range running down the peninsula axis;
        //  * arc: a high collisional arc closing the NW end around a plain;
        //  * scattered belts: zero-crossings of a warped low-frequency field.
        const double t_axis = ur / axis_a;
        const double spine = dmath::exp(-((vb - 0.18 * axis_b) / (0.15 * axis_b)) * ((vb - 0.18 * axis_b) / (0.15 * axis_b))) *
                             smoothstep(-0.55, -0.35, t_axis) * (1.0 - smoothstep(0.85, 1.0, t_axis));
        const double arc_cu = -axis_a + 1.15 * axis_b, arc_r = 1.05 * axis_b;
        const double arc_d = std::sqrt((ur - arc_cu) * (ur - arc_cu) + vb * vb);
        const double arc = dmath::exp(-((arc_d - arc_r) / (0.13 * axis_b)) * ((arc_d - arc_r) / (0.13 * axis_b))) *
                           (1.0 - smoothstep(arc_cu - 0.1 * arc_r, arc_cu + 0.45 * arc_r, ur));
        const double plain = (1.0 - smoothstep(0.35 * arc_r, 0.9 * arc_r, arc_d)) * (1.0 - smoothstep(arc_cu, arc_cu + 1.2 * arc_r, ur));
        plain_[idx(i, j)] = static_cast<float>(plain);
        const double bw = p_.mountain_wavelength_m * 3.6;
        const double bfield = noise::fbm2(s + 14, (x + 1.6 * wx) / bw, (z + 1.6 * wz) / bw, 3);
        const double scattered = 0.55 * dmath::pow(std::max(0.0, 1.0 - std::abs(bfield) * 3.2), 2.2);
        const double belt = std::max(std::max(spine * 0.75, arc), scattered);
        belt_[idx(i, j)] = static_cast<float>(belt);
        const double ridges = noise::ridged2(s + 15, x / p_.mountain_wavelength_m, z / p_.mountain_wavelength_m, 10, 2.05, 0.52);
        const double hills = 0.5 + 0.5 * noise::fbm2(s + 16, x / 45000.0, z / 45000.0, 7);
        const double plateau = smoothstep(0.15, 0.45, noise::fbm2(s + 17, x / 260000.0, z / 260000.0, 3));
        const double height = p_.mountain_height_m * (arc > spine * 0.75 && arc > scattered ? 1.25 : 0.8);
        relief[idx(i, j)] = (belt * dmath::pow(ridges, 1.35) * height + hills * p_.hill_height_m * (0.35 + belt) + plateau * 380.0) *
                            (1.0 - 0.85 * plain);
      }
    }, 4);

    // Calibrate the continental threshold so the land fraction matches the
    // requested area exactly (quantile of the continental signal).
    const double land_frac = std::clamp(p_.target_land_km2 * 1e6 / (size * size), 0.01, 0.95);
    std::vector<double> sorted = cont;
    const size_t k = static_cast<size_t>((1.0 - land_frac) * static_cast<double>(n_ - 1));
    std::nth_element(sorted.begin(), sorted.begin() + static_cast<std::ptrdiff_t>(k), sorted.end());
    const double t = sorted[k];

    parallel_for(0, n_, [&](size_t q) {
      const double c = cont[q] - t;
      double e;
      if (c >= 0.0) {
        const double inland = smoothstep(0.0, 0.10, c);
        e = 2.0 + c * 700.0 * (1.0 - 0.8 * plain_[q]) + 45.0 * plain_[q] * inland + relief[q] * inland;
      } else {
        const double d = -c;
        // continental shelf (~ -150 m) then slope to abyssal plain
        e = -1.0 - 150.0 * smoothstep(0.0, 0.035, d) - (p_.max_ocean_depth_m - 150.0) * smoothstep(0.035, 0.30, d);
        e += relief[q] * 0.15 * (1.0 - smoothstep(0.0, 0.08, d));  // islands / seamounts near coasts
      }
      m_.elev_[q] = static_cast<float>(e);
    }, 4096);
  }

  void volcanoes() {
    Rng rng(hash_combine(p_.seed, 0x766F6C63ULL));
    const int res = m_.res_;
    std::vector<Volcano>& vs = m_.volcanoes_;
    const double min_sep = 45000.0;
    for (int attempt = 0; attempt < 20000 && static_cast<int>(vs.size()) < p_.volcano_count; ++attempt) {
      const int i = static_cast<int>(rng.below(static_cast<uint32_t>(res)));
      const int j = static_cast<int>(rng.below(static_cast<uint32_t>(res)));
      const size_t q = idx(i, j);
      if (m_.elev_[q] < 20.f) { continue; }
      // volcanic arcs prefer orogenic belts
      if (rng.uniform() > 0.12 + 0.88 * belt_[q]) continue;
      const double x = cx(i), z = cx(j);
      bool ok = true;
      for (const auto& v : vs)
        if ((v.x_m - x) * (v.x_m - x) + (v.z_m - z) * (v.z_m - z) < min_sep * min_sep) { ok = false; break; }
      if (!ok) continue;
      vs.push_back({x, z, rng.uniform(6000.0, 21000.0), rng.uniform(900.0, 3100.0)});
    }
    const double cell = m_.cell_;
    for (const auto& v : vs) {
      const int r_cells = static_cast<int>(std::ceil(v.radius_m * 3.2 / cell));
      const int ci = static_cast<int>(v.x_m / cell), cj = static_cast<int>(v.z_m / cell);
      for (int j = std::max(0, cj - r_cells); j <= std::min(res - 1, cj + r_cells); ++j)
        for (int i = std::max(0, ci - r_cells); i <= std::min(res - 1, ci + r_cells); ++i) {
          const double dx = cx(i) - v.x_m, dz = cx(j) - v.z_m;
          const double r = std::sqrt(dx * dx + dz * dz) / v.radius_m;
          double h = v.height_m * dmath::exp(-2.6 * r * r);
          const double crater_r = 0.11;
          if (r < crater_r) h -= v.height_m * 0.22 * (1.0 - (r / crater_r) * (r / crater_r));
          const size_t q = idx(i, j);
          m_.elev_[q] += static_cast<float>(h);
          // Lava fields and ash plains are lobate, not circular: warp the radius.
          const double lobes = 1.0 + 0.45 * noise::fbm2(p_.seed + 18, cx(i) / 9000.0, cx(j) / 9000.0, 4);
          const double rw = r / std::max(0.35, lobes);
          const double infl = dmath::exp(-(rw / 2.4) * (rw / 2.4));
          m_.volcanic_[q] = std::max<uint8_t>(m_.volcanic_[q], static_cast<uint8_t>(std::lround(255.0 * infl)));
        }
    }
  }

  // ---- hydraulic erosion (droplet model, Beyer 2015) ----------------------
  // Heights are handled in cell units (metres / cell size) so the transport
  // constants are resolution independent with respect to slope. Droplets that
  // reach the sea drop their sediment: deltas and coastal plains form.
  void hydraulic_erosion() {
    const int res = m_.res_;
    const double inv_cell = 1.0 / m_.cell_;
    std::vector<double> h(n_);
    for (size_t q = 0; q < n_; ++q) h[q] = m_.elev_[q] * inv_cell;

    // erosion brush
    struct Tap { int di, dj; double w; };
    std::vector<Tap> brush;
    const int R = p_.erosion_radius;
    double wsum = 0.0;
    for (int dj = -R; dj <= R; ++dj)
      for (int di = -R; di <= R; ++di) {
        const double d = std::sqrt(static_cast<double>(di * di + dj * dj));
        if (d <= R) {
          const double w = std::max(0.0, R + 0.5 - d);
          brush.push_back({di, dj, w});
          wsum += w;
        }
      }
    for (auto& t : brush) t.w /= wsum;

    auto height_grad = [&](double px, double pz, double& gx, double& gz) {
      const int i = static_cast<int>(px), j = static_cast<int>(pz);
      const double u = px - i, v = pz - j;
      const double h00 = h[idx(i, j)], h10 = h[idx(i + 1, j)], h01 = h[idx(i, j + 1)], h11 = h[idx(i + 1, j + 1)];
      gx = (h10 - h00) * (1 - v) + (h11 - h01) * v;
      gz = (h01 - h00) * (1 - u) + (h11 - h10) * u;
      return h00 * (1 - u) * (1 - v) + h10 * u * (1 - v) + h01 * (1 - u) * v + h11 * u * v;
    };

    Rng rng(hash_combine(p_.seed, 0x65726F64ULL));
    const size_t droplets = static_cast<size_t>(p_.erosion_droplets_per_cell * static_cast<double>(n_));
    const double sea = 0.0;
    for (size_t d = 0; d < droplets; ++d) {
      double px = rng.uniform(0.0, res - 1.001), pz = rng.uniform(0.0, res - 1.001);
      if (h[idx(static_cast<int>(px), static_cast<int>(pz))] <= sea) continue;
      double dx = 0, dz = 0, speed = 1, water = 1, sediment = 0;
      for (int step = 0; step < p_.erosion_max_steps; ++step) {
        const int ni = static_cast<int>(px), nj = static_cast<int>(pz);
        const double u = px - ni, v = pz - nj;
        double gx, gz;
        const double hc = height_grad(px, pz, gx, gz);
        dx = dx * p_.erosion_inertia - gx * (1 - p_.erosion_inertia);
        dz = dz * p_.erosion_inertia - gz * (1 - p_.erosion_inertia);
        const double len = std::sqrt(dx * dx + dz * dz);
        if (len < 1e-12) {
          const double a = rng.uniform(0.0, dmath::kTwoPi);
          dx = dmath::cos(a); dz = dmath::sin(a);
        } else {
          dx /= len; dz /= len;
        }
        const double nx = px + dx, nz = pz + dz;
        if (nx < 0 || nz < 0 || nx >= res - 1.001 || nz >= res - 1.001) break;
        double tgx, tgz;
        const double hn = height_grad(nx, nz, tgx, tgz);
        const double dh = hn - hc;

        auto deposit_at = [&](double amount) {
          h[idx(ni, nj)] += amount * (1 - u) * (1 - v);
          h[idx(ni + 1, nj)] += amount * u * (1 - v);
          h[idx(ni, nj + 1)] += amount * (1 - u) * v;
          h[idx(ni + 1, nj + 1)] += amount * u * v;
        };

        if (hn <= sea) {  // reached the sea: build a delta
          deposit_at(sediment);
          sediment = 0;
          break;
        }
        const double capacity = std::max(-dh, p_.erosion_min_slope) * speed * water * p_.erosion_capacity;
        if (sediment > capacity || dh > 0) {
          const double amount = dh > 0 ? std::min(dh, sediment) : (sediment - capacity) * p_.erosion_deposition;
          sediment -= amount;
          deposit_at(amount);
        } else {
          const double amount = std::min((capacity - sediment) * p_.erosion_erosion, -dh);
          for (const auto& t : brush) {
            const int bi = ni + t.di, bj = nj + t.dj;
            if (bi < 0 || bj < 0 || bi >= res || bj >= res) continue;
            h[idx(bi, bj)] -= amount * t.w;
          }
          sediment += amount;
        }
        speed = std::sqrt(std::max(0.0, speed * speed - dh * p_.erosion_gravity));
        water *= (1 - p_.erosion_evaporation);
        px = nx; pz = nz;
      }
    }
    for (size_t q = 0; q < n_; ++q) m_.elev_[q] = static_cast<float>(h[q] * m_.cell_);
  }

  // Jacobi-style talus relaxation (order independent, hence deterministic).
  void thermal_erosion() {
    const int res = m_.res_;
    const double talus = std::tan(p_.thermal_talus_deg * dmath::kPi / 180.0) * m_.cell_;
    std::vector<float> delta(n_);
    for (int it = 0; it < p_.thermal_iterations; ++it) {
      std::fill(delta.begin(), delta.end(), 0.f);
      parallel_for(0, static_cast<size_t>(res), [&](size_t jj) {
        const int j = static_cast<int>(jj);
        for (int i = 0; i < res; ++i) {
          const size_t q = idx(i, j);
          const double hc = m_.elev_[q];
          double out = 0.0;
          for (int k = 0; k < 8; ++k) {
            const int ni = i + MacroMap::kDx[k], nj = j + MacroMap::kDz[k];
            if (ni < 0 || nj < 0 || ni >= res || nj >= res) continue;
            const double dist = (k & 1) ? 1.41421356237 : 1.0;
            const double diff = hc - m_.elev_[idx(ni, nj)];
            if (diff > talus * dist) out -= 0.125 * 0.5 * (diff - talus * dist);
            const double back = m_.elev_[idx(ni, nj)] - hc;
            if (back > talus * dist) out += 0.125 * 0.5 * (back - talus * dist);
          }
          delta[q] = static_cast<float>(out);
        }
      }, 8);
      for (size_t q = 0; q < n_; ++q) m_.elev_[q] += delta[q];
    }
  }

  // Sea level is chosen so that the area NOT connected to the ocean (land
  // plus inland lakes/depressions) equals the target exactly: quantile first
  // guess, then bisection on the connectivity-aware land area.
  void calibrate_sea_level() {
    const double size = p_.world_size_m;
    const double land_frac = std::clamp(p_.target_land_km2 * 1e6 / (size * size), 0.01, 0.95);
    std::vector<float> sorted = m_.elev_;
    const size_t k = static_cast<size_t>((1.0 - land_frac) * static_cast<double>(n_ - 1));
    std::nth_element(sorted.begin(), sorted.begin() + static_cast<std::ptrdiff_t>(k), sorted.end());
    const float shift = sorted[k];
    for (auto& e : m_.elev_) e -= shift;
    const std::vector<float> base = m_.elev_;
    const size_t target_cells = static_cast<size_t>(land_frac * static_cast<double>(n_) + 0.5);
    double lo = -400.0, hi = 400.0;  // candidate additional sea-level rise (m)
    auto land_cells = [&](double rise) {
      for (size_t q = 0; q < n_; ++q) m_.elev_[q] = static_cast<float>(base[q] - rise);
      ocean_flags();
      size_t land = 0;
      for (uint8_t o : m_.ocean_) land += o ? 0 : 1;
      return land;
    };
    for (int it = 0; it < 24; ++it) {
      const double mid = 0.5 * (lo + hi);
      if (land_cells(mid) > target_cells) lo = mid; else hi = mid;
    }
    land_cells(0.5 * (lo + hi));
  }

  // Ocean = below sea level AND connected to the map border.
  void ocean_flags() {
    const int res = m_.res_;
    std::fill(m_.ocean_.begin(), m_.ocean_.end(), 0);
    std::vector<uint32_t> stack;
    auto push = [&](int i, int j) {
      const size_t q = idx(i, j);
      if (m_.ocean_[q] || m_.elev_[q] >= 0.f) return;
      m_.ocean_[q] = 1;
      stack.push_back(static_cast<uint32_t>(q));
    };
    for (int i = 0; i < res; ++i) { push(i, 0); push(i, res - 1); push(0, i); push(res - 1, i); }
    while (!stack.empty()) {
      const uint32_t q = stack.back();
      stack.pop_back();
      const int i = static_cast<int>(q % res), j = static_cast<int>(q / res);
      for (int k = 0; k < 8; ++k) {
        const int ni = i + MacroMap::kDx[k], nj = j + MacroMap::kDz[k];
        if (ni >= 0 && nj >= 0 && ni < res && nj < res) push(ni, nj);
      }
    }
  }

  // Two-pass chamfer distance transform (exact enough, O(N), deterministic).
  void distance_to_ocean() {
    const int res = m_.res_;
    const float inf = 1e30f;
    std::vector<float>& d = dist_ocean_km_;
    for (size_t q = 0; q < n_; ++q) d[q] = m_.ocean_[q] ? 0.f : inf;
    const float a = static_cast<float>(m_.cell_ / 1000.0), b = a * 1.41421356f;
    for (int j = 0; j < res; ++j)
      for (int i = 0; i < res; ++i) {
        float& v = d[idx(i, j)];
        if (i > 0) v = std::min(v, d[idx(i - 1, j)] + a);
        if (j > 0) v = std::min(v, d[idx(i, j - 1)] + a);
        if (i > 0 && j > 0) v = std::min(v, d[idx(i - 1, j - 1)] + b);
        if (i < res - 1 && j > 0) v = std::min(v, d[idx(i + 1, j - 1)] + b);
      }
    for (int j = res - 1; j >= 0; --j)
      for (int i = res - 1; i >= 0; --i) {
        float& v = d[idx(i, j)];
        if (i < res - 1) v = std::min(v, d[idx(i + 1, j)] + a);
        if (j < res - 1) v = std::min(v, d[idx(i, j + 1)] + a);
        if (i < res - 1 && j < res - 1) v = std::min(v, d[idx(i + 1, j + 1)] + b);
        if (i > 0 && j < res - 1) v = std::min(v, d[idx(i - 1, j + 1)] + b);
      }
  }

  // Temperature: latitude gradient + lapse rate. Precipitation: westerly
  // moisture transport sweep with orographic lift (rain on windward slopes)
  // and depletion (rain shadow on leeward slopes), then smoothed.
  void climate() {
    const int res = m_.res_;
    const uint64_t s = p_.seed;
    const double cell_km = m_.cell_ / 1000.0;
    std::vector<float> rain(n_, 0.f);
    parallel_for(0, static_cast<size_t>(res), [&](size_t jj) {
      const int j = static_cast<int>(jj);
      const double lat = (j + 0.5) / res;  // 0 north .. 1 south
      const double t_sea = lerp(p_.sea_temp_north_c, p_.sea_temp_south_c, lat);
      const double medit = 1.15 - 0.45 * lat;  // drier south
      double moisture = 1.0;
      for (int i = 0; i < res; ++i) {
        const size_t q = idx(i, j);
        const double e = m_.elev_[q];
        const double x = cx(i), z = cx(j);
        const double t = t_sea - p_.lapse_rate_c_per_m * std::max(0.0, e) + 1.3 * noise::fbm2(s + 31, x / 300000.0, z / 300000.0, 3);
        m_.temp_[q] = static_cast<int16_t>(std::lround(std::clamp(t, -60.0, 60.0) * 100.0));
        if (m_.ocean_[q]) {
          moisture = std::min(1.0, moisture + 0.03 * cell_km);
          rain[q] = static_cast<float>(700.0 * medit);
          continue;
        }
        const double prev = i > 0 ? std::max(0.0, static_cast<double>(m_.elev_[q - 1])) : 0.0;
        const double lift = std::max(0.0, std::max(0.0, e) - prev) / m_.cell_;
        double r = moisture * (820.0 + 26000.0 * lift) * medit;
        r = std::clamp(r, 90.0, 4200.0);
        moisture = std::clamp(moisture - r * cell_km * 1.5e-6 + 0.00055 * cell_km, 0.05, 1.0);
        rain[q] = static_cast<float>(r);
      }
    }, 4);
    // separable box blur, radius ~ 12 km
    const int rad = std::max(1, static_cast<int>(12000.0 / m_.cell_));
    std::vector<float> tmp(n_);
    for (int pass = 0; pass < 2; ++pass) {
      const bool horiz = pass == 0;
      const std::vector<float>& src = horiz ? rain : tmp;
      std::vector<float>& dst = horiz ? tmp : m_.precip_;
      parallel_for(0, static_cast<size_t>(res), [&](size_t ll) {
        const int l = static_cast<int>(ll);
        double acc = 0;
        int cnt = 0;
        auto at = [&](int k) { return horiz ? src[idx(k, l)] : src[idx(l, k)]; };
        for (int k = 0; k <= std::min(rad, res - 1); ++k) { acc += at(k); ++cnt; }
        for (int k = 0; k < res; ++k) {
          const size_t q = horiz ? idx(k, l) : idx(l, k);
          dst[q] = static_cast<float>(acc / cnt);
          const int add = k + rad + 1, rem = k - rad;
          if (add < res) { acc += at(add); ++cnt; }
          if (rem >= 0) { acc -= at(rem); --cnt; }
        }
      }, 4);
    }
    parallel_for(0, n_, [&](size_t q) {
      const int i = static_cast<int>(q % res), j = static_cast<int>(q / res);
      const double f = 1.0 + 0.18 * noise::fbm2(s + 32, cx(i) / 150000.0, cx(j) / 150000.0, 4);
      m_.precip_[q] = static_cast<float>(std::max(60.0, m_.precip_[q] * f));
    }, 4096);
  }

  // Priority-Flood (Barnes et al. 2014) seeded from the ocean and the map
  // border. Each cell's flow target is the cell that discovered it, which
  // yields a valid drainage graph across flats and filled depressions without
  // epsilon gradients. Lakes are where the filled surface exceeds the terrain.
  // Discharge = sum of upstream runoff (precip * runoff coefficient).
  void drainage() {
    const int res = m_.res_;
    using Item = std::pair<double, uint32_t>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> pq;
    std::vector<uint8_t> seen(n_, 0);
    std::vector<uint32_t> order;
    order.reserve(n_);
    for (size_t q = 0; q < n_; ++q) {
      const int i = static_cast<int>(q % res), j = static_cast<int>(q / res);
      const bool border = i == 0 || j == 0 || i == res - 1 || j == res - 1;
      if (m_.ocean_[q] || border) {
        seen[q] = 1;
        surface_[q] = m_.ocean_[q] ? 0.0 : m_.elev_[q];
        pq.push({surface_[q], static_cast<uint32_t>(q)});
      }
    }
    while (!pq.empty()) {
      const auto [f, q] = pq.top();
      pq.pop();
      order.push_back(q);
      const int i = static_cast<int>(q % res), j = static_cast<int>(q / res);
      for (int k = 0; k < 8; ++k) {
        const int ni = i + MacroMap::kDx[k], nj = j + MacroMap::kDz[k];
        if (ni < 0 || nj < 0 || ni >= res || nj >= res) continue;
        const size_t nq = idx(ni, nj);
        if (seen[nq]) continue;
        seen[nq] = 1;
        surface_[nq] = std::max<double>(m_.elev_[nq], f);
        m_.flow_[nq] = static_cast<uint8_t>((k + 4) & 7);  // points back to discoverer
        pq.push({surface_[nq], static_cast<uint32_t>(nq)});
      }
    }
    const double cell_area = m_.cell_ * m_.cell_;
    std::vector<double> q_acc(n_, 0.0);
    for (size_t q = 0; q < n_; ++q)
      if (!m_.ocean_[q]) q_acc[q] = m_.precip_[q] * 0.001 * cell_area * p_.runoff_coefficient / kSecondsPerYear;
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
      const uint32_t q = *it;
      const uint8_t d = m_.flow_[q];
      if (d == MacroMap::kNoFlow) continue;
      const int i = static_cast<int>(q % res) + MacroMap::kDx[d], j = static_cast<int>(q / res) + MacroMap::kDz[d];
      q_acc[idx(i, j)] += q_acc[q];
    }
    for (size_t q = 0; q < n_; ++q) {
      m_.discharge_[q] = m_.ocean_[q] ? 0.f : static_cast<float>(q_acc[q]);
      if (m_.ocean_[q]) m_.water_[q] = 0.f;
      else if (surface_[q] - m_.elev_[q] > 2.5) m_.water_[q] = static_cast<float>(surface_[q]);
    }
    m_.surface_ = std::vector<float>(surface_.begin(), surface_.end());
  }

  // Temporal refugia: domain-warped Voronoi regions, each assigned the era
  // whose palaeoclimate best fits the region's present climate, with a
  // guaranteed minimum share per era.
  void regions_and_eras() {
    const int res = m_.res_;
    const uint64_t s = p_.seed;
    const double rs = p_.region_size_m;
    std::vector<uint64_t> key(n_);
    parallel_for(0, static_cast<size_t>(res), [&](size_t jj) {
      const int j = static_cast<int>(jj);
      for (int i = 0; i < res; ++i) {
        const double x = cx(i), z = cx(j);
        const double wx = 0.42 * rs * noise::fbm2(s + 41, x / (rs * 0.8), z / (rs * 0.8), 4);
        const double wz = 0.42 * rs * noise::fbm2(s + 42, x / (rs * 0.8), z / (rs * 0.8), 4);
        const auto w = noise::worley2(s + 43, (x + wx) / rs, (z + wz) / rs, 0.85);
        key[idx(i, j)] = (static_cast<uint64_t>(static_cast<uint32_t>(w.cx)) << 32) | static_cast<uint32_t>(w.cy);
      }
    }, 4);
    struct Stats { double area = 0, t = 0, p = 0, e = 0, volc = 0, coast = 0; uint64_t hash = 0; };
    std::map<uint64_t, Stats> stats;
    for (size_t q = 0; q < n_; ++q) {
      if (m_.ocean_[q]) continue;
      auto& st = stats[key[q]];
      st.area += 1;
      st.t += m_.temp_[q] * 0.01;
      st.p += m_.precip_[q];
      st.e += m_.elev_[q];
      st.volc += m_.volcanic_[q] / 255.0;
      st.coast += dist_ocean_km_[q] < 8.f ? 1 : 0;
    }
    std::vector<uint64_t> keys;
    std::vector<std::array<double, kEraCount>> score;
    for (auto& [k, st] : stats) {
      st.t /= st.area; st.p /= st.area; st.e /= st.area; st.volc /= st.area; st.coast /= st.area;
      st.hash = hash_combine(s + 44, k);
      std::array<double, kEraCount> sc{};
      const double lowland = 1.0 - smoothstep(200.0, 900.0, st.e);
      sc[static_cast<int>(Era::Carboniferous)] = trapezoid(st.t, 13, 24, 4) * trapezoid(st.p, 1100, 3500, 350) * (0.3 + 0.7 * lowland);
      sc[static_cast<int>(Era::Permian)] = trapezoid(st.t, 12, 30, 4) * trapezoid(st.p, 0, 650, 200);
      sc[static_cast<int>(Era::Triassic)] = trapezoid(st.t, 11, 26, 4) * trapezoid(st.p, 400, 950, 220);
      sc[static_cast<int>(Era::Jurassic)] = trapezoid(st.t, 12, 26, 4) * trapezoid(st.p, 800, 1900, 300) * (0.6 + 0.6 * st.coast);
      sc[static_cast<int>(Era::Cretaceous)] = trapezoid(st.t, 12, 28, 4) * trapezoid(st.p, 900, 2600, 350) + 1.6 * st.volc;
      sc[static_cast<int>(Era::Paleogene)] = trapezoid(st.t, 16, 32, 3) * trapezoid(st.p, 1500, 4500, 350) * (0.4 + 0.6 * lowland);
      sc[static_cast<int>(Era::Neogene)] = trapezoid(st.t, 11, 24, 4) * trapezoid(st.p, 350, 1000, 220);
      sc[static_cast<int>(Era::Pleistocene)] = trapezoid(st.t, -30, 8, 3) + smoothstep(900.0, 1800.0, st.e);
      for (int e = 0; e < kEraCount; ++e) sc[e] += 0.22 * to_unit(mix64(st.hash + static_cast<uint64_t>(e)));
      keys.push_back(k);
      score.push_back(sc);
    }
    const size_t nr = keys.size();
    std::vector<int> assigned(nr, 0);
    std::vector<double> area(nr, 0.0);
    std::array<double, kEraCount> era_area{};
    double land = 0.0;
    for (size_t r = 0; r < nr; ++r) {
      area[r] = stats[keys[r]].area;
      land += area[r];
      assigned[r] = static_cast<int>(std::max_element(score[r].begin(), score[r].end()) - score[r].begin());
      era_area[assigned[r]] += area[r];
    }
    // Every era must hold at least `min_share` of the land: repeatedly give the
    // most under-represented era the region whose climate fits it best relative
    // to its current assignment, taking only from eras that stay above the floor.
    const double min_share = 0.07;
    for (int guard = 0; guard < static_cast<int>(nr) * 4; ++guard) {
      int need = -1;
      for (int e = 0; e < kEraCount; ++e)
        if (era_area[e] < min_share * land && (need < 0 || era_area[e] < era_area[need])) need = e;
      if (need < 0) break;
      double best = -1e300;
      size_t pick = nr;
      for (size_t r = 0; r < nr; ++r) {
        const int cur = assigned[r];
        if (cur == need || era_area[cur] - area[r] < min_share * land) continue;
        // prefer good climatic fit, and regions not much larger than the deficit
        const double deficit = min_share * land - era_area[need];
        const double size_pen = 0.15 * std::abs(area[r] - deficit) / std::max(deficit, 1.0);
        const double gain = score[r][need] - score[r][cur] - size_pen;
        if (gain > best) { best = gain; pick = r; }
      }
      if (pick == nr) break;
      era_area[assigned[pick]] -= area[pick];
      assigned[pick] = need;
      era_area[need] += area[pick];
    }
    std::map<uint64_t, uint8_t> era_of;
    for (size_t r = 0; r < nr; ++r) era_of[keys[r]] = static_cast<uint8_t>(assigned[r]);
    for (size_t q = 0; q < n_; ++q) {
      auto it = era_of.find(key[q]);
      m_.era_[q] = it != era_of.end() ? it->second : static_cast<uint8_t>(Era::Cretaceous);
    }
  }

  void biomes() {
    const int res = m_.res_;
    parallel_for(0, static_cast<size_t>(res), [&](size_t jj) {
      const int j = static_cast<int>(jj);
      for (int i = 0; i < res; ++i) {
        const size_t q = idx(i, j);
        const double e = m_.elev_[q];
        Biome b;
        if (m_.ocean_[q]) {
          b = (-e < 160.0) ? Biome::ShallowReefSea : Biome::OpenOceanPelagic;
          m_.era_[q] = static_cast<uint8_t>(biome_def(b).era);
          m_.biome_[q] = static_cast<uint8_t>(b);
          continue;
        }
        const double gx = (m_.elev_[idx(std::min(i + 1, res - 1), j)] - m_.elev_[idx(std::max(i - 1, 0), j)]) / (2 * m_.cell_);
        const double gz = (m_.elev_[idx(i, std::min(j + 1, res - 1))] - m_.elev_[idx(i, std::max(j - 1, 0))]) / (2 * m_.cell_);
        const double slope = std::sqrt(gx * gx + gz * gz);
        const double t = m_.temp_[q] * 0.01;
        const double p = m_.precip_[q];
        const double coast = dist_ocean_km_[q];
        const double qd = m_.discharge_[q];
        const bool lake = m_.water_[q] > kNoWater * 0.5f;
        const double volc = m_.volcanic_[q] / 255.0;
        switch (static_cast<Era>(m_.era_[q])) {
          case Era::Carboniferous:
            b = ((e < 80 && slope < 0.025) || lake || qd > 60) ? Biome::CarboniferousCoalSwamp : Biome::CarboniferousGiantFernForest;
            break;
          case Era::Permian:
            b = (lake || (slope < 0.012 && p < 500)) ? Biome::PermianSaltFlats : Biome::PermianRedDesert;
            break;
          case Era::Triassic:
            b = (lake || qd > 40) ? Biome::TriassicRiftLakes : Biome::TriassicConiferBadlands;
            break;
          case Era::Jurassic:
            if (coast < 6.0 && e < 45) b = Biome::JurassicLagoonArchipelago;
            else if (p > 1150 || slope > 0.07) b = Biome::JurassicAraucariaForest;
            else b = Biome::JurassicFernPrairie;
            break;
          case Era::Cretaceous:
            if (volc > 0.35 || e > 950) b = Biome::CretaceousVolcanicHighlands;
            else if (coast < 5.0 && slope > 0.025) b = Biome::CretaceousChalkCoast;
            else if (qd > 90 || (e < 60 && coast < 25)) b = Biome::CretaceousFloodplainDelta;
            else b = Biome::CretaceousAngiospermForest;
            break;
          case Era::Paleogene: b = Biome::PaleogeneTropicalRainforest; break;
          case Era::Neogene: b = Biome::NeogeneSavanna; break;
          case Era::Pleistocene:
          default:
            b = (e > 1300 || t < 1.0) ? Biome::PleistoceneGlacialAlps : Biome::PleistoceneMammothSteppe;
            break;
        }
        // Physical override: permanent ice above the snow line in any refugium.
        if (t < -1.5) {
          b = Biome::PleistoceneGlacialAlps;
        }
        m_.biome_[q] = static_cast<uint8_t>(b);
      }
    }, 4);
  }

  size_t idx(int i, int j) const { return static_cast<size_t>(j) * m_.res_ + i; }

  const MacroBakeParams& p_;
  MacroMap& m_;
  void (*progress_)(const char*);
  size_t n_ = 0;
  std::vector<float> belt_;
  std::vector<float> plain_;
  std::vector<double> surface_;
  std::vector<float> dist_ocean_km_;
};

// ---------------------------------------------------------------------------
// MacroMap public API
// ---------------------------------------------------------------------------
MacroMap MacroMap::bake(const MacroBakeParams& p, void (*progress)(const char*)) {
  MacroMap m;
  MacroBaker(p, m, progress).run();
  return m;
}

bool MacroMap::is_lake(int i, int j) const {
  const size_t q = idx(clampi(i), clampi(j));
  return !ocean_[q] && water_[q] > kNoWater * 0.5f;
}

namespace {
inline double catmull_rom(double p0, double p1, double p2, double p3, double t) {
  return p1 + 0.5 * t * (p2 - p0 + t * (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3 + t * (3.0 * (p1 - p2) + p3 - p0)));
}
}  // namespace

double MacroMap::sample_elevation(double x_m, double z_m) const {
  const double gx = x_m / cell_ - 0.5, gz = z_m / cell_ - 0.5;
  const int i0 = static_cast<int>(std::floor(gx)), j0 = static_cast<int>(std::floor(gz));
  const double tx = gx - i0, tz = gz - j0;
  double rows[4];
  for (int r = 0; r < 4; ++r) {
    const int j = j0 - 1 + r;
    rows[r] = catmull_rom(elevation(i0 - 1, j), elevation(i0, j), elevation(i0 + 1, j), elevation(i0 + 2, j), tx);
  }
  return catmull_rom(rows[0], rows[1], rows[2], rows[3], tz);
}

MacroMap::BiomeWeights MacroMap::sample_biomes(double x_m, double z_m) const {
  const double gx = x_m / cell_ - 0.5, gz = z_m / cell_ - 0.5;
  const int i0 = static_cast<int>(std::floor(gx)), j0 = static_cast<int>(std::floor(gz));
  const double tx = gx - i0, tz = gz - j0;
  const Biome bs[4] = {biome(i0, j0), biome(i0 + 1, j0), biome(i0, j0 + 1), biome(i0 + 1, j0 + 1)};
  const double ws[4] = {(1 - tx) * (1 - tz), tx * (1 - tz), (1 - tx) * tz, tx * tz};
  BiomeWeights out;
  for (int k = 0; k < 4; ++k) {
    int f = -1;
    for (int m = 0; m < out.count; ++m)
      if (out.biome[m] == bs[k]) { f = m; break; }
    if (f < 0) { f = out.count++; out.biome[f] = bs[k]; out.weight[f] = 0; }
    out.weight[f] += ws[k];
  }
  return out;
}

namespace {
template <typename F>
double bilinear(double x_m, double z_m, double cell, F&& at) {
  const double gx = x_m / cell - 0.5, gz = z_m / cell - 0.5;
  const int i0 = static_cast<int>(std::floor(gx)), j0 = static_cast<int>(std::floor(gz));
  const double tx = gx - i0, tz = gz - j0;
  return (at(i0, j0) * (1 - tx) + at(i0 + 1, j0) * tx) * (1 - tz) + (at(i0, j0 + 1) * (1 - tx) + at(i0 + 1, j0 + 1) * tx) * tz;
}
}  // namespace

double MacroMap::sample_volcanic(double x_m, double z_m) const {
  return bilinear(x_m, z_m, cell_, [this](int i, int j) { return static_cast<double>(volcanic(i, j)); });
}
double MacroMap::sample_precip(double x_m, double z_m) const {
  return bilinear(x_m, z_m, cell_, [this](int i, int j) { return static_cast<double>(precipitation_mm(i, j)); });
}
double MacroMap::sample_temperature(double x_m, double z_m) const {
  return bilinear(x_m, z_m, cell_, [this](int i, int j) { return static_cast<double>(temperature_c(i, j)); });
}

MacroMap::StandingWater MacroMap::sample_standing_water(double x_m, double z_m) const {
  const double gx = x_m / cell_ - 0.5, gz = z_m / cell_ - 0.5;
  const int i0 = static_cast<int>(std::floor(gx)), j0 = static_cast<int>(std::floor(gz));
  const double tx = gx - i0, tz = gz - j0;
  const int ci[4] = {i0, i0 + 1, i0, i0 + 1}, cj[4] = {j0, j0, j0 + 1, j0 + 1};
  const double w[4] = {(1 - tx) * (1 - tz), tx * (1 - tz), (1 - tx) * tz, tx * tz};
  StandingWater out;
  double lw = 0.0, lsum = 0.0;
  for (int k = 0; k < 4; ++k) {
    const size_t q = idx(clampi(ci[k]), clampi(cj[k]));
    const bool ocean = ocean_[q] != 0;
    const bool lake = !ocean && water_[q] > kNoWater * 0.5f;
    if (!ocean && !lake) continue;
    out.fraction += w[k];
    lsum += w[k] * (ocean ? 0.0 : static_cast<double>(water_[q]));
    lw += w[k];
  }
  if (lw > 0.0) out.level = lsum / lw;
  return out;
}

MacroMap::RiverSample MacroMap::sample_river(double x_m, double z_m) const {
  RiverSample out;
  constexpr double kQmin = 4.0;
  // Meander: smooth domain warp of the query point bends the straight D8
  // segments into continuous curves.
  const double px = x_m + 0.22 * cell_ * noise::fbm2(seed_ + 51, x_m / 1500.0, z_m / 1500.0, 3);
  const double pz = z_m + 0.22 * cell_ * noise::fbm2(seed_ + 52, x_m / 1500.0, z_m / 1500.0, 3);
  const int gi = static_cast<int>(std::floor(px / cell_)), gj = static_cast<int>(std::floor(pz / cell_));
  double best_metric = 1e300;
  for (int dj = -2; dj <= 2; ++dj)
    for (int di = -2; di <= 2; ++di) {
      const int ki = clampi(gi + di), kj = clampi(gj + dj);
      const size_t kq = idx(ki, kj);
      const double qk = discharge_[kq];
      if (qk < kQmin || flow_[kq] == kNoFlow || ocean_[kq]) continue;
      if (water_[kq] > kNoWater * 0.5f) continue;  // inside a lake
      const int di_ = ki + kDx[flow_[kq]], dj_ = kj + kDz[flow_[kq]];
      const size_t dq = idx(clampi(di_), clampi(dj_));
      const double ax = (ki + 0.5) * cell_, az = (kj + 0.5) * cell_;
      const double bx = (di_ + 0.5) * cell_, bz = (dj_ + 0.5) * cell_;
      const double vx = bx - ax, vz = bz - az;
      const double t = std::clamp(((px - ax) * vx + (pz - az) * vz) / (vx * vx + vz * vz), 0.0, 1.0);
      const double ex = px - (ax + t * vx), ez = pz - (az + t * vz);
      const double dist = std::sqrt(ex * ex + ez * ez);
      const double qd = ocean_[dq] ? qk : std::max<double>(qk, discharge_[dq]);
      const double qt = qk + (qd - qk) * t;
      const double ramp = smoothstep(kQmin, 3.0 * kQmin, qt);
      const double half = 0.5 * 4.0 * std::sqrt(qt) * ramp + 0.5;
      const double depth = 0.32 * dmath::pow(qt, 0.38) * ramp;
      const double bank = std::max(6.0, half * 1.5);
      if (dist > half + bank) continue;
      const double metric = dist - half;
      if (metric >= best_metric) continue;
      best_metric = metric;
      const double sk = surface_[kq];
      const double sd = ocean_[dq] ? 0.0 : static_cast<double>(surface_[dq]);
      out.in_influence = true;
      out.distance_m = dist;
      out.half_width_m = half;
      out.depth_m = depth;
      out.discharge_m3s = qt;
      out.surface_m = sk + (sd - sk) * t - 0.35;
    }
  return out;
}

double MacroMap::land_area_km2() const {
  size_t land = 0;
  for (uint8_t o : ocean_) land += o ? 0 : 1;
  return static_cast<double>(land) * cell_ * cell_ * 1e-6;
}

std::vector<double> MacroMap::biome_area_km2() const {
  std::vector<double> a(kBiomeCount, 0.0);
  for (uint8_t b : biome_) a[b] += cell_ * cell_ * 1e-6;
  return a;
}

std::vector<double> MacroMap::era_area_km2() const {
  std::vector<double> a(kEraCount, 0.0);
  for (size_t q = 0; q < era_.size(); ++q)
    if (!ocean_[q]) a[era_[q]] += cell_ * cell_ * 1e-6;
  return a;
}

namespace {
template <typename T>
void write_vec(std::ofstream& f, const std::vector<T>& v) {
  f.write(reinterpret_cast<const char*>(v.data()), static_cast<std::streamsize>(v.size() * sizeof(T)));
}
template <typename T>
bool read_vec(std::ifstream& f, std::vector<T>& v, size_t n) {
  v.resize(n);
  f.read(reinterpret_cast<char*>(v.data()), static_cast<std::streamsize>(n * sizeof(T)));
  return static_cast<bool>(f);
}
template <typename T>
void write_pod(std::ofstream& f, const T& v) { f.write(reinterpret_cast<const char*>(&v), sizeof(T)); }
template <typename T>
bool read_pod(std::ifstream& f, T& v) { f.read(reinterpret_cast<char*>(&v), sizeof(T)); return static_cast<bool>(f); }
}  // namespace

bool MacroMap::save(const std::string& path) const {
  std::ofstream f(path, std::ios::binary | std::ios::trunc);
  if (!f) return false;
  write_pod(f, kMagic);
  write_pod(f, kVersion);
  write_pod(f, static_cast<int32_t>(res_));
  write_pod(f, cell_);
  write_pod(f, seed_);
  write_pod(f, static_cast<uint32_t>(volcanoes_.size()));
  for (const auto& v : volcanoes_) write_pod(f, v);
  write_vec(f, elev_);
  write_vec(f, water_);
  write_vec(f, surface_);
  write_vec(f, discharge_);
  write_vec(f, flow_);
  write_vec(f, biome_);
  write_vec(f, era_);
  write_vec(f, temp_);
  write_vec(f, precip_);
  write_vec(f, volcanic_);
  write_vec(f, ocean_);
  return static_cast<bool>(f);
}

bool MacroMap::load(const std::string& path, MacroMap& m) {
  std::ifstream f(path, std::ios::binary);
  if (!f) return false;
  uint32_t magic = 0, version = 0, nv = 0;
  int32_t res = 0;
  if (!read_pod(f, magic) || magic != kMagic || !read_pod(f, version) || version != kVersion) return false;
  if (!read_pod(f, res) || res <= 0 || res > 65536 || !read_pod(f, m.cell_) || !read_pod(f, m.seed_) || !read_pod(f, nv)) return false;
  m.res_ = res;
  m.volcanoes_.resize(nv);
  for (auto& v : m.volcanoes_)
    if (!read_pod(f, v)) return false;
  const size_t n = static_cast<size_t>(res) * res;
  return read_vec(f, m.elev_, n) && read_vec(f, m.water_, n) && read_vec(f, m.surface_, n) && read_vec(f, m.discharge_, n) &&
         read_vec(f, m.flow_, n) && read_vec(f, m.biome_, n) && read_vec(f, m.era_, n) && read_vec(f, m.temp_, n) &&
         read_vec(f, m.precip_, n) && read_vec(f, m.volcanic_, n) && read_vec(f, m.ocean_, n);
}

}  // namespace primeva
