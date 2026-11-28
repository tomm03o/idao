#pragma once

// Deterministic transcendental functions.
//
// Clients regenerate terrain locally instead of downloading it, so the
// generator must be bit-identical across compilers, OSes and CPUs. IEEE-754
// guarantees correctly-rounded + - * / and sqrt, but NOT sin/cos/exp/log/pow
// from the platform libm. Everything in the generation path therefore uses
// these implementations, built only from basic operations, std::floor and
// std::ldexp/std::frexp (both exact). Build with -ffp-contract=off (no FMA
// contraction) and without -ffast-math.

#include <cmath>
#include <cstdint>

namespace primeva::dmath {

inline constexpr double kPi = 3.14159265358979323846;
inline constexpr double kTwoPi = 6.28318530717958647692;
inline constexpr double kHalfPi = 1.57079632679489661923;
inline constexpr double kLn2 = 0.693147180559945309417;

// sin on [-pi/2, pi/2] via odd Taylor polynomial to x^21 (error < 1e-16 there).
inline double sin_core(double x) {
  const double x2 = x * x;
  double p = 1.0 / 51090942171709440000.0;            // 1/21!
  p = p * x2 - 1.0 / 121645100408832000.0;            // 1/19!
  p = p * x2 + 1.0 / 355687428096000.0;               // 1/17!
  p = p * x2 - 1.0 / 1307674368000.0;                 // 1/15!
  p = p * x2 + 1.0 / 6227020800.0;                    // 1/13!
  p = p * x2 - 1.0 / 39916800.0;                      // 1/11!
  p = p * x2 + 1.0 / 362880.0;                        // 1/9!
  p = p * x2 - 1.0 / 5040.0;                          // 1/7!
  p = p * x2 + 1.0 / 120.0;                           // 1/5!
  p = p * x2 - 1.0 / 6.0;                             // 1/3!
  p = p * x2 + 1.0;
  return p * x;
}

inline double sin(double x) {
  // reduce to [-pi, pi]
  x = x - std::floor(x / kTwoPi + 0.5) * kTwoPi;
  // reflect into [-pi/2, pi/2]: sin(pi - x) = sin(x)
  if (x > kHalfPi) x = kPi - x;
  else if (x < -kHalfPi) x = -kPi - x;
  return sin_core(x);
}
inline double cos(double x) { return sin(x + kHalfPi); }

inline double exp(double x) {
  if (x > 709.0) return HUGE_VAL;
  if (x < -745.0) return 0.0;
  const double kf = std::floor(x / kLn2 + 0.5);
  const double r = x - kf * kLn2;  // |r| <= ln2/2
  // Taylor to r^14: error < 1e-17 for |r| <= 0.347
  double p = 1.0 / 87178291200.0;
  p = p * r + 1.0 / 6227020800.0;
  p = p * r + 1.0 / 479001600.0;
  p = p * r + 1.0 / 39916800.0;
  p = p * r + 1.0 / 3628800.0;
  p = p * r + 1.0 / 362880.0;
  p = p * r + 1.0 / 40320.0;
  p = p * r + 1.0 / 5040.0;
  p = p * r + 1.0 / 720.0;
  p = p * r + 1.0 / 120.0;
  p = p * r + 1.0 / 24.0;
  p = p * r + 1.0 / 6.0;
  p = p * r + 0.5;
  p = p * r + 1.0;
  p = p * r + 1.0;
  return std::ldexp(p, static_cast<int>(kf));
}

inline double log(double x) {
  if (!(x > 0.0)) return x == 0.0 ? -HUGE_VAL : NAN;
  int e = 0;
  double m = std::frexp(x, &e);  // x = m * 2^e, m in [0.5, 1)
  if (m < 0.70710678118654752440) { m *= 2.0; e -= 1; }  // m in [0.707, 1.414)
  // log(m) = 2 atanh(s), s = (m-1)/(m+1), |s| <= 0.1716
  const double s = (m - 1.0) / (m + 1.0);
  const double s2 = s * s;
  double p = 1.0 / 23.0;
  p = p * s2 + 1.0 / 21.0;
  p = p * s2 + 1.0 / 19.0;
  p = p * s2 + 1.0 / 17.0;
  p = p * s2 + 1.0 / 15.0;
  p = p * s2 + 1.0 / 13.0;
  p = p * s2 + 1.0 / 11.0;
  p = p * s2 + 1.0 / 9.0;
  p = p * s2 + 1.0 / 7.0;
  p = p * s2 + 1.0 / 5.0;
  p = p * s2 + 1.0 / 3.0;
  p = p * s2 + 1.0;
  return 2.0 * s * p + static_cast<double>(e) * kLn2;
}

inline double pow(double a, double b) {
  if (b == 0.0) return 1.0;
  if (a == 0.0) return 0.0;
  if (a < 0.0) return NAN;  // generator never needs negative bases
  return dmath::exp(b * dmath::log(a));
}

inline double atan(double x) {
  // Range reduce: atan(x) = pi/2 - atan(1/x) for |x|>1; then halve twice
  // with atan(x) = 2 atan(x / (1 + sqrt(1 + x^2))) to |x| <= tan(pi/16).
  bool invert = false, neg = false;
  if (x < 0) { x = -x; neg = true; }
  if (x > 1.0) { x = 1.0 / x; invert = true; }
  x = x / (1.0 + std::sqrt(1.0 + x * x));
  x = x / (1.0 + std::sqrt(1.0 + x * x));
  const double x2 = x * x;  // |x| <= 0.199
  double p = -1.0 / 23.0;
  p = p * x2 + 1.0 / 21.0;
  p = p * x2 - 1.0 / 19.0;
  p = p * x2 + 1.0 / 17.0;
  p = p * x2 - 1.0 / 15.0;
  p = p * x2 + 1.0 / 13.0;
  p = p * x2 - 1.0 / 11.0;
  p = p * x2 + 1.0 / 9.0;
  p = p * x2 - 1.0 / 7.0;
  p = p * x2 + 1.0 / 5.0;
  p = p * x2 - 1.0 / 3.0;
  p = p * x2 + 1.0;
  double r = 4.0 * x * p;
  if (invert) r = kHalfPi - r;
  return neg ? -r : r;
}

inline double atan2(double y, double x) {
  if (x > 0) return dmath::atan(y / x);
  if (x < 0) return y >= 0 ? dmath::atan(y / x) + kPi : dmath::atan(y / x) - kPi;
  return y > 0 ? kHalfPi : (y < 0 ? -kHalfPi : 0.0);
}

}  // namespace primeva::dmath
