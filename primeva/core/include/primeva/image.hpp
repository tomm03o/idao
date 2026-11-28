#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace primeva {

// RGB8 image with a dependency-free PNG writer (zlib "stored" blocks).
struct Image {
  int width = 0, height = 0;
  std::vector<uint8_t> rgb;
  Image() = default;
  Image(int w, int h) : width(w), height(h), rgb(static_cast<size_t>(w) * h * 3, 0) {}
  void set(int x, int y, uint8_t r, uint8_t g, uint8_t b) {
    const size_t i = (static_cast<size_t>(y) * width + x) * 3;
    rgb[i] = r; rgb[i + 1] = g; rgb[i + 2] = b;
  }
  bool write_png(const std::string& path) const;
};

}  // namespace primeva
