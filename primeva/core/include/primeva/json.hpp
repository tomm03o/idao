#pragma once

// Small, strict JSON (RFC 8259) DOM parser for game data files.
// Objects keep insertion order (deterministic iteration).

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace primeva::json {

class Value {
 public:
  enum class Type : uint8_t { Null, Bool, Number, String, Array, Object };

  Value() = default;
  static Value make_bool(bool b) { Value v; v.type_ = Type::Bool; v.b_ = b; return v; }
  static Value make_number(double d) { Value v; v.type_ = Type::Number; v.n_ = d; return v; }
  static Value make_string(std::string s) { Value v; v.type_ = Type::String; v.s_ = std::move(s); return v; }
  static Value make_array() { Value v; v.type_ = Type::Array; return v; }
  static Value make_object() { Value v; v.type_ = Type::Object; return v; }

  Type type() const { return type_; }
  bool is_null() const { return type_ == Type::Null; }
  bool is_number() const { return type_ == Type::Number; }
  bool is_string() const { return type_ == Type::String; }
  bool is_array() const { return type_ == Type::Array; }
  bool is_object() const { return type_ == Type::Object; }

  double num(double fallback = 0.0) const { return type_ == Type::Number ? n_ : fallback; }
  bool boolean(bool fallback = false) const { return type_ == Type::Bool ? b_ : fallback; }
  const std::string& str() const { return s_; }
  const std::vector<Value>& arr() const { return a_; }
  std::vector<Value>& arr() { return a_; }
  const std::vector<std::pair<std::string, Value>>& obj() const { return o_; }
  std::vector<std::pair<std::string, Value>>& obj() { return o_; }

  // Object member lookup; returns a static null value when absent.
  const Value& operator[](std::string_view key) const;
  const Value& operator[](size_t i) const;
  bool has(std::string_view key) const;
  size_t size() const { return type_ == Type::Array ? a_.size() : (type_ == Type::Object ? o_.size() : 0); }

  double get(std::string_view key, double fallback) const {
    const Value& v = (*this)[key];
    return v.is_number() ? v.num() : fallback;
  }
  std::string get_str(std::string_view key, std::string fallback = "") const {
    const Value& v = (*this)[key];
    return v.is_string() ? v.str() : fallback;
  }

 private:
  Type type_ = Type::Null;
  bool b_ = false;
  double n_ = 0.0;
  std::string s_;
  std::vector<Value> a_;
  std::vector<std::pair<std::string, Value>> o_;
};

struct ParseError {
  size_t offset = 0;
  int line = 1;
  std::string message;
};

std::optional<Value> parse(std::string_view text, ParseError* err = nullptr);
std::optional<Value> parse_file(const std::string& path, ParseError* err = nullptr);

}  // namespace primeva::json
