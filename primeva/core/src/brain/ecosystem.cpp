#include "primeva/brain/ecosystem.hpp"

#include <algorithm>
#include <cmath>

#include "primeva/dmath.hpp"

namespace primeva::brain {

namespace {
constexpr double kPi = 3.14159265358979323846;
inline double dist(double ax, double az, double bx, double bz) { return std::sqrt((ax - bx) * (ax - bx) + (az - bz) * (az - bz)); }
inline float clamp01(double v) { return static_cast<float>(std::clamp(v, 0.0, 1.0)); }
bool is_herbivore(Diet d) { return d == Diet::Herbivore; }
bool is_predator(Diet d) { return d == Diet::Carnivore || d == Diet::Omnivore || d == Diet::Piscivore; }

// Ground speed for a gait, relative to the species' physiology.
double gait_speed(const SpeciesProfile& s, Gait g) {
  switch (g) {
    case Gait::Stand: return 0.0;
    case Gait::Sneak: return 0.35 * s.cruise_speed;
    case Gait::Walk: return s.cruise_speed;
    case Gait::Trot: return 0.5 * (s.cruise_speed + s.sprint_speed) * 0.7;
    case Gait::Run: return 0.75 * s.sprint_speed;
    case Gait::Sprint: return s.sprint_speed;
  }
  return 0.0;
}
// Noise emitted by a gait (hearing detection) and visual conspicuousness.
float gait_noise(Gait g) {
  switch (g) {
    case Gait::Stand: return 0.05f;
    case Gait::Sneak: return 0.08f;
    case Gait::Walk: return 0.3f;
    case Gait::Trot: return 0.5f;
    case Gait::Run: return 0.75f;
    case Gait::Sprint: return 1.0f;
  }
  return 0.3f;
}
}  // namespace

Ecosystem::Ecosystem(EcoConfig cfg, const std::vector<SpeciesProfile>& species, const TechniqueLibrary& lib)
    : cfg_(cfg), species_(species), lib_(lib), rng_(cfg.seed) {
  veg_n_ = static_cast<int>(std::ceil(cfg_.size_m / cfg_.veg_cell_m));
  veg_.resize(static_cast<size_t>(veg_n_) * veg_n_);
  for (int j = 0; j < veg_n_; ++j)
    for (int i = 0; i < veg_n_; ++i) {
      // patchy vegetation: dense thickets (cover for stalkers) and open ground
      const double v = 0.5 + 0.5 * std::sin(i * 0.37 + rng_.uniform() * 0.6) * std::cos(j * 0.29 + rng_.uniform() * 0.6);
      veg_[static_cast<size_t>(j) * veg_n_ + i] = clamp01(0.3 + 0.7 * v);
    }
  for (int k = 0; k < cfg_.water_points; ++k)
    water_.push_back({rng_.uniform(0.15, 0.85) * cfg_.size_m, rng_.uniform(0.15, 0.85) * cfg_.size_m});
  grid_n_ = static_cast<int>(std::ceil(cfg_.size_m / cell_));
  grid_.resize(static_cast<size_t>(grid_n_) * grid_n_);
  day_.per_tech.resize(lib_.size());
}

// Social species travel as a unit: the group shares one waypoint, renewed
// when the group reaches it or it gets stale. Solitary animals pick their own.
void Ecosystem::group_waypoint(Agent& a, double radius) {
  const SpeciesProfile& s = sp(a);
  auto pick = [&](double& x, double& z) {
    x = std::clamp(a.home_x + a.mind.rng.uniform(-radius, radius), 5.0, cfg_.size_m - 5);
    z = std::clamp(a.home_z + a.mind.rng.uniform(-radius, radius), 5.0, cfg_.size_m - 5);
  };
  if (s.social == Social::Solitary) {
    double x, z;
    pick(x, z);
    a.tx = static_cast<float>(x);
    a.tz = static_cast<float>(z);
    return;
  }
  const size_t g = static_cast<size_t>(a.group);
  const bool reached = g < group_cx_.size() && dist(group_cx_[g], group_cz_[g], group_wx_[g], group_wz_[g]) < 15.0;
  if (reached || t_ - group_wt_[g] > 240.0) {
    pick(group_wx_[g], group_wz_[g]);
    group_wt_[g] = t_;
  }
  // individual offset keeps members spread a few metres apart
  a.tx = static_cast<float>(group_wx_[g] + 4.0 * std::cos(a.id * 2.39996));
  a.tz = static_cast<float>(group_wz_[g] + 4.0 * std::sin(a.id * 2.39996));
}

float Ecosystem::growth(const Agent& a) const {
  if (!a.mind.juvenile) return 1.f;
  const float mat = sp(a).bonds.maturation_days;
  return 0.35f + 0.65f * std::min(1.f, a.mind.age_days / std::max(0.05f, mat));
}

bool Ecosystem::is_dependent_of(const Agent& young, const Agent& adult) const {
  if (!young.alive || !young.mind.juvenile || young.group != adult.group || adult.mind.juvenile) return false;
  if (young.mind.mother == adult.id || young.mind.father == adult.id) return true;
  return sp(adult).bonds.alloparental;  // packs raise their young together
}

// Position of the creature's primary attachment figure (a creature or its owner).
bool Ecosystem::attachment_pos(const Agent& a, double& x, double& z, bool& alive) const {
  alive = false;
  if (a.mind.attachment == 0) return false;
  if (a.mind.attachment == a.mind.owner && a.mind.owner != 0) {
    for (const auto& o : owners_)
      if (o.id == a.mind.owner) { x = o.x; z = o.z; alive = true; return true; }
    return false;
  }
  if (a.mind.attachment >= index_of_id_.size()) return false;
  const Agent& f = agents_[index_of_id_[a.mind.attachment]];
  x = f.x; z = f.z; alive = f.alive;
  return true;
}

Agent* Ecosystem::agent(uint32_t id) {
  if (id == 0 || id >= index_of_id_.size()) return nullptr;
  return &agents_[index_of_id_[id]];
}

Agent Ecosystem::spawn(int species, int group, double x, double z, bool juvenile) {
  Agent a;
  a.id = next_id_++;
  a.species = species;
  a.group = group;
  a.x = std::clamp(x, 5.0, cfg_.size_m - 5.0);
  a.z = std::clamp(z, 5.0, cfg_.size_m - 5.0);
  a.home_x = a.x;
  a.home_z = a.z;
  a.juvenile = juvenile;
  a.mind = make_mind(a.id, species_[static_cast<size_t>(species)], lib_, cfg_.seed);
  a.next_decision = t_ + (a.id % 4) * 0.125;
  a.last_novel = t_;
  return a;
}

int Ecosystem::add_group(const std::string& species_id, int count, double x, double z) {
  int si = -1;
  for (size_t i = 0; i < species_.size(); ++i)
    if (species_[i].id == species_id) si = static_cast<int>(i);
  if (si < 0) return -1;
  const int g = static_cast<int>(group_species_.size());
  group_species_.push_back(si);
  group_hunts_.emplace_back();
  group_wx_.push_back(x);
  group_wz_.push_back(z);
  group_wt_.push_back(-1e9);
  if (initial_population_.size() < species_.size()) initial_population_.resize(species_.size(), 0);
  initial_population_[static_cast<size_t>(si)] += count;
  for (int k = 0; k < count; ++k) {
    Agent a = spawn(si, g, x + rng_.uniform(-15, 15), z + rng_.uniform(-15, 15), false);
    a.mind.sex = static_cast<uint8_t>(k % 2);
    a.mind.age_days = species_[static_cast<size_t>(si)].bonds.maturation_days * static_cast<float>(1.0 + rng_.uniform(0.0, 2.0));
    a.last_breed = -rng_.uniform(0.0, 1.0) * cfg_.day_s;
    if (index_of_id_.size() <= a.id) index_of_id_.resize(a.id + 1);
    index_of_id_[a.id] = static_cast<uint32_t>(agents_.size());
    agents_.push_back(std::move(a));
  }
  return g;
}

uint32_t Ecosystem::add_owner(double x, double z, Trainer trainer) {
  Owner o;
  o.id = 1000000u + static_cast<uint32_t>(owners_.size());
  o.x = x;
  o.z = z;
  o.trainer = trainer;
  owners_.push_back(o);
  return o.id;
}

void Ecosystem::tame_group(int group, uint32_t owner_id, Command command, float initial_bond) {
  for (auto& o : owners_) {
    if (o.id != owner_id) continue;
    o.command = command;
    for (auto& a : agents_) {
      if (a.group != group || !a.alive) continue;
      a.mind.owner = owner_id;
      a.mind.bond = initial_bond;
      a.mind.attachment = owner_id;   // a tamed adult adopts its owner as attachment figure
      a.mind.attachment_kind = BondKind::Owner;
      a.mind.command = command;
      a.mind.obedience.fill(0.3f);
      o.creatures.push_back(a.id);
    }
  }
}

void Ecosystem::teach(uint32_t agent_id, const std::string& tech, float mastery, Source source) {
  Agent* a = agent(agent_id);
  const int t = lib_.find(tech);
  if (!a || t < 0 || a->mind.known_index(static_cast<uint16_t>(t)) >= 0) return;
  KnownTechnique k;
  k.tech = static_cast<uint16_t>(t);
  k.source = source;
  k.mastery = k.peak = mastery;
  a->mind.known.push_back(k);
}

void Ecosystem::watch_species(const std::string& species_id) {
  for (size_t i = 0; i < species_.size(); ++i)
    if (species_[i].id == species_id) watched_ = static_cast<int>(i);
}

// ---------------------------------------------------------------------------
// Spatial queries
// ---------------------------------------------------------------------------
void Ecosystem::rebuild_grid() {
  for (auto& c : grid_) c.clear();
  const size_t ng = group_species_.size();
  group_alive_.assign(ng, 0);
  group_cx_.assign(ng, 0.0);
  group_cz_.assign(ng, 0.0);
  for (size_t i = 0; i < agents_.size(); ++i) {
    const Agent& a = agents_[i];
    if (!a.alive) continue;
    ++group_alive_[static_cast<size_t>(a.group)];
    group_cx_[static_cast<size_t>(a.group)] += a.x;
    group_cz_[static_cast<size_t>(a.group)] += a.z;
    const int gx = std::clamp(static_cast<int>(a.x / cell_), 0, grid_n_ - 1);
    const int gz = std::clamp(static_cast<int>(a.z / cell_), 0, grid_n_ - 1);
    grid_[static_cast<size_t>(gz) * grid_n_ + gx].push_back(static_cast<uint32_t>(i));
  }
  for (size_t g = 0; g < ng; ++g)
    if (group_alive_[g] > 0) { group_cx_[g] /= group_alive_[g]; group_cz_[g] /= group_alive_[g]; }
  group_juveniles_.assign(ng, {});
  for (const auto& a : agents_)
    if (a.alive && a.mind.juvenile) group_juveniles_[static_cast<size_t>(a.group)].push_back(a.id);
  // dependents: young that rely on each adult (own offspring, or the whole
  // group's young for alloparental packs)
  for (auto& a : agents_) {
    if (!a.alive) continue;
    a.mind.dependents = 0;
    if (a.mind.juvenile) continue;
    for (uint32_t yid : group_juveniles_[static_cast<size_t>(a.group)])
      if (is_dependent_of(agents_[index_of_id_[yid]], a)) ++a.mind.dependents;
  }
}

template <typename F>
void Ecosystem::for_near(double x, double z, double r, F&& f) {
  const int x0 = std::clamp(static_cast<int>((x - r) / cell_), 0, grid_n_ - 1), x1 = std::clamp(static_cast<int>((x + r) / cell_), 0, grid_n_ - 1);
  const int z0 = std::clamp(static_cast<int>((z - r) / cell_), 0, grid_n_ - 1), z1 = std::clamp(static_cast<int>((z + r) / cell_), 0, grid_n_ - 1);
  for (int gz = z0; gz <= z1; ++gz)
    for (int gx = x0; gx <= x1; ++gx)
      for (uint32_t i : grid_[static_cast<size_t>(gz) * grid_n_ + gx]) {
        Agent& b = agents_[i];
        if (b.alive && dist(x, z, b.x, b.z) <= r) f(b);
      }
}

int Ecosystem::packmates_near(const Agent& a, double r) const {
  int n = 0;
  const int x0 = std::clamp(static_cast<int>((a.x - r) / cell_), 0, grid_n_ - 1), x1 = std::clamp(static_cast<int>((a.x + r) / cell_), 0, grid_n_ - 1);
  const int z0 = std::clamp(static_cast<int>((a.z - r) / cell_), 0, grid_n_ - 1), z1 = std::clamp(static_cast<int>((a.z + r) / cell_), 0, grid_n_ - 1);
  for (int gz = z0; gz <= z1; ++gz)
    for (int gx = x0; gx <= x1; ++gx)
      for (uint32_t i : grid_[static_cast<size_t>(gz) * grid_n_ + gx]) {
        const Agent& b = agents_[i];
        if (b.id != a.id && b.alive && b.group == a.group && dist(a.x, a.z, b.x, b.z) <= r) ++n;
      }
  return n;
}

// ---------------------------------------------------------------------------
// Perception: vision (cover, conspicuousness), hearing (gait noise), smell.
// ---------------------------------------------------------------------------
void Ecosystem::perceive(Agent& a) {
  const SpeciesProfile& s = sp(a);
  const double range = std::max({s.vision_range_m, s.hearing_range_m, s.smell_range_m});
  // forget stale memories (10 s)
  a.seen.erase(std::remove_if(a.seen.begin(), a.seen.end(), [&](const Agent::Seen& m) { return t_ - m.t > 10.0; }), a.seen.end());
  for_near(a.x, a.z, range, [&](Agent& b) {
    if (b.id == a.id) return;
    const double d = dist(a.x, a.z, b.x, b.z);
    const SpeciesProfile& sb = sp(b);
    // target conspicuousness: size, movement, cover, stalking skill
    const int vi = std::clamp(static_cast<int>(b.x / cfg_.veg_cell_m), 0, veg_n_ - 1);
    const int vj = std::clamp(static_cast<int>(b.z / cfg_.veg_cell_m), 0, veg_n_ - 1);
    const float cover = veg_[static_cast<size_t>(vj) * veg_n_ + vi];
    float vis = std::clamp(0.4f + 0.3f * std::log10(std::max(1.f, sb.mass_kg)), 0.3f, 1.3f);
    if (b.cmd.gait == Gait::Sneak) {
      const int k = b.current >= 0 ? b.current : -1;
      const float m = k >= 0 ? b.mind.known[static_cast<size_t>(k)].mastery : 0.f;
      vis *= 0.35f * (1.f - 0.5f * m) * (1.f - 0.5f * cover);
    }
    const double pv = s.vision * vis * std::max(0.0, 1.0 - d / s.vision_range_m);
    const double ph = s.hearing * gait_noise(b.cmd.gait) * std::max(0.0, 1.0 - d / s.hearing_range_m);
    const double ps = s.smell * 0.5 * std::max(0.0, 1.0 - d / s.smell_range_m);
    const double p = 1.0 - (1.0 - pv) * (1.0 - ph) * (1.0 - ps);
    const bool known_already = std::any_of(a.seen.begin(), a.seen.end(), [&](const Agent::Seen& m) { return m.id == b.id; });
    // already-tracked targets stay tracked at higher probability (attention)
    if (a.mind.rng.uniform() < (known_already ? std::min(1.0, p * 3.0 + 0.2) : p * 0.9)) {
      bool updated = false;
      for (auto& m : a.seen)
        if (m.id == b.id) {
          m = {b.id, static_cast<float>(b.x), static_cast<float>(b.z), static_cast<float>(b.vx), static_cast<float>(b.vz), t_};
          updated = true;
        }
      if (!updated)
        a.seen.push_back({b.id, static_cast<float>(b.x), static_cast<float>(b.z), static_cast<float>(b.vx), static_cast<float>(b.vz), t_});
    }
  });
}

float Ecosystem::prey_value(const Agent& hunter, const Agent& prey, int packmates) const {
  const SpeciesProfile& sh = sp(hunter);
  const SpeciesProfile& spy = sp(prey);
  if (!is_herbivore(spy.diet) || !prey.alive) return 0.f;
  if (hunter.mind.tamed() && prey.mind.owner == hunter.mind.owner) return 0.f;
  // Suitability peaks when the prey is within the group's subduing capacity.
  const double g = growth(hunter);
  const double capacity = sh.mass_kg * g * g * g * (1.0 + 0.8 * packmates) * 1.2;
  const double lr = std::log2(spy.mass_kg / capacity);
  const double suit = dmath::exp(-(lr * lr) / 2.0);
  const double vulnerable = (1.0 - 0.5 * prey.health) + (prey.captured_until > t_ ? 0.5 : 0.0);
  return clamp01(suit * vulnerable);
}

Inputs Ecosystem::compute_inputs(Agent& a, uint32_t& best_prey, uint8_t& ctx) {
  const SpeciesProfile& s = sp(a);
  Inputs in{};
  in[static_cast<size_t>(Input::Hunger)] = a.mind.hunger;
  in[static_cast<size_t>(Input::Thirst)] = a.mind.thirst;
  in[static_cast<size_t>(Input::Fatigue)] = a.mind.fatigue;
  in[static_cast<size_t>(Input::Health)] = a.health;
  in[static_cast<size_t>(Input::Stamina)] = a.stamina;
  in[static_cast<size_t>(Input::Boredom)] = clamp01((t_ - a.last_novel) / 900.0);

  const int pack = packmates_near(a, 40.0);
  const int group_total = group_alive_[static_cast<size_t>(a.group)] - 1;
  int herd_close = 0;
  for_near(a.x, a.z, 20.0, [&](Agent& b) { herd_close += (b.id != a.id && b.group == a.group) ? 1 : 0; });
  in[static_cast<size_t>(Input::HerdNear)] = group_total > 0 ? clamp01(static_cast<double>(herd_close) / std::min(group_total, 6)) : 0.f;
  in[static_cast<size_t>(Input::Packmates)] = clamp01(pack / 4.0);
  in[static_cast<size_t>(Input::Alone)] = (s.social == Social::Solitary || group_total == 0) ? 0.f : clamp01(1.0 - pack / 2.0);

  // Threats and prey from perception memory.
  float threat = 0.f, prey_q = 0.f, prey_near = 0.f, threat_weaker = 0.f;
  uint32_t threat_id = 0;
  best_prey = 0;
  float best_prey_mass = 0.f;
  for (const auto& m : a.seen) {
    Agent* b = agent(m.id);
    if (!b || !b->alive) continue;
    const SpeciesProfile& sb = sp(*b);
    const double d = dist(a.x, a.z, m.x, m.z);
    if (is_predator(sb.diet) && b->group != a.group && !(a.mind.tamed() && b->mind.owner == a.mind.owner)) {
      // danger: can that predator (with its pack) seriously hurt me?
      const int their_pack = 1 + packmates_near(*b, 40.0);
      const double power = sb.attack * growth(*b) * growth(*b) * their_pack;
      const double danger = std::clamp(power / (s.toughness * growth(a) * growth(a) * 0.12), 0.0, 1.0) *
                            dmath::pow(std::max(0.0, 1.0 - d / (s.vision_range_m * 1.2)), 0.7);
      if (danger > threat) {
        threat = static_cast<float>(danger);
        threat_id = b->id;
        a.threat_x = m.x;
        a.threat_z = m.z;
        threat_weaker = clamp01((s.mass_kg * (1 + pack)) / (sb.mass_kg * their_pack) - 0.8);
      }
    }
    if (is_predator(s.diet)) {
      const float v = prey_value(a, *b, pack);
      const float near = clamp01(1.0 - d / s.vision_range_m);
      const float score = v * (0.5f + 0.5f * near);
      if (score > prey_q) {
        prey_q = score;
        prey_near = near;
        best_prey = b->id;
        best_prey_mass = sb.mass_kg;
      }
    }
  }
  // Large herbivores charging me are threats to predators too.
  if (threat > 0.15f) {
    a.last_threat_seen = t_;
    if (a.threat_id != threat_id) { a.threat_since = t_; a.called_alarm = false; }
  }
  a.threat = threat;
  a.threat_id = threat_id;
  in[static_cast<size_t>(Input::Threat)] = threat;
  in[static_cast<size_t>(Input::ThreatWeaker)] = threat_weaker;
  in[static_cast<size_t>(Input::ThreatNew)] = (threat > 0.2f && !a.called_alarm && t_ - a.threat_since < 3.0) ? 1.f : 0.f;
  in[static_cast<size_t>(Input::PreyQuality)] = prey_q;
  in[static_cast<size_t>(Input::PreyNear)] = prey_near;

  float carcass = 0.f;
  for (const auto& c : carcasses_)
    if (c.meat_kg > 0.5f) carcass = std::max(carcass, clamp01(1.0 - dist(a.x, a.z, c.x, c.z) / std::max(30.0, static_cast<double>(s.smell_range_m) * 1.5)));
  in[static_cast<size_t>(Input::CarcassNear)] = carcass;

  const GroupHunt& gh = group_hunts_[static_cast<size_t>(a.group)];
  Agent* ght = agent(gh.target);
  in[static_cast<size_t>(Input::GroupHuntActive)] =
      (gh.started >= 0 && ght && ght->alive && gh.leader != a.id && dist(a.x, a.z, ght->x, ght->z) < 150.0) ? 1.f : 0.f;

  // Attachment figure (parent or owner): how far, and whether it is threatened.
  in[static_cast<size_t>(Input::Juvenile)] = a.mind.juvenile ? 1.f : 0.f;
  double axp = 0, azp = 0;
  bool att_alive = false;
  if (attachment_pos(a, axp, azp, att_alive) && att_alive) {
    const double range = a.mind.juvenile ? 20.0 : 40.0;
    in[static_cast<size_t>(Input::AttachmentFar)] = clamp01(dist(a.x, a.z, axp, azp) / range);
    float at = 0.f;
    for_near(axp, azp, 25.0, [&](Agent& b) {
      if (is_predator(sp(b).diet) && b.group != a.group && !(a.mind.tamed() && b.mind.owner == a.mind.owner)) at = 1.f;
    });
    in[static_cast<size_t>(Input::AttachmentThreat)] = at;
  }
  // Parents: state of the young that depend on me.
  if (a.mind.dependents > 0) {
    float yh = 0.f, yt = 0.f, yn = 0.f;
    for (uint32_t yid : group_juveniles_[static_cast<size_t>(a.group)]) {
      const Agent& y = agents_[index_of_id_[yid]];
      if (!is_dependent_of(y, a)) continue;
      const double d = dist(a.x, a.z, y.x, y.z);
      if (d > 250.0) continue;
      yh = std::max(yh, y.mind.hunger);
      yt = std::max(yt, y.threat);
      if (d < 30.0) yn = 1.f;
    }
    in[static_cast<size_t>(Input::YoungHungry)] = yh;
    in[static_cast<size_t>(Input::YoungThreat)] = yt;
    in[static_cast<size_t>(Input::YoungNear)] = yn;
  }

  // Context for the bandit: prey size class x pack bucket x tamed.
  int size_class = 0;
  if (best_prey) {
    const double r = best_prey_mass / s.mass_kg;
    size_class = r < 0.5 ? 0 : (r < 1.5 ? 1 : (r < 4.0 ? 2 : 3));
  }
  const int pack_bucket = pack == 0 ? 0 : (pack <= 2 ? 1 : 2);
  ctx = static_cast<uint8_t>(size_class * 6 + pack_bucket * 2 + (a.mind.tamed() ? 1 : 0));
  a.mind.stress = std::max(threat, a.mind.hunger > 0.9f ? 0.5f : 0.f);
  return in;
}

// ---------------------------------------------------------------------------
// Decision and episodes
// ---------------------------------------------------------------------------
void Ecosystem::decide(Agent& a) {
  ++decisions_;
  perceive(a);
  uint32_t prey = 0;
  uint8_t ctx = 0;
  const Inputs in = compute_inputs(a, prey, ctx);
  const SpeciesProfile& s = sp(a);
  const Choice ch = choose(a.mind, s, lib_, in, ctx, a.current, cfg_.learn);
  if (ch.known_index < 0) return;
  if (ch.known_index == a.current) return;  // keep going (commitment)
  // Hysteresis: animals persist in what they are doing unless something
  // clearly better (or urgent) comes up; prevents dithering between options.
  if (a.current >= 0 && ch.current_utility > 0.02f &&
      ch.utility < ch.current_utility * (1.f + cfg_.learn.switch_margin) + 0.03f)
    return;
  // Switching away from a running technique ends its episode as interrupted.
  if (a.current >= 0) {
    const TechniqueDef& t = lib_[a.mind.known[static_cast<size_t>(a.current)].tech];
    float r = -0.05f;
    if (t.is_hunt()) r = -0.25f;
    if (t.executor == Executor::Graze || t.executor == Executor::Rest || t.executor == Executor::Drink)
      r = std::clamp(0.4f * (a.ep_hunger0 - a.mind.hunger), -0.1f, 0.3f);
    end_episode(a, r - a.ep_damage_taken, false);
  }
  a.ctx = ctx;
  start_episode(a, ch.known_index, prey);
}

void Ecosystem::start_episode(Agent& a, int known_index, uint32_t prey) {
  a.current = known_index;
  a.ep_start = t_;
  a.ep_damage_taken = 0.f;
  a.ep_hunger0 = a.mind.hunger;
  a.ep_group = false;
  a.target = 0;
  const TechniqueDef& t = lib_[a.mind.known[static_cast<size_t>(known_index)].tech];
  if (t.executor != Executor::Rest && t.executor != Executor::Graze && t.executor != Executor::Drink) a.last_novel = t_;
  if (t.is_hunt()) {
    a.target = prey;
    if (t.executor != Executor::JoinHunt) ++day_.hunts;  // count initiatives only
    if (day_.hunts_by_group.size() <= static_cast<size_t>(a.group)) day_.hunts_by_group.resize(static_cast<size_t>(a.group) + 1, 0);
    ++day_.hunts_by_group[static_cast<size_t>(a.group)];
    if (t.executor == Executor::PackFlank && prey) {
      GroupHunt& gh = group_hunts_[static_cast<size_t>(a.group)];
      if (gh.started < 0 || !agent(gh.target) || !agent(gh.target)->alive) {
        gh = GroupHunt{prey, a.id, t_, {a.id}};
      } else {
        // a hunt is already running: join it with a role instead of starting a rival one
        a.target = gh.target;
        if (std::find(gh.members.begin(), gh.members.end(), a.id) == gh.members.end()) gh.members.push_back(a.id);
      }
      a.ep_group = true;
    }
    if (t.executor == Executor::JoinHunt) {
      GroupHunt& gh = group_hunts_[static_cast<size_t>(a.group)];
      a.target = gh.target;
      if (std::find(gh.members.begin(), gh.members.end(), a.id) == gh.members.end()) gh.members.push_back(a.id);
      a.ep_group = true;
    }
  }
  if (t.executor == Executor::Wander || t.executor == Executor::Search)
    group_waypoint(a, t.executor == Executor::Search ? 450.0 : 150.0);
  if (t.executor == Executor::Drink) {
    double best = 1e30;
    for (const auto& w : water_) {
      const double d = dist(a.x, a.z, w.first, w.second);
      if (d < best) { best = d; a.tx = static_cast<float>(w.first); a.tz = static_cast<float>(w.second); }
    }
  }
}

void Ecosystem::end_episode(Agent& a, float r_intrinsic, bool success) {
  if (a.current < 0) return;
  const int ki = a.current;
  KnownTechnique& k = a.mind.known[static_cast<size_t>(ki)];
  const TechniqueDef& t = lib_[k.tech];
  const bool killed = success && t.is_hunt() && t.executor != Executor::Capture;
  float r_owner = 0.f;
  owner_feedback(a, t, success, killed, r_owner);
  auto& st = day_.per_tech[k.tech];
  ++st.episodes;
  if (success) ++st.successes;
  if (t.is_hunt() && t.executor != Executor::JoinHunt && success) ++day_.hunt_successes;
  learn_from_episode(a.mind, sp(a), lib_, ki, a.ctx, std::clamp(r_intrinsic, -1.f, 1.f), r_owner, a.ep_group, cfg_.learn);
  if (a.last_use_day.size() < a.mind.known.size()) a.last_use_day.resize(a.mind.known.size(), 0);
  a.last_use_day[static_cast<size_t>(ki)] = static_cast<uint32_t>(t_ / cfg_.day_s);
  // Learnable behaviours are visible to others.
  if (t.is_hunt() || t.executor == Executor::HerdCircle || t.executor == Executor::MobCharge)
    broadcast_observation(a, k.tech, success);
  check_discoveries(a, t, success);
  // Shared success binds the group: hunting partners strengthen their bonds.
  if (success && (t.executor == Executor::PackFlank || t.executor == Executor::JoinHunt)) {
    const GroupHunt& gh = group_hunts_[static_cast<size_t>(a.group)];
    const float gain = sp(a).bonds.pack_bond_gain;
    for (uint32_t mid : gh.members)
      if (mid != a.id) a.mind.strengthen(mid, BondKind::Packmate, gain);
  }
  if (t.executor == Executor::PackFlank) {
    GroupHunt& gh = group_hunts_[static_cast<size_t>(a.group)];
    if (gh.leader == a.id) gh = GroupHunt{};
  }
  a.current = -1;
  a.target = 0;
}

void Ecosystem::owner_feedback(Agent& a, const TechniqueDef& t, bool success, bool killed, float& r_owner) {
  r_owner = 0.f;
  if (!a.mind.tamed()) return;
  for (auto& o : owners_) {
    if (o.id != a.mind.owner) continue;
    if (dist(a.x, a.z, o.x, o.z) > 120.0) return;  // the owner must witness it
    switch (o.trainer) {
      case Trainer::CaptureTrainer:
        if (t.executor == Executor::Capture && success) { r_owner = 1.0f; a.mind.hunger = std::max(0.f, a.mind.hunger - 0.15f); }
        else if (killed) r_owner = -0.6f;
        break;
      case Trainer::HuntTrainer:
        if (killed) { r_owner = 0.6f; }
        break;
      case Trainer::None: break;
    }
  }
}

void Ecosystem::broadcast_observation(const Agent& demo, uint16_t tech, bool success) {
  if (!cfg_.learn.social) return;
  const SpeciesProfile& sd = sp(demo);
  const KnownTechnique& kd = demo.mind.known[static_cast<size_t>(demo.mind.known_index(tech))];
  std::vector<uint32_t> observers;
  for_near(demo.x, demo.z, 90.0, [&](Agent& o) { if (o.id != demo.id) observers.push_back(o.id); });
  for (uint32_t oid : observers) {
    Agent& o = *agent(oid);
    const SpeciesProfile& so = sp(o);
    const double d = dist(o.x, o.z, demo.x, demo.z);
    const double r_obs = 0.6 * so.vision_range_m;
    if (d > r_obs) continue;
    // compatibility: same species (same group best); tamed animals of the same
    // owner can learn across species (mixed packs); wild cross-species: none.
    float compat = 0.f;
    if (o.species == demo.species) compat = o.group == demo.group ? 1.f : 0.6f;
    else if (o.mind.tamed() && o.mind.owner == demo.mind.owner && so.diet == sd.diet) compat = 0.35f;
    if (compat <= 0.f) continue;
    const bool participant = o.current >= 0 && lib_[o.mind.known[static_cast<size_t>(o.current)].tech].is_hunt() && o.target == demo.target;
    // Who we watch depends on whom we are bonded to: young watch their
    // attachment figure most closely (vertical transmission).
    const float bondw = o.mind.bond_with(demo.id);
    const bool is_parent = o.mind.mother == demo.id || o.mind.father == demo.id || o.mind.attachment == demo.id;
    const float attention = static_cast<float>(std::max(0.0, 1.0 - d / r_obs)) * (0.3f + 0.7f * o.mind.instinct(Instinct::Curiosity)) *
                            (1.f - 0.8f * std::min(1.f, o.mind.stress)) * (o.mind.hunger > 0.9f ? 0.4f : 1.f) *
                            (o.mind.juvenile ? 1.5f : 1.f) * (participant ? 1.5f : 1.f) * (0.3f + 1.2f * bondw) * (is_parent ? 1.5f : 1.f);
    if (observe(o.mind, so, lib_, tech, demo.id, kd.mastery, kd.generation, std::min(1.f, attention), compat, success, cfg_.learn)) {
      ++day_.social_acquisitions;
      const Transmission kind = is_parent ? Transmission::Vertical
                                          : (o.mind.juvenile == demo.mind.juvenile ? Transmission::Horizontal : Transmission::Oblique);
      ++day_.transmissions[static_cast<size_t>(kind)];
    }
  }
}

void Ecosystem::check_discoveries(Agent& a, const TechniqueDef& t, bool success) {
  (void)success;
  const SpeciesProfile& s = sp(a);
  for (size_t ti = 0; ti < lib_.size(); ++ti) {
    const TechniqueDef& d = lib_[ti];
    if (d.discover_p <= 0.f || a.mind.known_index(static_cast<uint16_t>(ti)) >= 0) continue;
    bool trigger = false;
    Agent* prey = agent(a.target);
    if (d.discover_trigger == "hunting_large_prey_with_pack")
      trigger = t.is_hunt() && prey && sp(*prey).mass_kg > 1.5f * s.mass_kg && packmates_near(a, 40.0) >= 2;
    else if (d.discover_trigger == "threat_in_herd")
      trigger = a.threat > 0.3f && packmates_near(a, 20.0) >= 3;
    else if (d.discover_trigger == "cornered_by_weaker")
      trigger = t.executor == Executor::Flee && a.threat > 0.3f && s.mass_kg > 200.f;
    else if (d.discover_trigger == "playful_with_prey")
      trigger = t.is_hunt() && a.mind.hunger < 0.35f;
    else if (d.discover_trigger == "hunting_near_cover")
      trigger = t.is_hunt();
    if (trigger && try_discover(a.mind, s, lib_, static_cast<uint16_t>(ti), cfg_.learn)) ++day_.discoveries;
  }
}

// ---------------------------------------------------------------------------
// Executors: technique -> MotorCommand (+ episode termination and outcome)
// ---------------------------------------------------------------------------
bool Ecosystem::hunt_step(Agent& a, Agent& prey, bool sneak, bool flank, float flank_side, float mastery) {
  const SpeciesProfile& s = sp(a);
  const double d = dist(a.x, a.z, prey.x, prey.z);
  const double reach = s.body_radius_m + sp(prey).body_radius_m + 0.8;
  if (d <= reach) {
    a.cmd.gait = Gait::Run;
    a.cmd.action = MotorAction::Bite;
    a.cmd.action_target = prey.id;
    a.cmd.target_x = static_cast<float>(prey.x);
    a.cmd.target_z = static_cast<float>(prey.z);
    return true;
  }
  const double strike = 6.0 + 10.0 * mastery;
  // Interception: aim where the prey will be; skill improves the lead estimate.
  const double v = std::max(1.0, gait_speed(s, Gait::Sprint));
  const double lead = std::clamp(d / v, 0.0, 3.0) * (0.3 + 0.7 * mastery);
  double txp = prey.x + prey.vx * lead, tzp = prey.z + prey.vz * lead;
  if (flank) {
    // Flankers run to a point on the side of the prey's escape route, ahead of it.
    double ex = prey.vx, ez = prey.vz;
    const double sp_ = std::sqrt(ex * ex + ez * ez);
    if (sp_ < 0.3) { ex = prey.x - a.x; ez = prey.z - a.z; }
    const double n = std::max(1e-6, std::sqrt(ex * ex + ez * ez));
    ex /= n; ez /= n;
    const double ang = flank_side * (60.0 + 25.0 * (1.0 - mastery) * (a.mind.rng.uniform() - 0.5)) * kPi / 180.0;
    const double ca = std::cos(ang), sa = std::sin(ang);
    const double fx = ex * ca - ez * sa, fz = ex * sa + ez * ca;
    const double ahead = 12.0 * (0.5 + mastery);
    if (d > 10.0) { txp = prey.x + fx * ahead + prey.vx * lead; tzp = prey.z + fz * ahead + prey.vz * lead; }
  }
  a.cmd.target_x = static_cast<float>(txp);
  a.cmd.target_z = static_cast<float>(tzp);
  a.cmd.action = MotorAction::None;
  if (sneak && d > strike) a.cmd.gait = Gait::Sneak;
  else a.cmd.gait = a.stamina > 0.05f ? Gait::Sprint : Gait::Trot;
  return false;
}

void Ecosystem::execute(Agent& a) {
  a.cmd.action = MotorAction::None;
  if (a.current < 0) { a.cmd.gait = Gait::Stand; return; }
  const SpeciesProfile& s = sp(a);
  KnownTechnique& k = a.mind.known[static_cast<size_t>(a.current)];
  const TechniqueDef& t = lib_[k.tech];
  const double elapsed = t_ - a.ep_start;
  auto end = [&](float r, bool ok) { end_episode(a, r - a.ep_damage_taken, ok); };

  switch (t.executor) {
    case Executor::Graze: {
      // move to the richest nearby vegetation cell and feed there
      const int ci = std::clamp(static_cast<int>(a.x / cfg_.veg_cell_m), 0, veg_n_ - 1);
      const int cj = std::clamp(static_cast<int>(a.z / cfg_.veg_cell_m), 0, veg_n_ - 1);
      float& here = veg_[static_cast<size_t>(cj) * veg_n_ + ci];
      if (here > 0.15f) {
        a.cmd.gait = Gait::Stand;
        a.cmd.action = MotorAction::Eat;
        const float intake = static_cast<float>(cfg_.dt / 900.0);
        here = std::max(0.f, here - intake * std::max(1.f, s.mass_kg / 200.f) * 0.5f);
        a.mind.hunger = std::max(0.f, a.mind.hunger - intake * 1.6f);
      } else {
        int bi = ci, bj = cj;
        float best = here;
        for (int dj = -2; dj <= 2; ++dj)
          for (int di = -2; di <= 2; ++di) {
            const int ii = std::clamp(ci + di, 0, veg_n_ - 1), jj = std::clamp(cj + dj, 0, veg_n_ - 1);
            const float v = veg_[static_cast<size_t>(jj) * veg_n_ + ii] - 0.02f * static_cast<float>(std::abs(di) + std::abs(dj));
            if (v > best) { best = v; bi = ii; bj = jj; }
          }
        a.cmd.gait = Gait::Walk;
        a.cmd.target_x = static_cast<float>((bi + 0.5) * cfg_.veg_cell_m);
        a.cmd.target_z = static_cast<float>((bj + 0.5) * cfg_.veg_cell_m);
      }
      if (a.mind.hunger < 0.05f || elapsed > 1800.0) end(std::clamp(0.2f + 0.5f * (a.ep_hunger0 - a.mind.hunger), 0.f, 0.6f), true);
      break;
    }
    case Executor::Drink: {
      a.cmd.target_x = a.tx;
      a.cmd.target_z = a.tz;
      if (dist(a.x, a.z, a.tx, a.tz) < 5.0) {
        a.cmd.gait = Gait::Stand;
        a.cmd.action = MotorAction::Drink;
        a.mind.thirst = std::max(0.f, a.mind.thirst - static_cast<float>(cfg_.dt / 40.0));
        if (a.mind.thirst < 0.03f) end(0.3f, true);
      } else {
        a.cmd.gait = Gait::Walk;
      }
      if (elapsed > 900.0) end(-0.1f, false);
      break;
    }
    case Executor::Rest:
      a.cmd.gait = Gait::Stand;
      a.cmd.action = MotorAction::Rest;
      if (a.mind.fatigue < 0.05f || elapsed > 600.0) end(0.2f, true);
      break;
    case Executor::Search:
      // hunger-driven patrol of the hunting range at a ground-covering trot
      a.cmd.gait = Gait::Trot;
      a.cmd.target_x = a.tx;
      a.cmd.target_z = a.tz;
      if (dist(a.x, a.z, a.tx, a.tz) < 6.0 || elapsed > 200.0) end(0.05f, true);
      break;
    case Executor::Wander:
      a.cmd.gait = Gait::Walk;
      a.cmd.target_x = a.tx;
      a.cmd.target_z = a.tz;
      if (dist(a.x, a.z, a.tx, a.tz) < 4.0 || elapsed > 240.0) end(0.05f, true);
      break;
    case Executor::Regroup: {
      const size_t g = static_cast<size_t>(a.group);
      const int n = group_alive_[g] - 1;
      if (n <= 0) { end(0.f, false); break; }
      // centroid of the others = (sum - self) / n
      a.cmd.target_x = static_cast<float>((group_cx_[g] * (n + 1) - a.x) / n);
      a.cmd.target_z = static_cast<float>((group_cz_[g] * (n + 1) - a.z) / n);
      a.cmd.gait = Gait::Trot;
      if (packmates_near(a, 15.0) >= std::min(n, 2) || elapsed > 300.0) end(0.2f, true);
      break;
    }
    case Executor::Flee: {
      double ex = a.x - a.threat_x, ez = a.z - a.threat_z;
      const double n = std::max(1e-6, std::sqrt(ex * ex + ez * ez));
      ex /= n; ez /= n;
      // evasive zig-zag: skill makes the escape path less predictable
      const double zig = (0.2 + 0.6 * k.mastery) * std::sin(t_ * 1.7 + a.id);
      a.cmd.target_x = static_cast<float>(a.x + (ex - ez * zig) * 30.0);
      a.cmd.target_z = static_cast<float>(a.z + (ez + ex * zig) * 30.0);
      a.cmd.gait = a.stamina > 0.05f ? Gait::Sprint : Gait::Trot;
      if (t_ - a.last_threat_seen > 8.0) end(0.6f, true);
      else if (elapsed > 120.0) end(0.0f, false);
      break;
    }
    case Executor::HerdCircle: {
      double cx = 0, cz = 0;
      int n = 0;
      for_near(a.x, a.z, 40.0, [&](Agent& b) { if (b.group == a.group) { cx += b.x; cz += b.z; ++n; } });
      a.cmd.target_x = static_cast<float>(cx / std::max(1, n));
      a.cmd.target_z = static_cast<float>(cz / std::max(1, n));
      a.cmd.gait = Gait::Trot;
      a.cmd.look_x = a.threat_x;
      a.cmd.look_z = a.threat_z;
      if (t_ - a.last_threat_seen > 12.0) end(0.5f, true);
      else if (elapsed > 180.0) end(0.1f, false);
      break;
    }
    case Executor::AlarmCall: {
      a.cmd.action = MotorAction::Call;
      a.called_alarm = true;
      int listeners = 0;
      for_near(a.x, a.z, s.hearing_range_m * 1.5, [&](Agent& b) {
        if (b.id == a.id || b.species != a.species) return;
        // receivers learn where the threat is (information transfer)
        b.seen.push_back({a.threat_id, a.threat_x, a.threat_z, 0.f, 0.f, t_});
        ++listeners;
      });
      end(listeners > 0 ? 0.3f : 0.f, listeners > 0);
      break;
    }
    case Executor::MobCharge: {
      Agent* th = agent(a.threat_id);
      if (!th || !th->alive || elapsed > 25.0) { end(-0.1f, false); break; }
      a.cmd.target_x = static_cast<float>(th->x);
      a.cmd.target_z = static_cast<float>(th->z);
      a.cmd.gait = a.stamina > 0.05f ? Gait::Run : Gait::Trot;
      if (dist(a.x, a.z, th->x, th->z) < s.body_radius_m + sp(*th).body_radius_m + 1.0) {
        a.cmd.action = MotorAction::Charge;
        const float ga = growth(a), gt = growth(*th);
        const float dmg = s.attack * ga * ga * (0.5f + 0.5f * k.mastery) * static_cast<float>(a.mind.rng.uniform(0.7, 1.3));
        th->health -= dmg / (sp(*th).toughness * gt * gt);
        // the charged predator learns to fear this species (memory)
        if (th->current >= 0) th->ep_damage_taken += 0.5f;
        if (th->health <= 0.f) kill(*th, nullptr);
        end(0.8f, true);
      }
      break;
    }
    case Executor::Stalk:
    case Executor::Pursue:
    case Executor::Capture:
    case Executor::PackFlank:
    case Executor::JoinHunt: {
      Agent* prey = agent(a.target);
      if (t.executor == Executor::JoinHunt) {
        const GroupHunt& gh = group_hunts_[static_cast<size_t>(a.group)];
        if (gh.started < 0) { end(-0.05f, false); break; }
        prey = agent(gh.target);
        a.target = gh.target;
      }
      if (!prey || !prey->alive) {
        // prey killed by someone else of the pack counts as a group success
        const bool pack_kill = prey && !prey->alive && a.ep_group;
        end(pack_kill ? 0.8f : -0.2f, pack_kill);
        break;
      }
      const double d = dist(a.x, a.z, prey->x, prey->z);
      const bool lost = d > 1.5 * s.vision_range_m || (a.stamina <= 0.02f && d > 15.0) || elapsed > 150.0;
      if (lost) { end(-0.3f, false); break; }
      bool flank = false;
      float side = 1.f;
      float mastery = k.mastery;
      if (t.executor == Executor::PackFlank || t.executor == Executor::JoinHunt) {
        GroupHunt& gh = group_hunts_[static_cast<size_t>(a.group)];
        const auto it = std::find(gh.members.begin(), gh.members.end(), a.id);
        const int idx = it == gh.members.end() ? 0 : static_cast<int>(it - gh.members.begin());
        // Roles: the leader (idx 0) drives the prey; the others flank, alternating sides.
        // A JoinHunt participant flanks only if it actually knows the cooperative technique.
        const int pf = lib_.find("pack_flank");
        const float pf_m = pf >= 0 ? a.mind.mastery_of(static_cast<uint16_t>(pf)) : 0.f;
        flank = idx > 0 && (t.executor == Executor::PackFlank || pf_m > 0.f);
        side = (idx % 2) ? 1.f : -1.f;
        if (t.executor == Executor::JoinHunt) mastery = std::max(pf_m, 0.5f * a.mind.mastery_of(static_cast<uint16_t>(lib_.find("pursuit"))));
      }
      // An already-pinned prey cannot be "captured" again (prevents a reward
      // loop that emerged in testing: re-pinning the same helpless prey).
      if (t.executor == Executor::Capture && prey->captured_until > t_) { end(0.f, false); break; }
      const bool contact = hunt_step(a, *prey, t.executor == Executor::Stalk, flank, side, mastery);
      if (contact) {
        if (t.executor == Executor::Capture) {
          // Non-lethal pin: needs enough mass on the prey and technique.
          const double group_mass = s.mass_kg * (1 + packmates_near(a, 8.0));
          const double ratio = std::log2(group_mass / sp(*prey).mass_kg);
          const double pz = 4.0 * (a.mind.skill[static_cast<size_t>(Skill::CaptureNonlethal)] + 0.5 * k.mastery + 0.3 * ratio - 0.35);
          if (t_ - a.last_bite > 1.0) {
            a.last_bite = t_;
            if (a.mind.rng.uniform() < 1.0 / (1.0 + dmath::exp(-pz))) {
              prey->captured_until = t_ + 30.0;
              ++day_.captures;
              if (day_.captures_by_group.size() <= static_cast<size_t>(a.group)) day_.captures_by_group.resize(static_cast<size_t>(a.group) + 1, 0);
              ++day_.captures_by_group[static_cast<size_t>(a.group)];
              // Intrinsic value of a capture is play, and play gets boring:
              // it decays with repetition within the day.
              const float novelty = 1.f / (1.f + a.captures_today / 3.f);
              ++a.captures_today;
              // Live prey pinned in front of one's own young is a lesson (cheetah
              // mothers, Caro 1994): high value. Otherwise it is play, which bores.
              bool young_near = false;
              for (uint32_t yid : group_juveniles_[static_cast<size_t>(a.group)])
                if (is_dependent_of(agents_[index_of_id_[yid]], a) && dist(a.x, a.z, agents_[index_of_id_[yid]].x, agents_[index_of_id_[yid]].z) < 40.0)
                  young_near = true;
              end(young_near ? 0.7f : (a.mind.hunger > 0.6f ? 0.05f : 0.2f) * novelty, true);
            }
          }
        } else {
          bite(a, *prey);
          if (!prey->alive) end(1.0f, true);
        }
      }
      break;
    }
    case Executor::Scavenge: {
      int best = -1;
      double bd = 1e30;
      for (size_t c = 0; c < carcasses_.size(); ++c) {
        const double d = dist(a.x, a.z, carcasses_[c].x, carcasses_[c].z);
        if (carcasses_[c].meat_kg > 0.5f && d < bd) { bd = d; best = static_cast<int>(c); }
      }
      if (best < 0 || elapsed > 600.0) { end(-0.1f, false); break; }
      Carcass& c = carcasses_[static_cast<size_t>(best)];
      a.cmd.target_x = static_cast<float>(c.x);
      a.cmd.target_z = static_cast<float>(c.z);
      a.cmd.gait = bd > 20.0 ? Gait::Trot : Gait::Walk;
      if (bd < 3.0) {
        a.cmd.gait = Gait::Stand;
        a.cmd.action = MotorAction::Eat;
        const float kg = std::min(c.meat_kg, static_cast<float>(0.02 * s.mass_kg * cfg_.dt));
        c.meat_kg -= kg;
        a.mind.hunger = std::max(0.f, a.mind.hunger - kg / (0.18f * s.mass_kg));
        if (a.mind.hunger < 0.03f || c.meat_kg <= 0.5f) end(0.4f, true);
      }
      break;
    }
    case Executor::FollowAttachment: {
      double fx, fz;
      bool alive;
      if (!attachment_pos(a, fx, fz, alive) || !alive) { end(0.f, false); break; }
      const double keep = a.mind.juvenile ? 3.0 : 5.0;
      a.cmd.target_x = static_cast<float>(fx + keep * std::cos(a.id * 2.39996));
      a.cmd.target_z = static_cast<float>(fz + keep * std::sin(a.id * 2.39996));
      const double d = dist(a.x, a.z, fx, fz);
      a.cmd.gait = d > 25.0 ? Gait::Run : (d > 10.0 ? Gait::Trot : Gait::Walk);
      if (d < keep + 4.0) {
        // proximity to the attachment figure is itself rewarding (security)
        a.mind.strengthen(a.mind.attachment, a.mind.attachment_kind, 0.002f);
        end(0.15f, true);
      } else if (elapsed > 200.0) {
        end(-0.1f, false);
      }
      break;
    }
    case Executor::GuardAttachment:
    case Executor::GuardYoung: {
      // charge the most dangerous predator near whoever I protect
      double px = a.x, pz = a.z;
      if (t.executor == Executor::GuardAttachment) {
        bool alive;
        if (!attachment_pos(a, px, pz, alive) || !alive) { end(0.f, false); break; }
      } else {
        double best = 1e30;
        for (uint32_t yid : group_juveniles_[static_cast<size_t>(a.group)]) {
          const Agent& y = agents_[index_of_id_[yid]];
          if (!is_dependent_of(y, a)) continue;
          if (y.threat > 0.f && dist(a.x, a.z, y.x, y.z) < best) { best = dist(a.x, a.z, y.x, y.z); px = y.x; pz = y.z; }
        }
      }
      Agent* foe = nullptr;
      double fd = 30.0;
      for_near(px, pz, 30.0, [&](Agent& b) {
        if (!is_predator(sp(b).diet) || b.group == a.group || (a.mind.tamed() && b.mind.owner == a.mind.owner)) return;
        const double d = dist(px, pz, b.x, b.z);
        if (d < fd) { fd = d; foe = &b; }
      });
      if (!foe || elapsed > 30.0) { end(foe ? -0.1f : 0.2f, !foe); break; }
      a.cmd.target_x = static_cast<float>(foe->x);
      a.cmd.target_z = static_cast<float>(foe->z);
      a.cmd.gait = Gait::Run;
      if (dist(a.x, a.z, foe->x, foe->z) < s.body_radius_m + sp(*foe).body_radius_m + 1.0) {
        a.cmd.action = MotorAction::Charge;
        const float ga = growth(a), gf = growth(*foe);
        foe->health -= s.attack * ga * ga * (0.5f + 0.5f * k.mastery) * static_cast<float>(a.mind.rng.uniform(0.7, 1.3)) /
                       (sp(*foe).toughness * gf * gf);
        if (foe->current >= 0) foe->ep_damage_taken += 0.5f;
        if (foe->health <= 0.f) kill(*foe, nullptr);
        end(0.7f, true);
      }
      break;
    }
    case Executor::Provision: {
      // Carry food to the hungriest dependent (carnivores regurgitate / bring
      // meat); this is also how young first learn what food is.
      if (a.mind.hunger > 0.55f) { end(-0.1f, false); break; }
      Agent* young = nullptr;
      float worst = 0.25f;
      for (uint32_t yid : group_juveniles_[static_cast<size_t>(a.group)]) {
        Agent& y = agents_[index_of_id_[yid]];
        if (is_dependent_of(y, a) && y.mind.hunger > worst && dist(a.x, a.z, y.x, y.z) < 250.0) { worst = y.mind.hunger; young = &y; }
      }
      if (!young || elapsed > 200.0) { end(0.f, false); break; }
      a.cmd.target_x = static_cast<float>(young->x);
      a.cmd.target_z = static_cast<float>(young->z);
      a.cmd.gait = Gait::Trot;
      if (dist(a.x, a.z, young->x, young->z) < 4.0) {
        young->mind.hunger = std::max(0.f, young->mind.hunger - 0.4f);
        a.mind.hunger = std::min(1.f, a.mind.hunger + 0.12f);
        young->mind.strengthen(a.id, young->mind.mother == a.id || young->mind.father == a.id ? BondKind::Parent : BondKind::Packmate, 0.05f);
        a.mind.strengthen(young->id, BondKind::Offspring, 0.03f);
        ++day_.provisioned;
        end(0.6f, true);
      }
      break;
    }
    case Executor::Count: break;
  }
}

void Ecosystem::bite(Agent& hunter, Agent& prey) {
  if (t_ - hunter.last_bite < 1.0) return;
  hunter.last_bite = t_;
  const SpeciesProfile& sh = sp(hunter);
  const SpeciesProfile& sy = sp(prey);
  const int ki = hunter.current;
  const float mastery = ki >= 0 ? hunter.mind.known[static_cast<size_t>(ki)].mastery : 0.f;
  // Herd defence: every herd mate packed around the victim deflects attacks.
  int guards = 0;
  for_near(prey.x, prey.z, 6.0, [&](Agent& b) {
    if (b.id != prey.id && b.group == prey.group && b.current >= 0 &&
        lib_[b.mind.known[static_cast<size_t>(b.current)].tech].executor == Executor::HerdCircle) ++guards;
  });
  const double held = prey.captured_until > t_ ? 1.6 : 1.0;
  const double gh = growth(hunter), gy = growth(prey);
  const double dmg = sh.attack * gh * gh * (0.6 + 0.4 * mastery) * hunter.mind.rng.uniform(0.7, 1.3) * held / (1.0 + 0.35 * guards);
  prey.health -= static_cast<float>(dmg / (sy.toughness * gy * gy));
  if (prey.current >= 0) prey.ep_damage_taken += 0.3f;
  // Defensive retaliation (kicks, horns): big prey hurt small hunters.
  if (hunter.mind.rng.uniform() < 0.25) {
    const double back = sy.attack * gy * gy * 0.35 * hunter.mind.rng.uniform(0.5, 1.2) * (prey.captured_until > t_ ? 0.3 : 1.0);
    hunter.health -= static_cast<float>(back / (sh.toughness * gh * gh));
    hunter.ep_damage_taken += static_cast<float>(std::min(0.5, back / (sh.toughness * gh * gh)));
    if (hunter.health <= 0.f) { kill(hunter, nullptr); return; }
  }
  if (prey.health <= 0.f) kill(prey, &hunter);
}

void Ecosystem::kill(Agent& prey, Agent* killer) {
  if (!prey.alive) return;
  if (prey.current >= 0) end_episode(prey, -1.f, false);
  prey.alive = false;
  prey.died_at = t_;
  carcasses_.push_back({prey.x, prey.z, 0.55f * sp(prey).mass_kg, t_});
  if (killer) {
    ++day_.kills;
    if (day_.kills_by_group.size() <= static_cast<size_t>(killer->group)) day_.kills_by_group.resize(static_cast<size_t>(killer->group) + 1, 0);
    ++day_.kills_by_group[static_cast<size_t>(killer->group)];
  }
  if (is_predator(sp(prey).diet)) ++day_.predator_deaths; else ++day_.prey_deaths;
  if (prey.mind.juvenile) ++day_.juvenile_deaths;
}

// ---------------------------------------------------------------------------
// Body: needs, stamina, kinematic stand-in for the motor brain
// ---------------------------------------------------------------------------
void Ecosystem::needs(Agent& a) {
  const SpeciesProfile& s = sp(a);
  const double dt = cfg_.dt;
  double activity = 1.0;
  switch (a.cmd.gait) {
    case Gait::Stand: activity = a.cmd.action == MotorAction::Rest ? 0.7 : 0.9; break;
    case Gait::Sneak: activity = 1.1; break;
    case Gait::Walk: activity = 1.2; break;
    case Gait::Trot: activity = 1.6; break;
    case Gait::Run: activity = 2.2; break;
    case Gait::Sprint: activity = 3.0; break;
  }
  // Kleiber-scaled hunger: a 25 kg animal empties its reserves in ~1 game day at rest.
  const double rate = (1.0 / cfg_.day_s) * s.metabolic_rate / 0.447 * (is_predator(s.diet) ? 0.75 : 1.0);
  a.mind.hunger = clamp01(a.mind.hunger + rate * activity * dt);
  a.mind.thirst = clamp01(a.mind.thirst + (1.0 / cfg_.day_s) * 1.2 * (0.6 + 0.4 * activity) * dt);
  if (a.cmd.action == MotorAction::Rest) a.mind.fatigue = clamp01(a.mind.fatigue - dt / 900.0);
  else a.mind.fatigue = clamp01(a.mind.fatigue + (1.0 / (0.8 * cfg_.day_s)) * activity * 0.6 * dt);
  if (a.cmd.gait == Gait::Sprint) a.stamina = clamp01(a.stamina - dt / s.sprint_endurance_s);
  else if (a.cmd.gait == Gait::Run) a.stamina = clamp01(a.stamina - 0.4 * dt / s.sprint_endurance_s);
  else a.stamina = clamp01(a.stamina + dt / (3.0 * s.sprint_endurance_s));
  a.health = std::min(1.f, a.health + static_cast<float>(dt / (2.0 * cfg_.day_s)));
  // ageing, maturity and dispersal
  a.mind.age_days += static_cast<float>(dt / cfg_.day_s);
  if (a.mind.juvenile && a.mind.age_days >= s.bonds.maturation_days) {
    a.mind.juvenile = false;
    a.mind.sex = static_cast<uint8_t>(a.id % 2);
    if (a.mind.attachment != a.mind.owner || a.mind.owner == 0) {
      // dispersing species loosen the bond with the parents at maturity
      for (auto& b : a.mind.bonds)
        if (b.kind == BondKind::Parent) b.strength *= 1.f - 0.8f * s.bonds.dispersal;
      if (s.bonds.dispersal >= 0.5f) a.mind.attachment = 0;
    }
  }
  // orphans: in alloparental groups the strongest adult bond becomes the new
  // attachment figure (adoption); otherwise the young is on its own
  if (a.mind.juvenile && a.mind.attachment != 0 && a.mind.attachment != a.mind.owner) {
    const Agent* f = a.mind.attachment < index_of_id_.size() ? &agents_[index_of_id_[a.mind.attachment]] : nullptr;
    if (!f || !f->alive) {
      a.mind.attachment = 0;
      float best = 0.f;
      for (const auto& b : a.mind.bonds) {
        const Agent* c = b.other < index_of_id_.size() ? &agents_[index_of_id_[b.other]] : nullptr;
        if (c && c->alive && !c->mind.juvenile && c->group == a.group && b.strength > best) { best = b.strength; a.mind.attachment = b.other; }
      }
      a.mind.attachment_kind = BondKind::Packmate;
    }
  }
  if (a.mind.hunger >= 1.f || a.mind.thirst >= 1.f) {
    a.health -= static_cast<float>(dt / (0.5 * cfg_.day_s));
    if (a.health <= 0.f) {
      ++day_.deaths_starvation;
      if (is_predator(s.diet)) ++day_.predators_starved;
      kill(a, nullptr);
    }
  }
}

void Ecosystem::integrate(Agent& a) {
  const SpeciesProfile& s = sp(a);
  if (a.captured_until > t_) { a.vx = a.vz = 0; return; }
  // juveniles are slower (dynamic similarity: v ~ sqrt(leg length) ~ growth^0.5)
  const double gs = std::sqrt(static_cast<double>(growth(a)));
  double speed = gait_speed(s, a.cmd.gait) * gs;
  if (a.cmd.gait == Gait::Sprint && a.stamina <= 0.f) speed = gait_speed(s, Gait::Trot) * gs;
  double dx = a.cmd.target_x - a.x, dz = a.cmd.target_z - a.z;
  const double d = std::sqrt(dx * dx + dz * dz);
  double tvx = 0, tvz = 0;
  if (d > 0.3 && speed > 0) { tvx = dx / d * std::min(speed, d / cfg_.dt); tvz = dz / d * std::min(speed, d / cfg_.dt); }
  // Acceleration limit ~ g * 0.5 (traction), turning inertia grows with mass.
  const double amax = 4.9 / (1.0 + 0.25 * std::log10(std::max(1.f, s.mass_kg)));
  double ax = (tvx - a.vx) / cfg_.dt, az = (tvz - a.vz) / cfg_.dt;
  const double an = std::sqrt(ax * ax + az * az);
  if (an > amax) { ax *= amax / an; az *= amax / an; }
  a.vx += ax * cfg_.dt;
  a.vz += az * cfg_.dt;
  a.x = std::clamp(a.x + a.vx * cfg_.dt, 1.0, cfg_.size_m - 1.0);
  a.z = std::clamp(a.z + a.vz * cfg_.dt, 1.0, cfg_.size_m - 1.0);
}

// Births: a well-fed adult female with an adult male of her group nearby
// lays a clutch. Carrying capacity: no births above the species cap.
void Ecosystem::reproduction() {
  std::vector<int> pop(species_.size(), 0);
  for (const auto& a : agents_) if (a.alive) ++pop[static_cast<size_t>(a.species)];
  // Births are collected first and performed afterwards: adding agents
  // while iterating would invalidate references into agents_.
  std::vector<std::pair<uint32_t, uint32_t>> births;
  for (size_t i = 0; i < agents_.size(); ++i) {
    Agent& f = agents_[i];
    if (!f.alive || f.mind.juvenile || f.mind.sex != 0) continue;
    const SpeciesProfile& s = sp(f);
    const size_t si = static_cast<size_t>(f.species);
    const int cap = static_cast<int>(cfg_.max_population_factor * static_cast<float>(si < initial_population_.size() ? initial_population_[si] : 0));
    if (pop[si] + s.bonds.clutch > cap) continue;
    const double interval = 2.0 * s.bonds.maturation_days * cfg_.day_s;
    if (t_ - f.last_breed < interval || f.health < 0.6f || f.mind.hunger > 0.45f || f.mind.dependents > 0) continue;
    // mate choice: the adult male of the group she is most bonded to, within 40 m
    Agent* mate = nullptr;
    float best = -1.f;
    for_near(f.x, f.z, 40.0, [&](Agent& m) {
      if (m.group != f.group || m.mind.juvenile || m.mind.sex != 1 || m.species != f.species) return;
      const float b = f.mind.bond_with(m.id);
      if (b > best) { best = b; mate = &m; }
    });
    if (!mate) continue;
    births.push_back({f.id, mate->id});
    f.last_breed = t_;
    pop[si] += s.bonds.clutch;
  }
  for (const auto& [m, f] : births) give_birth(m, f);
}

void Ecosystem::give_birth(uint32_t mother_id, uint32_t father_id) {
  const int clutch = sp(*agent(mother_id)).bonds.clutch;
  agents_.reserve(agents_.size() + static_cast<size_t>(clutch));  // no reallocation below: references stay valid
  Agent& mother = *agent(mother_id);
  Agent* father = agent(father_id);
  const SpeciesProfile& s = sp(mother);
  mother.last_breed = t_;
  if (father) {
    mother.mind.strengthen(father->id, BondKind::Mate, 0.2f);
    father->mind.strengthen(mother.id, BondKind::Mate, 0.2f);
  }
  // owner present at hatching (tamed mother, or egg handed to the player)?
  const Owner* owner = nullptr;
  if (mother.mind.tamed())
    for (const auto& o : owners_)
      if (o.id == mother.mind.owner && dist(o.x, o.z, mother.x, mother.z) < 30.0) owner = &o;
  for (int c = 0; c < s.bonds.clutch; ++c) {
    Agent y = spawn(mother.species, mother.group, mother.x + rng_.uniform(-2, 2), mother.z + rng_.uniform(-2, 2), true);
    y.mind = make_offspring(y.id, s, lib_, cfg_.seed, mother.mind, father ? &father->mind : nullptr, cfg_.mutation_sd);
    y.mind.sex = static_cast<uint8_t>(c % 2);
    y.home_x = mother.home_x;
    y.home_z = mother.home_z;
    y.health = 1.f;
    // Imprinting at hatching: the first caring figure becomes the attachment.
    if (owner && (s.bonds.egg_imprinting || mother.mind.tamed())) {
      y.mind.owner = owner->id;
      y.mind.bond = s.bonds.egg_imprinting ? 0.85f : 0.6f;
      y.mind.attachment = owner->id;
      y.mind.attachment_kind = BondKind::Owner;
      y.mind.command = mother.mind.command;
      y.mind.obedience.fill(0.3f);
      ++day_.owner_imprinted;
    } else {
      y.mind.attachment = mother.id;
      y.mind.attachment_kind = BondKind::Parent;
      if (mother.mind.tamed()) { y.mind.owner = mother.mind.owner; y.mind.bond = 0.3f; y.mind.command = mother.mind.command; y.mind.obedience.fill(0.3f); }
    }
    y.mind.strengthen(mother.id, BondKind::Parent, 0.6f);
    if (father && s.bonds.biparental) y.mind.strengthen(father->id, BondKind::Parent, 0.5f);
    // group bonds from birth: strong in packs, weak in herds
    for_near(mother.x, mother.z, 60.0, [&](Agent& m) {
      if (m.group == mother.group && m.id != mother.id && !m.mind.juvenile)
        y.mind.strengthen(m.id, BondKind::Packmate, 10.f * s.bonds.pack_bond_gain);
    });
    mother.mind.strengthen(y.id, BondKind::Offspring, 0.6f);
    if (index_of_id_.size() <= y.id) index_of_id_.resize(y.id + 1);
    index_of_id_[y.id] = static_cast<uint32_t>(agents_.size());
    agents_.push_back(std::move(y));
    ++day_.births;
  }
}

void Ecosystem::respawns() {
  if (cfg_.reproduction) reproduction();
  if (!cfg_.immigration) {
    carcasses_.erase(std::remove_if(carcasses_.begin(), carcasses_.end(),
                                    [&](const Carcass& c) { return c.meat_kg <= 0.5f || t_ - c.t > 0.5 * cfg_.day_s; }),
                     carcasses_.end());
    return;
  }
  // Dead creatures are replaced by naive newcomers (juveniles) joining the
  // same group: knowledge must be passed on, or it is lost with its holders.
  const size_t n = agents_.size();
  for (size_t i = 0; i < n; ++i) {
    Agent& a = agents_[i];
    if (a.alive || a.died_at < 0 || t_ - a.died_at < cfg_.respawn_delay_s) continue;
    a.died_at = -2;  // replaced
    const size_t g = static_cast<size_t>(a.group);
    const bool has_group = g < group_alive_.size() && group_alive_[g] > 0;
    const double cx = has_group ? group_cx_[g] : a.home_x, cz = has_group ? group_cz_[g] : a.home_z;
    Agent nb = spawn(a.species, a.group, cx + rng_.uniform(-10, 10), cz + rng_.uniform(-10, 10), true);
    nb.home_x = a.home_x;
    nb.home_z = a.home_z;
    if (a.mind.tamed()) {
      nb.mind.owner = a.mind.owner;
      nb.mind.bond = 0.3f;
      nb.mind.command = a.mind.command;
      nb.mind.obedience.fill(0.3f);
    }
    if (index_of_id_.size() <= nb.id) index_of_id_.resize(nb.id + 1);
    index_of_id_[nb.id] = static_cast<uint32_t>(agents_.size());
    agents_.push_back(std::move(nb));
  }
  carcasses_.erase(std::remove_if(carcasses_.begin(), carcasses_.end(),
                                  [&](const Carcass& c) { return c.meat_kg <= 0.5f || t_ - c.t > 0.5 * cfg_.day_s; }),
                   carcasses_.end());
}

void Ecosystem::owners_step() {
  for (auto& o : owners_) {
    // The owner walks slowly around camp; tamed creatures get daily rations
    // when they are close, so they do not have to kill to survive.
    // The owner accompanies the animals (as a player riding along would), so
    // that it can witness - and reward or scold - what they do.
    double cx = 0, cz = 0;
    int n = 0;
    for (uint32_t id : o.creatures) {
      const Agent* c = agent(id);
      if (c && c->alive) { cx += c->x; cz += c->z; ++n; }
    }
    if (n > 0) {
      cx /= n; cz /= n;
      const double d = dist(o.x, o.z, cx, cz);
      if (d > 35.0) {
        const double step = std::min(d - 35.0, 1.5 * cfg_.dt);
        o.x += (cx - o.x) / d * step;
        o.z += (cz - o.z) / d * step;
      }
    }
    for (uint32_t id : o.creatures) {
      Agent* a = agent(id);
      if (!a || !a->alive) continue;
      a->mind.command = o.command;
      if (a->mind.hunger > 0.8f && dist(a->x, a->z, o.x, o.z) < 30.0) a->mind.hunger -= 0.3f;
    }
    // Demonstration ("Show" mode): the trainer shows the commanded technique
    // to each nearby tamed creature, at most three times per game day.
    if (o.trainer == Trainer::CaptureTrainer && o.demos_today < 3 && std::fmod(t_, cfg_.day_s / 3.0) < cfg_.dt) {
      const int tech = lib_.find("capture_pin");
      for (uint32_t id : o.creatures) {
        Agent* a = agent(id);
        if (!a || !a->alive || dist(a->x, a->z, o.x, o.z) > 60.0) continue;
        // the owner is watched as closely as the bond with it allows
        if (observe(a->mind, sp(*a), lib_, static_cast<uint16_t>(tech), o.id, 0.6f, 0, std::min(1.f, 0.3f + 1.2f * a->mind.bond), 1.0f,
                    true, cfg_.learn)) {
          ++day_.social_acquisitions;
          ++day_.transmissions[static_cast<size_t>(Transmission::FromOwner)];
        }
      }
      ++o.demos_today;
    }
  }
  // newcomers in tamed groups
  for (auto& a : agents_)
    if (a.alive && a.mind.tamed())
      for (auto& o : owners_)
        if (o.id == a.mind.owner && std::find(o.creatures.begin(), o.creatures.end(), a.id) == o.creatures.end())
          o.creatures.push_back(a.id);
}

void Ecosystem::step() {
  rebuild_grid();
  for (size_t i = 0; i < agents_.size(); ++i) {
    Agent& a = agents_[i];
    if (!a.alive) continue;
    if (t_ >= a.next_decision) {
      a.next_decision = t_ + 0.5;
      decide(a);
    }
    execute(a);
  }
  for (auto& a : agents_) {
    if (!a.alive) continue;
    integrate(a);
    needs(a);
  }
  // vegetation regrowth (logistic)
  if (tick_ % 40 == 0)
    for (auto& v : veg_) v = std::min(1.f, v + static_cast<float>(cfg_.regrow_per_s * 40 * cfg_.dt) * (0.2f + v) * (1.f - v));
  owners_step();
  if (tick_ % 40 == 0) respawns();
  t_ += cfg_.dt;
  ++tick_;
}

void Ecosystem::end_of_day() {
  day_.knowers.assign(lib_.size(), 0);
  day_.mean_mastery.assign(lib_.size(), 0.f);
  day_.mean_generation.assign(lib_.size(), 0.f);
  std::vector<uint32_t> gen_n(lib_.size(), 0);
  day_.watched_alive = 0;
  float bond = 0.f, ob = 0.f;
  int tamed = 0;
  for (const auto& a : agents_) {
    if (!a.alive) continue;
    if (a.mind.tamed()) { bond += a.mind.bond; ob += a.mind.obedience[static_cast<size_t>(Command::Capture)]; ++tamed; }
    if (watched_ >= 0 && a.species != watched_) continue;
    ++day_.watched_alive;
    for (const auto& k : a.mind.known) {
      ++day_.knowers[k.tech];
      day_.mean_mastery[k.tech] += k.mastery;
      if (k.source == Source::Observed) { day_.mean_generation[k.tech] += k.generation; ++gen_n[k.tech]; }
    }
  }
  for (size_t t = 0; t < lib_.size(); ++t) {
    if (day_.knowers[t]) day_.mean_mastery[t] /= static_cast<float>(day_.knowers[t]);
    if (gen_n[t]) day_.mean_generation[t] /= static_cast<float>(gen_n[t]);
  }
  day_.mean_bond = tamed ? bond / tamed : 0.f;
  // generations, genetics and bonds of the watched species
  day_.juveniles_alive = 0;
  day_.max_generation = 0;
  day_.mean_innate.fill(0.f);
  std::array<double, 5> bsum{};
  day_.bond_count.fill(0);
  uint32_t nw = 0;
  for (const auto& a : agents_) {
    if (!a.alive || (watched_ >= 0 && a.species != watched_)) continue;
    ++nw;
    if (a.mind.juvenile) ++day_.juveniles_alive;
    day_.max_generation = std::max(day_.max_generation, a.mind.generation);
    for (int i = 0; i < kInstinctCount; ++i) day_.mean_innate[i] += a.mind.innate[i];
    for (const auto& b : a.mind.bonds) { bsum[static_cast<size_t>(b.kind)] += b.strength; ++day_.bond_count[static_cast<size_t>(b.kind)]; }
    if (a.mind.owner) { bsum[static_cast<size_t>(BondKind::Owner)] += a.mind.bond; ++day_.bond_count[static_cast<size_t>(BondKind::Owner)]; }
  }
  if (nw) for (auto& v : day_.mean_innate) v /= static_cast<float>(nw);
  for (size_t k = 0; k < 5; ++k) day_.mean_bond_by_kind[k] = day_.bond_count[k] ? static_cast<float>(bsum[k] / day_.bond_count[k]) : 0.f;
  // bond decay without contact (daily)
  for (auto& a : agents_) {
    if (!a.alive) continue;
    const float decay = sp(a).bonds.bond_decay_per_day;
    for (auto& b : a.mind.bonds) {
      const Agent* o = b.other < index_of_id_.size() ? &agents_[index_of_id_[b.other]] : nullptr;
      const bool contact = o && o->alive && dist(a.x, a.z, o->x, o->z) < 60.0;
      if (!contact) b.strength = std::max(0.f, b.strength - decay);
    }
    a.mind.bonds.erase(std::remove_if(a.mind.bonds.begin(), a.mind.bonds.end(), [](const Bond& b) { return b.strength <= 0.001f; }),
                       a.mind.bonds.end());
  }
  day_.mean_obedience_capture = tamed ? ob / tamed : 0.f;
  for (auto& o : owners_) o.demos_today = 0;
  for (auto& a : agents_) a.captures_today = 0;
  // forgetting, once per day
  const uint32_t today = static_cast<uint32_t>(t_ / cfg_.day_s);
  for (auto& a : agents_)
    if (a.alive) forget(a.mind, lib_, 1.f, a.last_use_day, today);
}

void Ecosystem::run_days(int days, const std::function<void(const DayReport&)>& on_day) {
  const uint64_t ticks_per_day = static_cast<uint64_t>(cfg_.day_s / cfg_.dt);
  for (int d = 0; d < days; ++d) {
    day_ = DayReport{};
    day_.day = static_cast<int>(t_ / cfg_.day_s) + 1;
    day_.per_tech.resize(lib_.size());
    for (uint64_t k = 0; k < ticks_per_day; ++k) step();
    end_of_day();
    if (on_day) on_day(day_);
  }
}

Ecosystem::Explanation Ecosystem::explain(uint32_t id) {
  Explanation ex;
  Agent* a = agent(id);
  if (!a || !a->alive) return ex;
  rebuild_grid();
  uint32_t prey = 0;
  ex.inputs = compute_inputs(*a, prey, ex.ctx);
  ex.scores = score_all(a->mind, sp(*a), lib_, ex.inputs, ex.ctx, a->current, cfg_.learn);
  std::sort(ex.scores.begin(), ex.scores.end(), [](const ScoredTechnique& x, const ScoredTechnique& y) { return x.utility > y.utility; });
  ex.current = a->current;
  return ex;
}

uint64_t Ecosystem::state_hash() const {
  uint64_t h = 0x9E3779B97F4A7C15ULL;
  for (const auto& a : agents_) {
    h = hash_combine(h, a.id);
    h = hash_combine(h, static_cast<uint64_t>(std::llround(a.x * 1000.0)));
    h = hash_combine(h, static_cast<uint64_t>(std::llround(a.z * 1000.0)));
    h = hash_combine(h, a.alive ? 1u : 0u);
    for (const auto& k : a.mind.known) h = hash_combine(h, (static_cast<uint64_t>(k.tech) << 32) ^ static_cast<uint64_t>(std::llround(k.mastery * 1e6)));
  }
  return h;
}

}  // namespace primeva::brain
