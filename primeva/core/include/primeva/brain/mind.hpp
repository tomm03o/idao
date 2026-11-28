#pragma once

// The cognitive brain of a creature. ONE model for wild and tamed creatures:
// taming only adds an allegiance (owner, bond, obedience) and an extra reward
// channel (owner praise/scolding) - perception, needs, techniques, learning
// and social transmission are identical. A captured wild animal keeps what it
// learned in the wild; a tamed animal released goes on using what it learned.

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "primeva/brain/species.hpp"
#include "primeva/brain/technique.hpp"
#include "primeva/hash.hpp"

namespace primeva::brain {

inline constexpr int kContexts = 32;  // discrete situations for the contextual bandit

struct LearningParams {
  bool learning = true;          // master switch (control experiments)
  bool social = true;            // social transmission between creatures
  float eta_mastery = 0.05f;     // mastery step (individual)
  float eta_mastery_group = 0.03f;
  float gamma = 1.4f;            // diminishing returns exponent
  float eta_skill = 0.02f;
  float alpha0 = 0.30f, alpha_min = 0.05f, tau = 6.f;  // bandit step size schedule
  float beta_explore = 0.25f;    // UCB bonus scale (x curiosity)
  float temperature0 = 0.15f;    // soft selection temperature
  float inertia = 0.15f;         // commitment bonus for the running technique
  float switch_margin = 0.25f;   // hysteresis: switch only if the best beats the current by 25%
  float fidelity = 0.85f;        // per-generation transmission fidelity
  float owner_reward_weight = 1.0f;
  float discovery_scale = 1.0f;
};

enum class Source : uint8_t { Innate, Discovered, Observed, Player };

struct KnownTechnique {
  uint16_t tech = 0;
  Source source = Source::Innate;
  uint8_t generation = 0;        // transmission distance from the inventor (0 = innate/discovered)
  uint32_t teacher = 0;          // creature id it was learned from (knowledge genealogy)
  float mastery = 0.f, peak = 0.f;
  uint32_t uses = 0, successes = 0;
  std::array<float, kContexts> q{};      // value estimates per context, in [-1, 1]
  std::array<uint16_t, kContexts> n{};   // visit counts per context
};

// Typed social bonds. The primary attachment figure (parent, or owner for a
// creature imprinted on / raised by a player) is what a juvenile follows,
// watches most closely and learns from first.
enum class BondKind : uint8_t { Parent, Offspring, Mate, Packmate, Owner };

struct Bond {
  uint32_t other = 0;
  BondKind kind = BondKind::Packmate;
  float strength = 0.f;  // 0..1
};

enum class Transmission : uint8_t { Vertical, Horizontal, Oblique, FromOwner };

struct Exposure {                // partial social learning of a not-yet-known technique
  uint16_t tech = 0;
  uint16_t count = 0;
  uint32_t best_teacher = 0;
  uint8_t teacher_generation = 0;
  float best_factor = 0.f;
};

struct Mind {
  uint32_t id = 0;
  std::array<float, kInstinctCount> innate{};
  std::array<float, kInstinctCount> drift{};
  std::array<float, kSkillCount> skill{};
  std::vector<KnownTechnique> known;
  std::vector<Exposure> exposures;
  float hunger = 0.2f, thirst = 0.2f, fatigue = 0.1f, stress = 0.f;
  // life history
  bool juvenile = false;
  float age_days = 0.f;
  uint8_t sex = 0;               // 0 female, 1 male
  uint32_t mother = 0, father = 0;
  uint32_t generation = 0;       // genealogical generation (founders = 0)
  uint16_t dependents = 0;       // young currently depending on me (set by the host)
  // social bonds and attachment
  std::vector<Bond> bonds;
  uint32_t attachment = 0;       // primary attachment figure (creature id or owner id), 0 = none
  BondKind attachment_kind = BondKind::Parent;
  // allegiance (wild: owner == 0). `bond` is the bond with the owner.
  uint32_t owner = 0;
  float bond = 0.f;
  std::array<float, kCommandCount> obedience{};
  Command command = Command::None;
  Rng rng{1};

  float instinct(Instinct i) const {
    const float v = innate[static_cast<size_t>(i)] + drift[static_cast<size_t>(i)];
    return v < 0.f ? 0.f : (v > 1.f ? 1.f : v);
  }
  bool tamed() const { return owner != 0; }
  float bond_with(uint32_t other) const;
  // Adds `delta` to the bond with `other` (creating it with `kind` if absent).
  void strengthen(uint32_t other, BondKind kind, float delta);
  int known_index(uint16_t tech) const;
  float mastery_of(uint16_t tech) const;
};

// Builds a newborn/spawned mind: individual instinct variation around the
// species profile (+-0.08, deterministic from the seed) and innate techniques.
Mind make_mind(uint32_t id, const SpeciesProfile& sp, const TechniqueLibrary& lib, uint64_t seed);

// A newborn: innate instincts inherited from the parents (mean + small
// mutation), innate repertoire of the species, no learned techniques. Its
// knowledge must come from its own experience and from those it is bonded to.
Mind make_offspring(uint32_t id, const SpeciesProfile& sp, const TechniqueLibrary& lib, uint64_t seed, const Mind& mother,
                    const Mind* father, float mutation_sd = 0.03f);

bool can_use(const TechniqueDef& t, const SpeciesProfile& sp, const Mind& m);

struct Choice {
  int known_index = -1;
  float utility = 0.f;
  float current_utility = 0.f;  // utility of the running technique (for hysteresis)
  bool explored = false;        // chosen thanks to the exploration bonus
};

struct ScoredTechnique {
  int known_index = -1;
  float utility = 0.f, consideration = 0.f, instinct = 0.f, value = 0.f, command = 1.f, explore = 0.f;
};

// Utility of every usable known technique (for selection and for the UI
// "why did it do that?").
std::vector<ScoredTechnique> score_all(const Mind& m, const SpeciesProfile& sp, const TechniqueLibrary& lib, const Inputs& in,
                                       uint8_t ctx, int current_known, const LearningParams& p);
Choice choose(Mind& m, const SpeciesProfile& sp, const TechniqueLibrary& lib, const Inputs& in, uint8_t ctx, int current_known,
              const LearningParams& p);

// Episode outcome: r_intrinsic from the world (success, injury, energy) and
// r_owner from the owner's feedback (tamed only; 0 otherwise).
void learn_from_episode(Mind& m, const SpeciesProfile& sp, const TechniqueLibrary& lib, int known_index, uint8_t ctx,
                        float r_intrinsic, float r_owner, bool in_group, const LearningParams& p);

// Social learning: observer `o` watched a demonstrator perform `tech`.
// `attention` (0..1) comes from perception (distance, visibility, focus),
// `compat` from species / body-plan compatibility. Returns true when the
// observer acquired the technique this time.
bool observe(Mind& o, const SpeciesProfile& so, const TechniqueLibrary& lib, uint16_t tech, uint32_t teacher_id,
             float teacher_mastery, uint8_t teacher_generation, float attention, float compat, bool success,
             const LearningParams& p);

// Constrained innovation: may invent `tech` when its trigger context occurs.
bool try_discover(Mind& m, const SpeciesProfile& sp, const TechniqueLibrary& lib, uint16_t tech, const LearningParams& p);

// Forgetting of unused techniques (half-life in game days), with a floor at
// 35% of the peak so relearning is fast ("savings").
void forget(Mind& m, const TechniqueLibrary& lib, float days, const std::vector<uint32_t>& last_use_day, uint32_t today);

}  // namespace primeva::brain
