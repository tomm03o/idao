#pragma once

#include <cstdint>

namespace primeva::noise {

// Seeded gradient (Perlin-style) noise with quintic interpolation.
// Inputs are doubles split into an int64 lattice cell + fractional part, so
// precision is preserved at continental coordinates (1e6 m * 8 voxels/m).
// Output is normalised to approximately [-1, 1].
double perlin2(uint64_t seed, double x, double y);
double perlin3(uint64_t seed, double x, double y, double z);

// Fractal Brownian motion, normalised by total amplitude -> ~[-1, 1].
double fbm2(uint64_t seed, double x, double y, int octaves, double lacunarity = 2.0, double gain = 0.5);
double fbm3(uint64_t seed, double x, double y, double z, int octaves, double lacunarity = 2.0, double gain = 0.5);

// Musgrave ridged multifractal, output in [0, 1]; 1 on ridge crests.
double ridged2(uint64_t seed, double x, double y, int octaves, double lacunarity = 2.0, double gain = 0.5);

// "Billow" (|noise|) fBm in [0,1]: rounded hills, dunes.
double billow2(uint64_t seed, double x, double y, int octaves, double lacunarity = 2.0, double gain = 0.5);

struct Worley3 {
  double f1 = 1e30;     // distance to nearest feature point (lattice units)
  double f2 = 1e30;     // distance to second nearest
  uint64_t cell_hash = 0;  // hash identifying the nearest feature's cell
  double px = 0, py = 0, pz = 0;  // nearest feature point (lattice units)
};
// Cellular noise, one jittered feature point per unit cell.
Worley3 worley3(uint64_t seed, double x, double y, double z, double jitter = 0.9);

struct Worley2 {
  double f1 = 1e30, f2 = 1e30;
  uint64_t cell_hash = 0;
  double px = 0, py = 0;
  int64_t cx = 0, cy = 0;  // lattice cell of nearest feature
};
Worley2 worley2(uint64_t seed, double x, double y, double jitter = 0.9);

}  // namespace primeva::noise
