#pragma once

// Headless ecosystem used to develop and measure the creature brain.
// It plays the role the game world will play: it computes the brain's Inputs
// from perception, runs the chosen technique through an executor that emits
// MotorCommands, integrates a kinematic stand-in for the motor brain,
// resolves interactions (bites, pins, charges, eating) and feeds outcomes back
// into learning and social transmission. Deterministic for a given seed.

#include <array>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "primeva/brain/mind.hpp"

namespace primeva::brain {

enum class Trainer : uint8_t {
  None,
  CaptureTrainer,  // rewards non-lethal captures, scolds kills (commands "capture")
  HuntTrainer,     // rewards kills on command "hunt"
};

struct EcoConfig {
  uint64_t seed = 1;
  double size_m = 1600.0;
  double dt = 0.25;               // seconds per tick
  double day_s = 7200.0;          // one game day (2 h)
  double veg_cell_m = 25.0;
  double regrow_per_s = 1.0 / 2400.0;
  int water_points = 6;
  double respawn_delay_s = 1200.0;  // immigration: dead creatures replaced by naive newcomers
  bool immigration = true;          // replacement by newcomers (off in generational runs)
  bool reproduction = false;        // births from parents: genetic + cultural inheritance
  float max_population_factor = 2.0f;  // carrying-capacity cap per species (x initial count)
  float mutation_sd = 0.03f;        // instinct mutation at birth
  LearningParams learn;
};

struct Agent {
  uint32_t id = 0;
  int species = 0;
  int group = -1;
  Mind mind;
  double x = 0, z = 0, vx = 0, vz = 0;
  float health = 1.f;     // fraction of toughness
  float stamina = 1.f;
  bool alive = true;
  bool juvenile = false;
  double died_at = -1;
  double captured_until = -1;
  double home_x = 0, home_z = 0;
  // running technique (an "episode")
  int current = -1;          // index into mind.known
  uint8_t ctx = 0;
  double ep_start = 0;
  uint32_t target = 0;
  float ep_damage_taken = 0.f;
  float ep_hunger0 = 0.f;
  bool ep_group = false;
  double next_decision = 0;
  double last_bite = -10;
  double last_threat_seen = -100;
  double threat_since = -100;
  bool called_alarm = false;
  uint16_t captures_today = 0;   // diminishing intrinsic reward of repeated captures
  double last_breed = -1e9;
  double last_novel = 0;
  float tx = 0, tz = 0;      // executor scratch target
  MotorCommand cmd;
  std::vector<uint32_t> last_use_day;
  // perception memory
  struct Seen {
    uint32_t id;
    float x, z, vx, vz;
    double t;
  };
  std::vector<Seen> seen;
  float threat = 0.f;
  uint32_t threat_id = 0;
  float threat_x = 0, threat_z = 0;
};

struct Owner {
  uint32_t id = 0;
  double x = 0, z = 0;
  Trainer trainer = Trainer::None;
  Command command = Command::None;
  std::vector<uint32_t> creatures;
  int demos_today = 0;
};

struct TechniqueDayStats {
  uint32_t episodes = 0, successes = 0;
};

struct DayReport {
  int day = 0;
  std::vector<TechniqueDayStats> per_tech;    // by technique id
  uint32_t kills = 0, captures = 0, deaths_starvation = 0, predator_deaths = 0, prey_deaths = 0, predators_starved = 0;
  uint32_t hunts = 0, hunt_successes = 0;
  // knowledge state of a watched species at the end of the day
  uint32_t watched_alive = 0;
  std::vector<uint32_t> knowers;              // by technique id
  std::vector<float> mean_mastery;            // by technique id, over knowers
  std::vector<float> mean_generation;         // by technique id, over knowers who learned socially
  uint32_t social_acquisitions = 0, discoveries = 0;
  std::vector<uint32_t> kills_by_group, captures_by_group, hunts_by_group;
  // generations & bonds (watched species)
  uint32_t births = 0, juvenile_deaths = 0, juveniles_alive = 0, max_generation = 0, owner_imprinted = 0, provisioned = 0;
  std::array<uint32_t, 4> transmissions{};          // vertical, horizontal, oblique, from owner
  std::array<float, kInstinctCount> mean_innate{};   // genetic instinct means (evolution)
  std::array<float, 5> mean_bond_by_kind{};          // by BondKind
  std::array<uint32_t, 5> bond_count{};
  float mean_bond = 0.f, mean_obedience_capture = 0.f;
};

class Ecosystem {
 public:
  Ecosystem(EcoConfig cfg, const std::vector<SpeciesProfile>& species, const TechniqueLibrary& lib);

