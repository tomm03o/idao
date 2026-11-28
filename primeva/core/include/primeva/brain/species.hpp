#pragma once

#include <array>
#include <string>
#include <vector>

#include "primeva/brain/types.hpp"
#include "primeva/json.hpp"

namespace primeva::brain {

// Life history and attachment profile, derived from the social structure and
// body mass (see docs/design/07_cervello_creature.md, "Legami e generazioni").
struct BondProfile {
  float parental_care = 0.5f;       // 0..1 investment in young (feeding, guarding)
  bool biparental = false;          // pair-bonded species: both parents care
  bool alloparental = false;        // packs: every adult of the group helps raise the young
  float pack_bond_gain = 0.02f;     // bond gained per shared success (hunt, defence)
  float bond_decay_per_day = 0.03f; // without contact
  float imprint_window_days = 0.1f; // sensitive period after birth
  float maturation_days = 2.f;      // juvenile period (game days)
  int clutch = 2;                   // young per breeding event
  float dispersal = 0.f;            // 0..1 how much adults loosen the bond with parents at maturity
  bool egg_imprinting = false;      // roster taming method "imprinting_egg": imprints on whoever hatches it
};

// Everything the brain needs to know about a species, derived from
// data/creatures/creatures.json plus first-principles physiology.
struct SpeciesProfile {
  std::string id, name;
  Diet diet = Diet::Herbivore;
  Social social = Social::Solitary;
  int group_min = 1, group_max = 1;
  float mass_kg = 1.f, length_m = 1.f, height_m = 0.5f;
  bool biped = false, flyer = false, swimmer = false, burrower = false;
  std::array<float, kInstinctCount> instinct{};
  std::array<float, kSkillCount> affinity{};  // innate talent 0..1 (learning-rate multiplier)
  float vision = 0.5f, smell = 0.5f, hearing = 0.5f, tremor = 0.f;
  std::vector<std::string> innate_techniques;  // names from the roster (species-specific flavour)
  std::string taming_method;
  BondProfile bonds;

  // ---- derived (see derive()) ----
  int cognition_tier = 1;     // 1 enhancement, 2 emulation, 3 imitation, 4 active teaching
  float sprint_speed = 5.f;   // m/s
  float cruise_speed = 1.5f;  // m/s
  float sprint_endurance_s = 20.f;
  float attack = 1.f;         // damage per bite (arbitrary consistent units, ~ force)
  float toughness = 1.f;      // health pool
  float vision_range_m = 60.f, smell_range_m = 30.f, hearing_range_m = 60.f;
  float metabolic_rate = 1.f; // relative hunger rate per second (Kleiber: mass^-0.25)
  float body_radius_m = 0.5f;

  void derive();
};

// Loads every species from the roster file. Returns false on parse errors.
bool load_species(const std::string& path, std::vector<SpeciesProfile>& out, std::string* error = nullptr);
const SpeciesProfile* find_species(const std::vector<SpeciesProfile>& all, std::string_view id);

}  // namespace primeva::brain
