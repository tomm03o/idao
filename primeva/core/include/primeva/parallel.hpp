#pragma once

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <functional>
#include <thread>
#include <vector>

namespace primeva {

inline unsigned worker_count() {
  const unsigned n = std::thread::hardware_concurrency();
  return n == 0 ? 1u : n;
}

// Runs fn(i) for i in [begin, end) on all hardware threads with dynamic
// work stealing in blocks. fn must only write to data owned by index i, which
// keeps the result independent of scheduling (deterministic).
inline void parallel_for(size_t begin, size_t end, const std::function<void(size_t)>& fn, size_t block = 1) {
  if (end <= begin) return;
  const unsigned threads = std::min<unsigned>(worker_count(), static_cast<unsigned>((end - begin + block - 1) / block));
  if (threads <= 1) {
    for (size_t i = begin; i < end; ++i) fn(i);
    return;
  }
  std::atomic<size_t> next{begin};
  auto worker = [&]() {
    for (;;) {
      const size_t s = next.fetch_add(block);
      if (s >= end) break;
      const size_t e = std::min(end, s + block);
      for (size_t i = s; i < e; ++i) fn(i);
    }
  };
  std::vector<std::thread> pool;
  pool.reserve(threads - 1);
  for (unsigned t = 1; t < threads; ++t) pool.emplace_back(worker);
  worker();
  for (auto& t : pool) t.join();
}

}  // namespace primeva
