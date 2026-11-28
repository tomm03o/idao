#include "primeva/image.hpp"

#include <algorithm>
#include <array>
#include <fstream>

namespace primeva {
namespace {

const std::array<uint32_t, 256>& crc_table() {
  static const std::array<uint32_t, 256> t = [] {
    std::array<uint32_t, 256> r{};
    for (uint32_t n = 0; n < 256; ++n) {
      uint32_t c = n;
      for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
      r[n] = c;
    }
    return r;
  }();
  return t;
}

uint32_t crc32(const uint8_t* d, size_t n, uint32_t c = 0xFFFFFFFFu) {
  const auto& t = crc_table();
  for (size_t i = 0; i < n; ++i) c = t[(c ^ d[i]) & 0xFF] ^ (c >> 8);
  return c;
}

void be32(std::vector<uint8_t>& v, uint32_t x) {
  v.push_back(static_cast<uint8_t>(x >> 24)); v.push_back(static_cast<uint8_t>(x >> 16));
  v.push_back(static_cast<uint8_t>(x >> 8)); v.push_back(static_cast<uint8_t>(x));
}

void chunk(std::vector<uint8_t>& out, const char* type, const std::vector<uint8_t>& data) {
  be32(out, static_cast<uint32_t>(data.size()));
  std::vector<uint8_t> td(type, type + 4);
  td.insert(td.end(), data.begin(), data.end());
  out.insert(out.end(), td.begin(), td.end());
  be32(out, crc32(td.data(), td.size()) ^ 0xFFFFFFFFu);
}

}  // namespace

bool Image::write_png(const std::string& path) const {
  std::vector<uint8_t> raw;
  raw.reserve(static_cast<size_t>(height) * (width * 3 + 1));
  for (int y = 0; y < height; ++y) {
    raw.push_back(0);  // filter: none
    raw.insert(raw.end(), rgb.begin() + static_cast<std::ptrdiff_t>(static_cast<size_t>(y) * width * 3),
               rgb.begin() + static_cast<std::ptrdiff_t>(static_cast<size_t>(y + 1) * width * 3));
  }
  std::vector<uint8_t> z = {0x78, 0x01};
  uint32_t a = 1, b = 0;
  for (uint8_t c : raw) { a = (a + c) % 65521; b = (b + a) % 65521; }
  size_t pos = 0;
  do {
    const size_t len = std::min<size_t>(65535, raw.size() - pos);
    const bool last = pos + len == raw.size();
    z.push_back(last ? 1 : 0);
    z.push_back(static_cast<uint8_t>(len & 0xFF)); z.push_back(static_cast<uint8_t>(len >> 8));
    z.push_back(static_cast<uint8_t>(~len & 0xFF)); z.push_back(static_cast<uint8_t>((~len >> 8) & 0xFF));
    z.insert(z.end(), raw.begin() + static_cast<std::ptrdiff_t>(pos), raw.begin() + static_cast<std::ptrdiff_t>(pos + len));
    pos += len;
  } while (pos < raw.size());
  be32(z, (b << 16) | a);

  std::vector<uint8_t> out = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
  std::vector<uint8_t> ihdr;
  be32(ihdr, static_cast<uint32_t>(width)); be32(ihdr, static_cast<uint32_t>(height));
  ihdr.insert(ihdr.end(), {8, 2, 0, 0, 0});
  chunk(out, "IHDR", ihdr);
  chunk(out, "IDAT", z);
  chunk(out, "IEND", {});
  std::ofstream f(path, std::ios::binary | std::ios::trunc);
  f.write(reinterpret_cast<const char*>(out.data()), static_cast<std::streamsize>(out.size()));
  return static_cast<bool>(f);
}

}  // namespace primeva
