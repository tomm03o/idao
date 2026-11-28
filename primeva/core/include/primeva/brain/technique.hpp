#pragma once

#include <array>
#include <string>
#include <string_view>
#include <vector>

#include "primeva/brain/types.hpp"

namespace primeva::brain {

// Normalised (0..1) facts the decision layer reads. Computed by the host
// world from perception + memory + body state; identical for wild and tamed.
enum class Input : uint8_t {
  Hunger, Thirst, Fatigue, Threat, ThreatNew, ThreatWeaker, PreyQuality, PreyNear, CarcassNear, HerdNear,
  Packmates, Alone, Health, Stamina, Boredom, GroupHuntActive,
  AttachmentFar,     // distance to the primary attachment figure (parent or owner), normalised
  AttachmentThreat,  // a threat close to the attachment figure
  Juvenile,          // 1 while the creature is young (dependent)
  YoungHungry,       // hunger of my dependent young nearby (parents)
  YoungThreat,       // threat close to my dependent young (parents)
  YoungNear,         // my young are close (teaching opportunity)
  Count
};
inline constexpr int kInputCount = static_cast<int>(Input::Count);
using Inputs = std::array<float, kInputCount>;

enum class CurveType : uint8_t { Linear, Logistic, Power, InversePower, Step };

struct Consideration {
  Input input = Input::Hunger;
  CurveType type = CurveType::Linear;
  float a = 1.f, b = 0.f;  // linear: m,b | logistic: k,c | power: k | step: c
  float eval(float x) const;
};

// The finite set of behaviours the host knows how to execute. Techniques are
// data that select, parameterise and combine these.
enum class Executor : uint8_t {
  Graze, Drink, Rest, Wander, Regroup, Flee, HerdCircle, AlarmCall, MobCharge, Stalk, Pursue, PackFlank,
  JoinHunt, Scavenge, Capture, FollowAttachment, GuardAttachment, Search, Provision, GuardYoung, Count
};

enum class Command : uint8_t { None, Follow, Stay, Guard, Hunt, Capture, Count };
inline constexpr int kCommandCount = static_cast<int>(Command::Count);
std::string_view command_name(Command c);

struct TechniqueDef {
  std::string id;
  Skill category = Skill::Foraging;
  Executor executor = Executor::Wander;
  uint32_t diet_mask = 0xFFFFFFFFu;
  float base_weight = 1.f, difficulty = 0.f, risk = 0.f;
  int min_tier = 1;
  bool cooperative = false, social_only = false, owned_only = false;
  bool needs_attachment = false;  // usable only with an attachment figure (parent or owner)
  bool parents_only = false;      // usable only by a creature with dependent young
  bool adults_only = false;       // not available to juveniles
  std::array<float, kInstinctCount> gate{};    // minimum instinct value (0 = no gate)
  std::array<float, kInstinctCount> weight{};  // utility / learning modulation by instinct
  std::vector<Consideration> considerations;
  std::string discover_trigger;
  float discover_p = 0.f;
  uint32_t command_mask = 0;                   // commands this technique fulfils

  bool is_hunt() const {
    return executor == Executor::Stalk || executor == Executor::Pursue || executor == Executor::PackFlank ||
           executor == Executor::JoinHunt || executor == Executor::Capture;
  }
};

class TechniqueLibrary {
 public:
  bool load(const std::string& path, std::string* error = nullptr);
  const TechniqueDef& operator[](size_t i) const { return defs_[i]; }
  size_t size() const { return defs_.size(); }
  int find(std::string_view id) const;
  const std::vector<TechniqueDef>& all() const { return defs_; }

 private:
  std::vector<TechniqueDef> defs_;
};

}  // namespace primeva::brain
