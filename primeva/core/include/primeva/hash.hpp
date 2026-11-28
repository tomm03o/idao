#pragma once

#include <cstdint>
#include <string_view>

namespace primeva {

// SplitMix64 finaliser: a bijective, well-avalanched 64-bit mix. All procedural
// randomness in Primeva is a pure function of (seed, coordinates) so that the
// server, every client and offline tools generate bit-identical worlds.
constexpr uint64_t mix64(uint64_t z) {
  z += 0x9E3779B97F4A7C15ULL;
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  return z ^ (z >> 31);
}

constexpr uint64_t hash_combine(uint64_t seed, uint64_t v) { return mix64(seed ^ (v + 0x9E3779B97F4A7C15ULL + (seed << 6) + (seed >> 2))); }

constexpr uint64_t hash2(uint64_t seed, int64_t x, int64_t y) {
  return mix64(seed ^ mix64(static_cast<uint64_t>(x) * 0x8CB92BA72F3D8DD7ULL ^ static_cast<uint64_t>(y) * 0xA0761D6478BD642FULL));
}
constexpr uint64_t hash3(uint64_t seed, int64_t x, int64_t y, int64_t z) {
  return mix64(seed ^ mix64(static_cast<uint64_t>(x) * 0x8CB92BA72F3D8DD7ULL ^ static_cast<uint64_t>(y) * 0xA0761D6478BD642FULL ^
                            static_cast<uint64_t>(z) * 0xE7037ED1A0B428DBULL));
}

// Uniform double in [0,1) from the top 53 bits.
constexpr double to_unit(uint64_t h) { return static_cast<double>(h >> 11) * (1.0 / 9007199254740992.0); }

constexpr uint64_t hash_string(std::string_view s) {
  uint64_t h = 0xCBF29CE484222325ULL;  // FNV-1a then finalised
  for (char c : s) { h ^= static_cast<uint8_t>(c); h *= 0x100000001B3ULL; }
  return mix64(h);
}

// Small deterministic PRNG (xoshiro256**) for offline bakes where sequential
// randomness is needed (erosion droplets, placement).
class Rng {
 public:
  explicit Rng(uint64_t seed) {
    uint64_t z = seed;
    for (auto& v : s_) { z = mix64(z); v = z; }
  }
  uint64_t next() {
    const uint64_t r = rotl(s_[1] * 5, 7) * 9;
    const uint64_t t = s_[1] << 17;
    s_[2] ^= s_[0]; s_[3] ^= s_[1]; s_[1] ^= s_[2]; s_[0] ^= s_[3];
    s_[2] ^= t; s_[3] = rotl(s_[3], 45);
    return r;
  }
  double uniform() { return to_unit(next()); }
  double uniform(double lo, double hi) { return lo + (hi - lo) * uniform(); }
  uint32_t below(uint32_t n) { return static_cast<uint32_t>((next() >> 32) * n >> 32); }

 private:
  static constexpr uint64_t rotl(uint64_t x, int k) { return (x << k) | (x >> (64 - k)); }
  uint64_t s_[4];
};

}  // namespace primeva
