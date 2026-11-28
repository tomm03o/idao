#include "primeva/json.hpp"

#include <cstdlib>
#include <fstream>
#include <sstream>

namespace primeva::json {

namespace {
const Value& null_value() {
  static const Value v;
  return v;
}

class Parser {
 public:
  Parser(std::string_view t, ParseError* e) : t_(t), err_(e) {}

  std::optional<Value> run() {
    ws();
    Value v;
    if (!value(v, 0)) return std::nullopt;
    ws();
    if (p_ != t_.size()) return fail("trailing characters after document");
    return v;
  }

 private:
  static constexpr int kMaxDepth = 256;

  std::nullopt_t fail(const char* msg) {
    if (err_) {
      err_->offset = p_;
      err_->line = 1;
      for (size_t i = 0; i < p_ && i < t_.size(); ++i) err_->line += t_[i] == '\n';
      err_->message = msg;
    }
    ok_ = false;
    return std::nullopt;
  }

  void ws() {
    while (p_ < t_.size() && (t_[p_] == ' ' || t_[p_] == '\t' || t_[p_] == '\n' || t_[p_] == '\r')) ++p_;
  }

  bool lit(std::string_view s) {
    if (t_.substr(p_, s.size()) != s) return false;
    p_ += s.size();
    return true;
  }

  bool value(Value& out, int depth) {
    if (depth > kMaxDepth) { fail("nesting too deep"); return false; }
    if (p_ >= t_.size()) { fail("unexpected end of input"); return false; }
    const char c = t_[p_];
    if (c == '{') return object(out, depth);
    if (c == '[') return array(out, depth);
    if (c == '"') {
      std::string s;
      if (!string(s)) return false;
      out = Value::make_string(std::move(s));
      return true;
    }
    if (c == 't') { if (lit("true")) { out = Value::make_bool(true); return true; } fail("invalid literal"); return false; }
    if (c == 'f') { if (lit("false")) { out = Value::make_bool(false); return true; } fail("invalid literal"); return false; }
    if (c == 'n') { if (lit("null")) { out = Value(); return true; } fail("invalid literal"); return false; }
    if (c == '-' || (c >= '0' && c <= '9')) return number(out);
    fail("unexpected character");
    return false;
  }

  bool number(Value& out) {
    const size_t start = p_;
    if (t_[p_] == '-') ++p_;
    if (p_ >= t_.size()) { fail("bad number"); return false; }
    if (t_[p_] == '0') {
      ++p_;
    } else if (t_[p_] >= '1' && t_[p_] <= '9') {
      while (p_ < t_.size() && t_[p_] >= '0' && t_[p_] <= '9') ++p_;
    } else {
      fail("bad number");
      return false;
    }
    if (p_ < t_.size() && t_[p_] == '.') {
      ++p_;
      if (p_ >= t_.size() || t_[p_] < '0' || t_[p_] > '9') { fail("bad fraction"); return false; }
      while (p_ < t_.size() && t_[p_] >= '0' && t_[p_] <= '9') ++p_;
    }
    if (p_ < t_.size() && (t_[p_] == 'e' || t_[p_] == 'E')) {
      ++p_;
      if (p_ < t_.size() && (t_[p_] == '+' || t_[p_] == '-')) ++p_;
      if (p_ >= t_.size() || t_[p_] < '0' || t_[p_] > '9') { fail("bad exponent"); return false; }
      while (p_ < t_.size() && t_[p_] >= '0' && t_[p_] <= '9') ++p_;
    }
    const std::string tok(t_.substr(start, p_ - start));
    out = Value::make_number(std::strtod(tok.c_str(), nullptr));
    return true;
  }

  static void put_utf8(std::string& s, uint32_t cp) {
    if (cp < 0x80) s += static_cast<char>(cp);
    else if (cp < 0x800) { s += static_cast<char>(0xC0 | (cp >> 6)); s += static_cast<char>(0x80 | (cp & 0x3F)); }
    else if (cp < 0x10000) {
      s += static_cast<char>(0xE0 | (cp >> 12)); s += static_cast<char>(0x80 | ((cp >> 6) & 0x3F)); s += static_cast<char>(0x80 | (cp & 0x3F));
    } else {
      s += static_cast<char>(0xF0 | (cp >> 18)); s += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
      s += static_cast<char>(0x80 | ((cp >> 6) & 0x3F)); s += static_cast<char>(0x80 | (cp & 0x3F));
    }
  }

