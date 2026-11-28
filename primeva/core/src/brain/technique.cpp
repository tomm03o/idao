#include "primeva/brain/technique.hpp"

#include <algorithm>
#include <cmath>

#include "primeva/dmath.hpp"
#include "primeva/json.hpp"

namespace primeva::brain {

namespace {
constexpr std::array<std::string_view, kInputCount> kInputNames = {
    "hunger", "thirst", "fatigue", "threat", "threat_new", "threat_weaker", "prey_quality", "prey_near",
    "carcass_near", "herd_near", "packmates", "alone", "health", "stamina", "boredom", "group_hunt_active",
    "attachment_far", "attachment_threat", "juvenile", "young_hungry", "young_threat", "young_near"};
constexpr std::array<std::string_view, static_cast<size_t>(Executor::Count)> kExecNames = {
    "graze", "drink", "rest", "wander", "regroup", "flee", "herd_circle", "alarm_call", "mob_charge", "stalk",
    "pursue", "pack_flank", "join_hunt", "scavenge", "capture", "follow_attachment", "guard_attachment", "search",
    "provision", "guard_young"};
constexpr std::array<std::string_view, kCommandCount> kCommandNames = {"none", "follow", "stay", "guard", "hunt", "capture"};

template <size_t N>
int index_of(const std::array<std::string_view, N>& names, std::string_view n) {
  for (size_t i = 0; i < N; ++i)
    if (names[i] == n) return static_cast<int>(i);
  return -1;
}
}  // namespace

std::string_view command_name(Command c) { return kCommandNames[static_cast<size_t>(c)]; }

float Consideration::eval(float x) const {
  x = std::clamp(x, 0.f, 1.f);
  double y = 0.0;
  switch (type) {
    case CurveType::Linear: y = a * x + b; break;
    case CurveType::Logistic: y = 1.0 / (1.0 + dmath::exp(-static_cast<double>(a) * (x - b))); break;
    case CurveType::Power: y = dmath::pow(std::max(1e-6, static_cast<double>(x)), a); break;
    case CurveType::InversePower: y = dmath::pow(std::max(1e-6, 1.0 - x), a); break;
    case CurveType::Step: y = x >= a ? 1.0 : 0.0; break;
  }
  return static_cast<float>(std::clamp(y, 0.0, 1.0));
}

int TechniqueLibrary::find(std::string_view id) const {
  for (size_t i = 0; i < defs_.size(); ++i)
    if (defs_[i].id == id) return static_cast<int>(i);
  return -1;
}

bool TechniqueLibrary::load(const std::string& path, std::string* error) {
  auto fail = [&](const std::string& m) {
    if (error) *error = m;
    return false;
  };
  json::ParseError pe;
  const auto doc = json::parse_file(path, &pe);
  if (!doc) return fail("techniques: " + pe.message + " at line " + std::to_string(pe.line));
  defs_.clear();
  for (const json::Value& t : (*doc)["techniques"].arr()) {
    TechniqueDef d;
    d.id = t.get_str("id");
    const auto cat = skill_from_name(t.get_str("category"));
    if (!cat) return fail("technique " + d.id + ": unknown category " + t.get_str("category"));
    d.category = *cat;
    const int ex = index_of(kExecNames, t.get_str("executor"));
    if (ex < 0) return fail("technique " + d.id + ": unknown executor " + t.get_str("executor"));
    d.executor = static_cast<Executor>(ex);
    if (t.has("diets")) {
      d.diet_mask = 0;
      for (const auto& dv : t["diets"].arr()) {
        if (dv.str() == "*") { d.diet_mask = 0xFFFFFFFFu; break; }
        const auto diet = diet_from_name(dv.str());
        if (!diet) return fail("technique " + d.id + ": unknown diet " + dv.str());
        d.diet_mask |= 1u << static_cast<int>(*diet);
      }
    }
    d.base_weight = static_cast<float>(t.get("base_weight", 1.0));
    d.difficulty = static_cast<float>(t.get("difficulty", 0.0));
    d.risk = static_cast<float>(t.get("risk", 0.0));
    d.min_tier = static_cast<int>(t.get("min_tier", 1));
    d.cooperative = t["cooperative"].boolean();
    d.social_only = t["social_only"].boolean();
    d.owned_only = t["owned_only"].boolean();
    d.needs_attachment = t["needs_attachment"].boolean();
    d.parents_only = t["parents_only"].boolean();
    d.adults_only = t["adults_only"].boolean();
    for (const auto& [k, v] : t["instinct_gate"].obj()) {
      const auto in = instinct_from_name(k);
      if (!in) return fail("technique " + d.id + ": unknown instinct " + k);
      d.gate[static_cast<size_t>(*in)] = static_cast<float>(v.num());
    }
    for (const auto& [k, v] : t["instinct_weight"].obj()) {
      const auto in = instinct_from_name(k);
      if (!in) return fail("technique " + d.id + ": unknown instinct " + k);
      d.weight[static_cast<size_t>(*in)] = static_cast<float>(v.num());
    }
    for (const auto& c : t["considerations"].arr()) {
      Consideration con;
      const int in = index_of(kInputNames, c.get_str("input"));
      if (in < 0) return fail("technique " + d.id + ": unknown input " + c.get_str("input"));
      con.input = static_cast<Input>(in);
      const std::string curve = c.get_str("curve", "linear");
      if (curve == "linear") { con.type = CurveType::Linear; con.a = static_cast<float>(c.get("m", 1.0)); con.b = static_cast<float>(c.get("b", 0.0)); }
      else if (curve == "logistic") { con.type = CurveType::Logistic; con.a = static_cast<float>(c.get("k", 8.0)); con.b = static_cast<float>(c.get("c", 0.5)); }
      else if (curve == "power") { con.type = CurveType::Power; con.a = static_cast<float>(c.get("k", 1.0)); }
      else if (curve == "inverse_power") { con.type = CurveType::InversePower; con.a = static_cast<float>(c.get("k", 1.0)); }
      else if (curve == "step") { con.type = CurveType::Step; con.a = static_cast<float>(c.get("c", 0.5)); }
      else return fail("technique " + d.id + ": unknown curve " + curve);
      d.considerations.push_back(con);
    }
    d.discover_trigger = t["discover"].get_str("trigger");
    d.discover_p = static_cast<float>(t["discover"].get("p", 0.0));
    defs_.push_back(std::move(d));
  }
  // command -> technique mapping
  for (const auto& [cmd, list] : (*doc)["commands"].obj()) {
    const int ci = index_of(kCommandNames, cmd);
    if (ci < 0) return fail("unknown command " + cmd);
    for (const auto& tv : list.arr()) {
      const int ti = find(tv.str());
      if (ti < 0) return fail("command " + cmd + " references unknown technique " + tv.str());
      defs_[static_cast<size_t>(ti)].command_mask |= 1u << ci;
    }
  }
  return true;
}

}  // namespace primeva::brain
