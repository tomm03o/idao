#include "primeva/brain/mind.hpp"

#include <algorithm>
#include <cmath>

#include "primeva/dmath.hpp"

namespace primeva::brain {

int Mind::known_index(uint16_t tech) const {
  for (size_t i = 0; i < known.size(); ++i)
    if (known[i].tech == tech) return static_cast<int>(i);
  return -1;
}

float Mind::mastery_of(uint16_t tech) const {
  const int k = known_index(tech);
  return k < 0 ? 0.f : known[static_cast<size_t>(k)].mastery;
}

float Mind::bond_with(uint32_t other) const {
  if (other != 0 && other == owner) return bond;
  for (const auto& b : bonds)
    if (b.other == other) return b.strength;
  return 0.f;
}

void Mind::strengthen(uint32_t other, BondKind kind, float delta) {
  if (other == 0 || other == id) return;
  if (other == owner) { bond = std::clamp(bond + delta, 0.f, 1.f); return; }
  for (auto& b : bonds)
    if (b.other == other) {
      b.strength = std::clamp(b.strength + delta, 0.f, 1.f);
      // a stronger relation kind (parent/offspring/mate) overrides "packmate"
      if (b.kind == BondKind::Packmate && kind != BondKind::Packmate) b.kind = kind;
      return;
    }
  if (delta > 0.f) bonds.push_back({other, kind, std::clamp(delta, 0.f, 1.f)});
}

bool can_use(const TechniqueDef& t, const SpeciesProfile& sp, const Mind& m) {
  if (!(t.diet_mask & (1u << static_cast<int>(sp.diet)))) return false;
  if (sp.cognition_tier < t.min_tier) return false;
  if (t.social_only && sp.social == Social::Solitary) return false;
  if (t.owned_only && !m.tamed()) return false;
  if (t.needs_attachment && m.attachment == 0) return false;
  if (t.parents_only && m.dependents == 0) return false;
  if (t.adults_only && m.juvenile) return false;
  for (int i = 0; i < kInstinctCount; ++i)
    if (t.gate[i] > 0.f && m.instinct(static_cast<Instinct>(i)) < t.gate[i]) return false;
  return true;
}

Mind make_mind(uint32_t id, const SpeciesProfile& sp, const TechniqueLibrary& lib, uint64_t seed) {
  Mind m;
  m.id = id;
  m.rng = Rng(hash_combine(seed, id));
  for (int i = 0; i < kInstinctCount; ++i)
    m.innate[i] = std::clamp(sp.instinct[i] + static_cast<float>(m.rng.uniform(-0.08, 0.08)), 0.f, 1.f);
  for (int s = 0; s < kSkillCount; ++s) m.skill[s] = 0.3f * sp.affinity[s];
  m.hunger = static_cast<float>(m.rng.uniform(0.1, 0.4));
  m.thirst = static_cast<float>(m.rng.uniform(0.1, 0.4));
  m.fatigue = static_cast<float>(m.rng.uniform(0.0, 0.3));

  // Innate repertoire = instinctive behaviours of the species. Cooperative
  // hunting, capture and other refined skills are NOT innate: they must be
  // discovered or learned socially (this is what the experiments measure).
  auto give = [&](std::string_view id_name, float base) {
    const int t = lib.find(id_name);
    if (t < 0) return;
    const TechniqueDef& d = lib[static_cast<size_t>(t)];
    if (!(d.diet_mask & (1u << static_cast<int>(sp.diet))) || sp.cognition_tier < d.min_tier) return;
    if (d.social_only && sp.social == Social::Solitary) return;
    KnownTechnique k;
    k.tech = static_cast<uint16_t>(t);
    k.source = Source::Innate;
    k.mastery = k.peak = std::clamp(base + 0.25f * sp.affinity[static_cast<size_t>(d.category)], 0.05f, 0.6f);
    m.known.push_back(k);
  };
  const bool herbivore = sp.diet == Diet::Herbivore || sp.diet == Diet::Omnivore;
  const bool predator = sp.diet == Diet::Carnivore || sp.diet == Diet::Omnivore || sp.diet == Diet::Piscivore;
  give("drink", 0.5f);
  give("rest", 0.5f);
  give("wander", 0.4f);
  give("flee", 0.3f);
  if (sp.social != Social::Solitary) give("regroup", 0.5f);
  if (herbivore) give("graze", 0.5f);
  if (herbivore && (sp.social == Social::Herd || sp.social == Social::Colony)) {
    give("alarm_call", 0.2f);
    if (sp.affinity[static_cast<size_t>(Skill::DefenseHerdCircle)] > 0.3f) give("herd_circle", 0.15f);
  }
  if (sp.affinity[static_cast<size_t>(Skill::DefenseGuarding)] >= 0.5f || sp.affinity[static_cast<size_t>(Skill::CombatMelee)] >= 0.6f)
    give("mob_charge", 0.15f);
  if (predator) {
    give("pursuit", 0.15f);
    give("scavenge", 0.4f);
    give("search_prey", 0.4f);
    if (sp.instinct[static_cast<size_t>(Instinct::Patience)] >= 0.3f || sp.affinity[static_cast<size_t>(Skill::HuntingAmbush)] >= 0.5f)
      give("stalk_ambush", 0.1f);
    if (sp.social == Social::Pack || sp.social == Social::Pair) give("join_hunt", 0.2f);
  }
  // Attachment and parental behaviours are instinctive in every species;
  // their availability is gated at use time (attachment figure, young).
  give("follow_attachment", 0.5f);
  give("guard_attachment", 0.2f);
  if (sp.bonds.parental_care >= 0.5f && predator) give("provision_young", 0.3f);
  if (sp.bonds.parental_care >= 0.3f) give("guard_young", 0.2f);
  return m;
}

Mind make_offspring(uint32_t id, const SpeciesProfile& sp, const TechniqueLibrary& lib, uint64_t seed, const Mind& mother,
                    const Mind* father, float mutation_sd) {
  Mind m = make_mind(id, sp, lib, seed);
  // Genetic inheritance of the innate instincts (not of the learned drift):
  // mid-parent value plus a small Gaussian-like mutation (Irwin-Hall of 3 uniforms).
  for (int i = 0; i < kInstinctCount; ++i) {
    const float mid = father ? 0.5f * (mother.innate[i] + father->innate[i]) : mother.innate[i];
    const double u = m.rng.uniform() + m.rng.uniform() + m.rng.uniform() - 1.5;  // var 0.25
    m.innate[i] = std::clamp(mid + static_cast<float>(u * 2.0 * mutation_sd), 0.f, 1.f);
    m.drift[i] = 0.f;
  }
  m.juvenile = true;
  m.age_days = 0.f;
  m.mother = mother.id;
  m.father = father ? father->id : 0;
  m.generation = std::max(mother.generation, father ? father->generation : 0u) + 1;
  m.hunger = 0.3f;
  m.thirst = 0.1f;
  m.fatigue = 0.f;
  for (auto& s : m.skill) s *= 0.5f;   // a hatchling's innate talent is still undeveloped
  for (auto& k : m.known)
    if (k.source == Source::Innate) k.mastery = k.peak = 0.6f * k.mastery;
  return m;
}

// ---------------------------------------------------------------------------
// Decision: Infinite-Axis Utility (Dave Mark) over known techniques.
// ---------------------------------------------------------------------------
std::vector<ScoredTechnique> score_all(const Mind& m, const SpeciesProfile& sp, const TechniqueLibrary& lib, const Inputs& in,
                                       uint8_t ctx, int current_known, const LearningParams& p) {
  std::vector<ScoredTechnique> out;
  out.reserve(m.known.size());
  uint32_t total_visits = 0;
  for (const auto& k : m.known) total_visits += k.n[ctx];
  const float curiosity = m.instinct(Instinct::Curiosity);
  const float fear = m.instinct(Instinct::Fear);
  const float health = in[static_cast<size_t>(Input::Health)];
  for (size_t ki = 0; ki < m.known.size(); ++ki) {
    const KnownTechnique& k = m.known[ki];
    const TechniqueDef& t = lib[k.tech];
    if (!can_use(t, sp, m)) continue;
    ScoredTechnique s;
    s.known_index = static_cast<int>(ki);
    // IAUS: product of considerations with compensation for their number.
    const size_t n = t.considerations.size();
    double c = 1.0;
    const double mod = n > 0 ? 1.0 - 1.0 / static_cast<double>(n) : 0.0;
    for (const auto& con : t.considerations) {
      double v = con.eval(in[static_cast<size_t>(con.input)]);
      v = v + (1.0 - v) * mod * v;  // make-up value
      c *= v;
    }
    s.consideration = static_cast<float>(c);
    // Instinct modulation: each weighted axis scales utility around 1.
    double inst = 1.0;
    for (int i = 0; i < kInstinctCount; ++i)
      if (t.weight[i] != 0.f) inst *= 1.0 + t.weight[i] * (m.instinct(static_cast<Instinct>(i)) - 0.5);
    s.instinct = static_cast<float>(std::clamp(inst, 0.2, 2.5));
    // Learned value of this technique in this context, and how well it is mastered.
    s.value = 0.5f + 0.5f * k.q[ctx];
    const float mastery_term = 0.6f + 0.4f * k.mastery;
    // Allegiance: an obeyed command raises matching techniques and damps the
    // others; survival behaviours (flee) are never suppressed.
    s.command = 1.f;
    if (m.tamed() && m.command != Command::None && t.executor != Executor::Flee) {
      const float ob = m.obedience[static_cast<size_t>(m.command)] * (0.4f + 0.6f * m.bond);
      if (t.command_mask & (1u << static_cast<int>(m.command))) s.command = 1.f + 3.f * ob;
      else s.command = 1.f - 0.7f * ob;
    }
    double u = t.base_weight * s.consideration * s.instinct * s.value * mastery_term * s.command;
    if (static_cast<int>(ki) == current_known) u *= 1.0 + p.inertia;
    // Exploration (UCB) - suppressed for risky techniques when afraid and hurt.
    if (s.consideration > 0.05f && !(t.risk > 0.5f && fear > 0.6f && health < 0.5f)) {
      s.explore = static_cast<float>(p.beta_explore * curiosity * s.consideration *
                                     std::sqrt(dmath::log(static_cast<double>(total_visits) + 2.0) / (k.n[ctx] + 1.0)));
    }
    s.utility = static_cast<float>(u) + s.explore;
    out.push_back(s);
  }
  return out;
}

Choice choose(Mind& m, const SpeciesProfile& sp, const TechniqueLibrary& lib, const Inputs& in, uint8_t ctx, int current_known,
              const LearningParams& p) {
  auto scored = score_all(m, sp, lib, in, ctx, current_known, p);
  Choice ch;
  if (scored.empty()) return ch;
  for (const auto& sc : scored)
    if (sc.known_index == current_known) ch.current_utility = sc.utility;
  std::sort(scored.begin(), scored.end(), [](const ScoredTechnique& a, const ScoredTechnique& b) {
    return a.utility != b.utility ? a.utility > b.utility : a.known_index < b.known_index;
  });
  // Soft selection among the top 3: temperature grows with curiosity and
  // collapses under stress (a terrified animal does not experiment).
  const size_t K = std::min<size_t>(3, scored.size());
  const double temp = std::max(1e-3, static_cast<double>(p.temperature0) * (0.5 + m.instinct(Instinct::Curiosity)) *
                                         (1.0 - 0.8 * std::clamp(static_cast<double>(m.stress), 0.0, 1.0)));
  double w[3], sum = 0.0;
  for (size_t i = 0; i < K; ++i) {
    // temperature is relative to the best utility (scale-free)
    w[i] = dmath::exp((scored[i].utility - scored[0].utility) / (temp * std::max(0.05f, scored[0].utility)));
    sum += w[i];
  }
  double r = m.rng.uniform() * sum;
  size_t pick = 0;
  for (size_t i = 0; i < K; ++i) {
    if (r < w[i]) { pick = i; break; }
    r -= w[i];
    pick = i;
  }
  ch.known_index = scored[pick].known_index;
  ch.utility = scored[pick].utility;
  ch.explored = scored[pick].explore > 0.5f * scored[pick].utility;
  return ch;
}

// ---------------------------------------------------------------------------
// Learning
// ---------------------------------------------------------------------------
void learn_from_episode(Mind& m, const SpeciesProfile& sp, const TechniqueLibrary& lib, int known_index, uint8_t ctx,
                        float r_intrinsic, float r_owner, bool in_group, const LearningParams& p) {
  if (known_index < 0 || static_cast<size_t>(known_index) >= m.known.size()) return;
  KnownTechnique& k = m.known[static_cast<size_t>(known_index)];
  const TechniqueDef& t = lib[k.tech];
  ++k.uses;
  if (r_intrinsic > 0.f) ++k.successes;

  // Owner feedback matters in proportion to the bond (and to how receptive
  // the species is socially).
  const float receptivity = 0.5f + 0.5f * m.instinct(Instinct::Sociability);
  const float r_own = m.tamed() ? r_owner * (0.3f + 0.7f * m.bond) * receptivity * p.owner_reward_weight : 0.f;
  const float r = std::clamp(r_intrinsic + r_own, -1.f, 1.f);

  // Allegiance dynamics (also when learning is frozen: they are not skills).
  if (m.tamed()) {
    if (r_owner > 0.f) m.bond = std::min(1.f, m.bond + 0.02f * (1.f - m.bond));
    if (r_owner < 0.f) m.bond = std::max(0.f, m.bond - 0.01f);
    if (m.command != Command::None && (t.command_mask & (1u << static_cast<int>(m.command)))) {
      float& ob = m.obedience[static_cast<size_t>(m.command)];
      if (r_owner > 0.f) ob = std::min(1.f, ob + 0.04f * (1.f - ob));
    }
  }
  if (!p.learning) return;

  // Contextual bandit: q <- q + alpha_n (r - q). Patient creatures revise more slowly.
  {
    uint16_t& n = k.n[ctx];
    const float patience = m.instinct(Instinct::Patience);
    const float alpha = std::max(p.alpha_min, p.alpha0 / (1.f + static_cast<float>(n) / p.tau)) * (1.3f - 0.6f * patience);
    k.q[ctx] += alpha * (r - k.q[ctx]);
    if (n < 65535) ++n;
  }
  // Routine behaviours (difficulty 0: drinking, resting...) have values but no skill to master.
  if (t.difficulty <= 0.f) return;

  // Mastery: practice with diminishing returns, modulated by innate talent
  // (affinity) for the category; failures that are "instructive" still teach.
  const float talent = 0.6f + 0.8f * sp.affinity[static_cast<size_t>(t.category)];
  const float eta = in_group ? p.eta_mastery_group : p.eta_mastery;
  const float r_eff = r + (r < 0.f && r > -0.6f ? 0.25f : 0.f);
  float dm = eta * static_cast<float>(dmath::pow(1.0 - k.mastery, p.gamma)) * std::max(r_eff, 0.f) * talent;
  if (r < 0.f) dm -= 0.15f * 0.15f * k.mastery * (-r);
  k.mastery = std::clamp(k.mastery + dm, 0.f, 1.f);
  k.peak = std::max(k.peak, k.mastery);

  // Skill level of the category.
  float& lvl = m.skill[static_cast<size_t>(t.category)];
  const float q = r > 0.3f ? 1.f : (r > -0.3f ? 0.35f : 0.1f);
  const float fatigue_factor = 1.f - 0.7f * m.fatigue;
  lvl = std::clamp(lvl + p.eta_skill * static_cast<float>(dmath::pow(1.0 - lvl, 1.4)) * q * talent * fatigue_factor, 0.f, 1.f);

  // Personality drift (bounded): winning fights -> bolder; being hurt -> warier.
  const float cap = m.tamed() ? 0.25f : 0.15f;
  auto nudge = [&](Instinct a, float d) {
    float& x = m.drift[static_cast<size_t>(a)];
    x = std::clamp(x + d, -cap, cap);
  };
  if (t.is_hunt() || t.executor == Executor::MobCharge) {
    if (r > 0.5f) { nudge(Instinct::Aggression, 0.002f); nudge(Instinct::Fear, -0.001f); }
    if (r < -0.5f) { nudge(Instinct::Fear, 0.003f); }
  }
  if (m.tamed() && r_owner > 0.f) nudge(Instinct::Sociability, 0.001f);
}

bool observe(Mind& o, const SpeciesProfile& so, const TechniqueLibrary& lib, uint16_t tech, uint32_t teacher_id,
             float teacher_mastery, uint8_t teacher_generation, float attention, float compat, bool success,
             const LearningParams& p) {
  if (!p.social || !p.learning) return false;
  const TechniqueDef& t = lib[tech];
  if (!(t.diet_mask & (1u << static_cast<int>(so.diet))) || so.cognition_tier < t.min_tier) return false;
  if (t.social_only && so.social == Social::Solitary) return false;
  static constexpr float kCognitionGain[5] = {0.f, 0.15f, 0.35f, 0.6f, 0.8f};
  const float fidelity = static_cast<float>(dmath::pow(p.fidelity, teacher_generation));
  const float teacher_factor = (0.3f + 0.7f * teacher_mastery * fidelity) * (success ? 1.f : 0.4f);
  const float p_obs = std::clamp(attention * teacher_factor * compat * kCognitionGain[std::clamp(so.cognition_tier, 0, 4)] * 2.5f,
                                 0.f, 1.f);

  const int ki = o.known_index(tech);
  if (ki >= 0) {
    // Already known: watching an expert still refines it a little (mastery
    // pulled toward the demonstrator's), the "apprenticeship" effect.
    KnownTechnique& k = o.known[static_cast<size_t>(ki)];
    if (teacher_mastery > k.mastery && o.rng.uniform() < p_obs)
      k.mastery = std::min(teacher_mastery, k.mastery + 0.02f * (teacher_mastery - k.mastery) * 4.f);
    return false;
  }
  if (o.rng.uniform() >= p_obs) return false;

  Exposure* e = nullptr;
  for (auto& ex : o.exposures)
    if (ex.tech == tech) { e = &ex; break; }
  if (!e) {
    o.exposures.push_back({tech, 0, 0, 0, 0.f});
    e = &o.exposures.back();
  }
  ++e->count;
  if (teacher_factor * compat > e->best_factor) {
    e->best_factor = teacher_factor * compat;
    e->best_teacher = teacher_id;
    e->teacher_generation = teacher_generation;
  }
  // Stages: familiar (>=3) -> emulating -> acquired. Imitation (acquiring the
  // means, not just the goal) needs cognition tier >= 3; tier-2 species only
  // acquire through their own trial after many exposures (emulation).
  const int needed = so.cognition_tier >= 3 ? 4 : (so.cognition_tier == 2 ? 8 : 1000000);
  if (e->count < needed) return false;
  KnownTechnique k;
  k.tech = tech;
  k.source = Source::Observed;
  k.teacher = e->best_teacher;
  k.generation = static_cast<uint8_t>(std::min(255, e->teacher_generation + 1));
  k.mastery = k.peak = std::min(0.45f, 0.10f + 0.35f * e->best_factor);
  o.known.push_back(k);
  o.exposures.erase(o.exposures.begin() + (e - o.exposures.data()));
  return true;
}

bool try_discover(Mind& m, const SpeciesProfile& sp, const TechniqueLibrary& lib, uint16_t tech, const LearningParams& p) {
  if (!p.learning || m.known_index(tech) >= 0) return false;
  const TechniqueDef& t = lib[tech];
  if (t.discover_p <= 0.f || !can_use(t, sp, m)) return false;
  static constexpr float kTierFactor[5] = {0.f, 0.4f, 0.7f, 1.0f, 1.2f};
  const float pd = t.discover_p * p.discovery_scale * m.instinct(Instinct::Curiosity) * (0.5f + m.instinct(Instinct::Playfulness)) *
                   kTierFactor[std::clamp(sp.cognition_tier, 0, 4)];
  if (m.rng.uniform() >= pd) return false;
  KnownTechnique k;
  k.tech = tech;
  k.source = Source::Discovered;
  k.mastery = k.peak = 0.1f;
  m.known.push_back(k);
  return true;
}

void forget(Mind& m, const TechniqueLibrary& lib, float days, const std::vector<uint32_t>& last_use_day, uint32_t today) {
  (void)lib;
  for (size_t i = 0; i < m.known.size(); ++i) {
    KnownTechnique& k = m.known[i];
    if (k.source == Source::Innate) continue;
    const uint32_t last = i < last_use_day.size() ? last_use_day[i] : today;
    if (today <= last) continue;
    const double half_life = 30.0 * (0.6 + 0.8 * k.peak) * (1.0 + 0.5 * m.instinct(Instinct::Patience));
    const float decayed = k.mastery * static_cast<float>(dmath::pow(0.5, days / half_life));
    k.mastery = std::max(decayed, 0.35f * k.peak);
  }
}

}  // namespace primeva::brain