  bool hex4(uint32_t& v) {
    if (p_ + 4 > t_.size()) return false;
    v = 0;
    for (int k = 0; k < 4; ++k) {
      const char c = t_[p_++];
      v <<= 4;
      if (c >= '0' && c <= '9') v |= static_cast<uint32_t>(c - '0');
      else if (c >= 'a' && c <= 'f') v |= static_cast<uint32_t>(c - 'a' + 10);
      else if (c >= 'A' && c <= 'F') v |= static_cast<uint32_t>(c - 'A' + 10);
      else return false;
    }
    return true;
  }

  bool string(std::string& s) {
    ++p_;  // opening quote
    while (true) {
      if (p_ >= t_.size()) { fail("unterminated string"); return false; }
      const char c = t_[p_++];
      if (c == '"') return true;
      if (static_cast<unsigned char>(c) < 0x20) { fail("control character in string"); return false; }
      if (c != '\\') { s += c; continue; }
      if (p_ >= t_.size()) { fail("bad escape"); return false; }
      const char e = t_[p_++];
      switch (e) {
        case '"': s += '"'; break;
        case '\\': s += '\\'; break;
        case '/': s += '/'; break;
        case 'b': s += '\b'; break;
        case 'f': s += '\f'; break;
        case 'n': s += '\n'; break;
        case 'r': s += '\r'; break;
        case 't': s += '\t'; break;
        case 'u': {
          uint32_t cp;
          if (!hex4(cp)) { fail("bad \\u escape"); return false; }
          if (cp >= 0xD800 && cp <= 0xDBFF) {  // surrogate pair
            uint32_t lo;
            if (!lit("\\u") || !hex4(lo) || lo < 0xDC00 || lo > 0xDFFF) { fail("bad surrogate pair"); return false; }
            cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
          } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
            fail("lone low surrogate");
            return false;
          }
          put_utf8(s, cp);
          break;
        }
        default: fail("bad escape"); return false;
      }
    }
  }

  bool array(Value& out, int depth) {
    ++p_;
    out = Value::make_array();
    ws();
    if (p_ < t_.size() && t_[p_] == ']') { ++p_; return true; }
    while (true) {
      ws();
      Value v;
      if (!value(v, depth + 1)) return false;
      out.arr().push_back(std::move(v));
      ws();
      if (p_ >= t_.size()) { fail("unterminated array"); return false; }
      if (t_[p_] == ',') { ++p_; continue; }
      if (t_[p_] == ']') { ++p_; return true; }
      fail("expected , or ]");
      return false;
    }
  }

  bool object(Value& out, int depth) {
    ++p_;
    out = Value::make_object();
    ws();
    if (p_ < t_.size() && t_[p_] == '}') { ++p_; return true; }
    while (true) {
      ws();
      if (p_ >= t_.size() || t_[p_] != '"') { fail("expected key string"); return false; }
      std::string key;
      if (!string(key)) return false;
      ws();
      if (p_ >= t_.size() || t_[p_] != ':') { fail("expected :"); return false; }
      ++p_;
      ws();
      Value v;
      if (!value(v, depth + 1)) return false;
      out.obj().emplace_back(std::move(key), std::move(v));
      ws();
      if (p_ >= t_.size()) { fail("unterminated object"); return false; }
      if (t_[p_] == ',') { ++p_; continue; }
      if (t_[p_] == '}') { ++p_; return true; }
      fail("expected , or }");
      return false;
    }
  }

  std::string_view t_;
  ParseError* err_;
  size_t p_ = 0;
  bool ok_ = true;
};
}  // namespace

const Value& Value::operator[](std::string_view key) const {
  if (type_ != Type::Object) return null_value();
  for (const auto& [k, v] : o_)
    if (k == key) return v;
  return null_value();
}

const Value& Value::operator[](size_t i) const {
  if (type_ != Type::Array || i >= a_.size()) return null_value();
  return a_[i];
}

bool Value::has(std::string_view key) const {
  if (type_ != Type::Object) return false;
  for (const auto& kv : o_)
    if (kv.first == key) return true;
  return false;
}

std::optional<Value> parse(std::string_view text, ParseError* err) { return Parser(text, err).run(); }

std::optional<Value> parse_file(const std::string& path, ParseError* err) {
  std::ifstream f(path, std::ios::binary);
  if (!f) {
    if (err) err->message = "cannot open " + path;
    return std::nullopt;
  }
  std::stringstream ss;
  ss << f.rdbuf();
  return parse(ss.str(), err);
}

}  // namespace primeva::json
