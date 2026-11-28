#pragma once

#include <cstdio>
#include <vector>

namespace ptest {
struct TestCase {
  const char* name;
  void (*fn)();
};
std::vector<TestCase>& registry();
int& failures();
struct Registrar {
  Registrar(const char* n, void (*f)()) { registry().push_back({n, f}); }
};
}  // namespace ptest

#define PTEST(name)                                              \
  static void name();                                            \
  static ::ptest::Registrar name##_registrar(#name, &name);      \
  static void name()

#define CHECK(cond)                                                                 \
  do {                                                                              \
    if (!(cond)) {                                                                  \
      std::printf("    %s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond);      \
      ++::ptest::failures();                                                        \
    }                                                                               \
  } while (0)

#define CHECK_NEAR(a, b, tol)                                                                          \
  do {                                                                                                 \
    const double pa_ = (a), pb_ = (b);                                                                 \
    if (!(std::abs(pa_ - pb_) <= (tol))) {                                                             \
      std::printf("    %s:%d: CHECK_NEAR failed: %s=%.9g vs %s=%.9g (tol %g)\n", __FILE__, __LINE__, #a, pa_, #b, pb_, \
                  static_cast<double>(tol));                                                           \
      ++::ptest::failures();                                                                           \
    }                                                                                                  \
  } while (0)
