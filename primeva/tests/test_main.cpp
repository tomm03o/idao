// Minimal self-contained test runner (no external dependencies).
#include "test.hpp"

#include <chrono>
#include <cstdio>
#include <cstring>

namespace ptest {
std::vector<TestCase>& registry() {
  static std::vector<TestCase> r;
  return r;
}
int& failures() {
  static int f = 0;
  return f;
}
}  // namespace ptest

int main(int argc, char** argv) {
  const char* filter = argc > 1 ? argv[1] : nullptr;
  int run = 0, failed = 0;
  for (const auto& t : ptest::registry()) {
    if (filter && !std::strstr(t.name, filter)) continue;
    const int before = ptest::failures();
    const auto t0 = std::chrono::steady_clock::now();
    t.fn();
    const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    const bool ok = ptest::failures() == before;
    std::printf("[%s] %s (%.0f ms)\n", ok ? " OK " : "FAIL", t.name, ms);
    ++run;
    failed += ok ? 0 : 1;
  }
  std::printf("\n%d tests, %d failed\n", run, failed);
  return failed ? 1 : 0;
}
