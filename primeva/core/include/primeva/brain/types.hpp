#pragma once

// Shared vocabulary of the creature brain (ids match the data files).

#include <array>
#include <cstdint>
#include <optional>
#include <string_view>

namespace primeva::brain {

enum class Instinct : uint8_t { Aggression, Fear, Curiosity, Territoriality, Sociability, Patience, Playfulness, Count };
inline constexpr int kInstinctCount = static_cast<int>(Instinct::Count);

enum class Skill : uint8_t {
  HuntingAmbush, HuntingPursuit, HuntingCooperative, Fishing, DiggingBurrowing, Foraging, Harvesting,
  DefenseGuarding, DefenseHerdCircle, CombatMelee, CombatRanged, Evasion, Stealth, Tracking, ScoutingAerial,
  TransportHauling, Construction, Climbing, SwimmingDiving, CaptureNonlethal, Communication, TerritoryPatrol,
  RetrievalRescue, Count
};
inline constexpr int kSkillCount = static_cast<int>(Skill::Count);

enum class Social : uint8_t { Solitary, Pair, Pack, Herd, Colony, Swarm };
enum class Diet : uint8_t { Carnivore, Herbivore, Omnivore, Piscivore, Insectivore, Scavenger, FilterFeeder, Lithovore };

std::string_view instinct_name(Instinct i);
std::string_view skill_name(Skill s);
std::optional<Instinct> instinct_from_name(std::string_view n);
std::optional<Skill> skill_from_name(std::string_view n);
std::optional<Social> social_from_name(std::string_view n);
std::optional<Diet> diet_from_name(std::string_view n);

// ----------------------------------------------------------------------------
// MotorCommand: the ONLY interface from the cognitive brain to the motor brain.
// Identical for wild, tamed and ridden creatures; the motor brain (learned
// locomotion policy near players, kinematic model far away) turns it into
// movement and reports back a MotorStatus.
// ----------------------------------------------------------------------------
enum class Gait : uint8_t { Stand, Sneak, Walk, Trot, Run, Sprint };
enum class MotorAction : uint8_t { None, Bite, Pin, Charge, Call, Eat, Drink, Dig, Rest };

struct MotorCommand {
  float target_x = 0.f, target_z = 0.f;  // world metres
  Gait gait = Gait::Stand;
  MotorAction action = MotorAction::None;
  uint32_t action_target = 0;            // entity id for Bite / Pin / Charge
  float look_x = 0.f, look_z = 0.f;      // head / attention target
};

struct MotorStatus {
  float speed = 0.f;          // current ground speed m/s
  float stamina = 1.f;        // 0..1 anaerobic reserve
  float stability = 1.f;      // 0..1 (1 = steady); motor brain reports stumbles
  bool action_done = false;   // last action resolved this tick
  bool action_hit = false;
};

}  // namespace primeva::brain