  // Spawns a group (herd / pack) of `count` individuals around (x, z).
  int add_group(const std::string& species_id, int count, double x, double z);
  uint32_t add_owner(double x, double z, Trainer trainer);
  void tame_group(int group, uint32_t owner_id, Command command, float initial_bond = 0.4f);
  // Gives every member of `group` technique `tech` (e.g. an innovator).
  void teach(uint32_t agent_id, const std::string& tech, float mastery, Source source);

  void step();
  // Runs whole days; `on_day` receives the report of each finished day.
  void run_days(int days, const std::function<void(const DayReport&)>& on_day);

  void watch_species(const std::string& species_id);
  const std::vector<Agent>& agents() const { return agents_; }
  const TechniqueLibrary& library() const { return lib_; }
  double time() const { return t_; }
  uint64_t state_hash() const;
  uint64_t decisions() const { return decisions_; }

  // "Why did it do that?": the creature's current inputs and the utility
  // breakdown of every technique it could choose (used by the game UI too).
  struct Explanation {
    Inputs inputs{};
    uint8_t ctx = 0;
    std::vector<ScoredTechnique> scores;
    int current = -1;
  };
  Explanation explain(uint32_t id);

 private:
  struct Carcass { double x, z; float meat_kg; double t; };
  struct GroupHunt { uint32_t target = 0; uint32_t leader = 0; double started = -1; std::vector<uint32_t> members; };

  Agent* agent(uint32_t id);
  const SpeciesProfile& sp(const Agent& a) const { return species_[static_cast<size_t>(a.species)]; }
  Agent spawn(int species, int group, double x, double z, bool juvenile);
  void group_waypoint(Agent& a, double radius);
  float growth(const Agent& a) const;               // 0.35 (hatchling) .. 1 (adult) body scale
  void reproduction();
  void give_birth(uint32_t mother_id, uint32_t father_id);
  bool attachment_pos(const Agent& a, double& x, double& z, bool& alive) const;
  bool is_dependent_of(const Agent& young, const Agent& adult) const;

  void rebuild_grid();
  template <typename F> void for_near(double x, double z, double r, F&& f);
  void perceive(Agent& a);
  Inputs compute_inputs(Agent& a, uint32_t& best_prey, uint8_t& ctx);
  void decide(Agent& a);
  void start_episode(Agent& a, int known_index, uint32_t prey);
  void end_episode(Agent& a, float r_intrinsic, bool success);
  void execute(Agent& a);
  void integrate(Agent& a);
  void needs(Agent& a);
  void bite(Agent& hunter, Agent& prey);
  void kill(Agent& prey, Agent* killer);
  bool hunt_step(Agent& a, Agent& prey, bool sneak, bool flank, float flank_side, float mastery);
  float prey_value(const Agent& hunter, const Agent& prey, int packmates) const;
  int packmates_near(const Agent& a, double r) const;
  void owner_feedback(Agent& a, const TechniqueDef& t, bool success, bool killed, float& r_owner);
  void broadcast_observation(const Agent& demo, uint16_t tech, bool success);
  void check_discoveries(Agent& a, const TechniqueDef& t, bool success);
  void respawns();
  void owners_step();
  void end_of_day();

  EcoConfig cfg_;
  std::vector<SpeciesProfile> species_;
  TechniqueLibrary lib_;
  std::vector<Agent> agents_;
  std::vector<Owner> owners_;
  std::vector<Carcass> carcasses_;
  std::vector<GroupHunt> group_hunts_;   // by group id
  std::vector<int> group_species_;
  std::vector<int> group_alive_;                 // per tick: living members per group
  std::vector<double> group_cx_, group_cz_;      // per tick: group centroids
  std::vector<double> group_wx_, group_wz_, group_wt_;  // shared travel waypoint of each group (+ set time)
  std::vector<std::vector<uint32_t>> group_juveniles_;  // per tick: living juveniles of each group
  std::vector<int> initial_population_;                 // per species
  std::vector<std::pair<double, double>> water_;
  std::vector<float> veg_;
  int veg_n_ = 0;
  // spatial hash
  double cell_ = 50.0;
  int grid_n_ = 0;
  std::vector<std::vector<uint32_t>> grid_;
  std::vector<uint32_t> index_of_id_;
  double t_ = 0.0;
  uint64_t tick_ = 0;
  uint64_t decisions_ = 0;
  uint32_t next_id_ = 1;
  int watched_ = -1;
  DayReport day_;
  Rng rng_;
};

}  // namespace primeva::brain
