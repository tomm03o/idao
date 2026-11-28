#include "primeva/brain/species.hpp"

#include <algorithm>
#include <cmath>

#include "primeva/dmath.hpp"

namespace primeva::brain {

namespace {
constexpr std::array<std::string_view, kInstinctCount> kInstinctNames = {
    "aggression", "fear", "curiosity", "territoriality", "sociability", "patience", "playfulness"};
constexpr std::array<std::string_view, kSkillCount> kSkillNames = {
    "hunting_ambush", "hunting_pursuit", "hunting_cooperative", "fishing", "digging_burrowing", "foraging",
    "harvesting", "defense_guarding", "defense_herd_circle", "combat_melee", "combat_ranged", "evasion",
    "stealth", "tracking", "scouting_aerial", "transport_hauling", "construction", "climbing", "swimming_diving",
    "capture_nonlethal", "communication", "territory_patrol", "retrieval_rescue"};
constexpr std::array<std::string_view, 6> kSocialNames = {"solitary", "pair", "pack", "herd", "colony", "swarm"};
constexpr std::array<std::string_view, 8> kDietNames = {"carnivore", "herbivore", "omnivore", "piscivore",
                                                        "insectivore", "scavenger", "filter_feeder", "lithovore"};
template <typename E, size_t N>
std::optional<E> lookup(const std::array<std::string_view, N>& names, std::string_view n) {
  for (size_t i = 0; i < N; ++i)
    if (names[i] == n) return static_cast<E>(i);
  return std::nullopt;
}
}  // namespace

std::string_view instinct_name(Instinct i) { return kInstinctNames[static_cast<size_t>(i)]; }
std::string_view skill_name(Skill s) { return kSkillNames[static_cast<size_t>(s)]; }
std::optional<Instinct> instinct_from_name(std::string_view n) { return lookup<Instinct>(kInstinctNames, n); }
std::optional<Skill> skill_from_name(std::string_view n) { return lookup<Skill>(kSkillNames, n); }
std::optional<Social> social_from_name(std::string_view n) { return lookup<Social>(kSocialNames, n); }
std::optional<Diet> diet_from_name(std::string_view n) { return lookup<Diet>(kDietNames, n); }

void SpeciesProfile::derive() {
  const double g = 9.81;
  // Hip height ~ 0.55 x standing height for quadrupeds/bipeds.
  const double hip = std::max(0.05, 0.55 * static_cast<double>(height_m));
  // Dynamic similarity (Alexander 1989): v = sqrt(Fr * g * h). Maximum Froude
  // number falls with size (graviportal giants walk at Fr < 1; small
  // cursorial bipeds reach Fr ~ 3-5).
  const double log_m = dmath::log(std::max(0.1, static_cast<double>(mass_kg))) / dmath::log(10.0);
  double fr_max = std::clamp(4.6 - 1.1 * log_m, 0.5, 5.0);
  if (biped) fr_max *= 1.15;
  sprint_speed = static_cast<float>(std::sqrt(fr_max * g * hip));
  cruise_speed = static_cast<float>(std::sqrt(0.25 * g * hip));
  // Anaerobic sprint endurance: predators of pursuit build tolerate longer chases.
  sprint_endurance_s = 12.f + 25.f * affinity[static_cast<size_t>(Skill::HuntingPursuit)] +
                       10.f * affinity[static_cast<size_t>(Skill::Evasion)];
  // Muscle force scales with cross-section ~ M^(2/3); predators/armoured
  // defenders convert it into effective damage via their combat affinity.
  const double m23 = dmath::pow(std::max(0.1, static_cast<double>(mass_kg)), 2.0 / 3.0);
  const double weapon = (diet == Diet::Carnivore ? 1.0 : 0.45) + 0.6 * affinity[static_cast<size_t>(Skill::CombatMelee)] +
                        0.3 * affinity[static_cast<size_t>(Skill::DefenseGuarding)];
  attack = static_cast<float>(m23 * weapon);
  toughness = static_cast<float>(4.0 * m23 * (1.0 + 0.5 * affinity[static_cast<size_t>(Skill::DefenseGuarding)]));
  // Senses: ranges grow weakly with eye/head size (M^0.15).
  const double size_f = dmath::pow(std::max(0.1, static_cast<double>(mass_kg)), 0.15);
  vision_range_m = static_cast<float>((25.0 + 110.0 * vision) * size_f * 0.6);
  smell_range_m = static_cast<float>((10.0 + 70.0 * smell) * size_f * 0.6);
  hearing_range_m = static_cast<float>((15.0 + 90.0 * hearing) * size_f * 0.6);
  // Kleiber: mass-specific metabolic rate ~ M^-0.25 (hunger is per kg of reserve).
  metabolic_rate = static_cast<float>(dmath::pow(std::max(0.1, static_cast<double>(mass_kg)), -0.25));
  body_radius_m = std::max(0.1f, 0.25f * length_m);

  // Cognitive tier from ecology (social carnivores and highly curious social
  // species reach imitation; most others emulate; tiny solitary grazers only
  // show local enhancement). Documented in docs/design/07_cervello_creature.md.
  const float soc = instinct[static_cast<size_t>(Instinct::Sociability)];
  const float cur = instinct[static_cast<size_t>(Instinct::Curiosity)];
  int tier = 1;
  if (social == Social::Pack || (social == Social::Pair && diet == Diet::Carnivore)) tier = 3;
  else if (social == Social::Herd || social == Social::Pair || diet == Diet::Carnivore || diet == Diet::Omnivore) tier = 2;
  if (tier == 3 && soc > 0.8f && cur > 0.7f) tier = 4;
  if (tier == 2 && cur > 0.75f && soc > 0.6f) tier = 3;
  if (mass_kg < 0.5f && social != Social::Pack) tier = std::min(tier, 1);
  cognition_tier = tier;

  // ---- attachment / life history ----
  // Development time scales allometrically, t ~ M^0.25 (compressed game time).
  bonds.maturation_days = static_cast<float>(1.5 * dmath::pow(std::max(0.1, static_cast<double>(mass_kg)) / 25.0, 0.25));
  // Small animals lay more eggs per clutch (r-strategy), giants fewer (K).
  bonds.clutch = std::clamp(static_cast<int>(std::lround(3.0 * dmath::pow(25.0 / std::max(0.1, static_cast<double>(mass_kg)), 0.15))), 1, 5);
  switch (social) {
    case Social::Pack:
      bonds.parental_care = 0.9f; bonds.alloparental = true; bonds.pack_bond_gain = 0.03f;
      bonds.bond_decay_per_day = 0.02f; bonds.dispersal = 0.1f; break;
    case Social::Pair:
      bonds.parental_care = 0.8f; bonds.biparental = true; bonds.pack_bond_gain = 0.02f;
      bonds.bond_decay_per_day = 0.03f; bonds.dispersal = 0.7f; break;
    case Social::Herd:
      bonds.parental_care = 0.6f; bonds.pack_bond_gain = 0.008f; bonds.bond_decay_per_day = 0.04f; bonds.dispersal = 0.3f; break;
    case Social::Colony:
      bonds.parental_care = 0.5f; bonds.pack_bond_gain = 0.01f; bonds.bond_decay_per_day = 0.05f; bonds.dispersal = 0.4f; break;
    case Social::Swarm:
      bonds.parental_care = 0.1f; bonds.pack_bond_gain = 0.002f; bonds.bond_decay_per_day = 0.1f; bonds.dispersal = 1.f; break;
    case Social::Solitary:
      bonds.parental_care = 0.4f; bonds.pack_bond_gain = 0.f; bonds.bond_decay_per_day = 0.08f; bonds.dispersal = 1.f; break;
  }
  bonds.egg_imprinting = taming_method == "imprinting_egg";
  bonds.imprint_window_days = bonds.egg_imprinting ? 0.15f : 0.08f;
}

bool load_species(const std::string& path, std::vector<SpeciesProfile>& out, std::string* error) {
  json::ParseError pe;
  const auto doc = json::parse_file(path, &pe);
  if (!doc || !doc->is_array()) {
    if (error) *error = "species file: " + pe.message + " at line " + std::to_string(pe.line);
    return false;
  }
  out.clear();
  for (const json::Value& c : doc->arr()) {
    SpeciesProfile s;
    s.id = c.get_str("id");
    s.name = c.get_str("name");
    s.diet = diet_from_name(c.get_str("diet")).value_or(Diet::Herbivore);
    s.social = social_from_name(c["social"].get_str("structure")).value_or(Social::Solitary);
    s.group_min = static_cast<int>(c["social"]["group_size"][0].num(1));
    s.group_max = static_cast<int>(c["social"]["group_size"][1].num(1));
    s.mass_kg = static_cast<float>(c["size"].get("mass_kg", 1.0));
    s.length_m = static_cast<float>(c["size"].get("length_m", 1.0));
    s.height_m = static_cast<float>(c["size"].get("height_m", 0.5));
    for (const auto& l : c["locomotion"].arr()) {
      if (l.str() == "biped" || l.str() == "facultative_biped") s.biped = true;
      if (l.str() == "flyer" || l.str() == "glider") s.flyer = true;
      if (l.str() == "swimmer") s.swimmer = true;
      if (l.str() == "burrower") s.burrower = true;
    }
    for (int i = 0; i < kInstinctCount; ++i)
      s.instinct[i] = static_cast<float>(c["instincts"].get(instinct_name(static_cast<Instinct>(i)), 0.5));
    for (const auto& [k, v] : c["skill_affinity"].obj())
      if (auto sk = skill_from_name(k)) s.affinity[static_cast<size_t>(*sk)] = static_cast<float>(v.num());
    s.vision = static_cast<float>(c["senses"].get("vision", 0.5));
    s.smell = static_cast<float>(c["senses"].get("smell", 0.5));
    s.hearing = static_cast<float>(c["senses"].get("hearing", 0.5));
    s.tremor = static_cast<float>(c["senses"].get("tremor", 0.0));
    for (const auto& t : c["innate_techniques"].arr()) s.innate_techniques.push_back(t.str());
    s.taming_method = c["taming"].get_str("method");
    s.derive();
    out.push_back(std::move(s));
  }
  return true;
}

const SpeciesProfile* find_species(const std::vector<SpeciesProfile>& all, std::string_view id) {
  for (const auto& s : all)
    if (s.id == id) return &s;
  return nullptr;
}

}  // namespace primeva::brain
