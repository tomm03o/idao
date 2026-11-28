// brain_lab — experiments on the creature brain (headless ecosystem).
//
//   brain_lab learning [--days 12] [--seeds 3]     full brain vs no social learning vs frozen learning
//   brain_lab culture  [--days 15]                 diffusion of an invented technique through packs
//   brain_lab tamed    [--days 12]                 same brain: wild pack vs pack trained by an owner
//   brain_lab bench    [--n 500,2000,8000]         CPU cost per creature
//   brain_lab explain                              "why did it do that?" for one creature
//
// Data: data/creatures/creatures.json, data/brain/techniques.json
// Output CSVs: out/brain/*.csv

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <map>
#include <string>
#include <vector>

#include "primeva/brain/ecosystem.hpp"

using namespace primeva::brain;

namespace {

struct Args {
  std::map<std::string, std::string> kv;
  double num(const std::string& k, double d) const { auto it = kv.find(k); return it == kv.end() ? d : std::atof(it->second.c_str()); }
  std::string get(const std::string& k, const std::string& d) const { auto it = kv.find(k); return it == kv.end() ? d : it->second; }
};

std::string root_dir() {
  // tools are run from primeva/ or primeva/build
  for (const char* r : {".", "..", "../.."})
    if (std::filesystem::exists(std::string(r) + "/data/brain/techniques.json")) return r;
  return ".";
}

struct Data {
  std::vector<SpeciesProfile> species;
  TechniqueLibrary lib;
};

Data load_data() {
  Data d;
  std::string err;
  const std::string r = root_dir();
  if (!load_species(r + "/data/creatures/creatures.json", d.species, &err) || !d.lib.load(r + "/data/brain/techniques.json", &err)) {
    std::fprintf(stderr, "data error: %s\n", err.c_str());
    std::exit(2);
  }
  return d;
}

// Triassic badlands community (same biome as the motor-gym terrain).
void populate(Ecosystem& e, int packs, int herds_small, int herds_large) {
  const double S = 1600.0;
  for (int p = 0; p < packs; ++p) {
    const double a = 6.2831853 * p / packs;
    e.add_group("pallidrake", 5, S / 2 + 420 * std::cos(a), S / 2 + 420 * std::sin(a));
  }
  for (int h = 0; h < herds_small; ++h) {
    const double a = 6.2831853 * (h + 0.5) / herds_small;
    e.add_group("rhynchon", 8, S / 2 + 300 * std::cos(a), S / 2 + 300 * std::sin(a));
  }
  for (int h = 0; h < herds_large; ++h) e.add_group("placeron", 6, S / 2 + (h ? 200 : -200), S / 2);
}

int tech(const Ecosystem& e, const char* id) { return e.library().find(id); }

std::FILE* open_csv(const std::string& name, const char* header) {
  std::filesystem::create_directories(root_dir() + "/out/brain");
  std::FILE* f = std::fopen((root_dir() + "/out/brain/" + name).c_str(), "w");
  std::fprintf(f, "%s\n", header);
  return f;
}

// ---------------------------------------------------------------------------
int cmd_learning(const Args& a) {
  const Data d = load_data();
  const int days = static_cast<int>(a.num("days", 12)), seeds = static_cast<int>(a.num("seeds", 3));
  std::FILE* csv = open_csv("learning.csv",
                            "condition,seed,day,hunts,hunt_success,kills,pred_starved,pack_flank_knowers,pack_flank_mastery,"
                            "pursuit_mastery,stalk_mastery,pack_flank_generation,social_acq,discoveries,pred_alive");
  struct Cond { const char* name; bool learning, social; };
  const Cond conds[] = {{"full", true, true}, {"no_social", true, false}, {"frozen", false, false}};
  std::printf("%-10s %5s | %7s %8s %6s %8s | %9s %8s %8s\n", "condition", "days", "hunts/d", "success", "kills/d", "starved*",
              "flank_kn", "flank_m", "purs_m");
  for (const Cond& c : conds) {
    double early_s = 0, late_s = 0, early_k = 0, late_k = 0, late_h = 0, early_h = 0, starve = 0, kn = 0, fm = 0, pm = 0;
    for (int seed = 1; seed <= seeds; ++seed) {
      EcoConfig cfg;
      cfg.seed = static_cast<uint64_t>(seed) * 7919u;
      cfg.learn.learning = c.learning;
      cfg.learn.social = c.social;
      Ecosystem e(cfg, d.species, d.lib);
      populate(e, 4, 6, 2);
      e.watch_species("pallidrake");
      const int pf = tech(e, "pack_flank"), pu = tech(e, "pursuit"), st = tech(e, "stalk_ambush");
      e.run_days(days, [&](const DayReport& r) {
        const double succ = r.hunts ? static_cast<double>(r.hunt_successes) / r.hunts : 0.0;
        std::fprintf(csv, "%s,%d,%d,%u,%.4f,%u,%u,%u,%.4f,%.4f,%.4f,%.3f,%u,%u,%u\n", c.name, seed, r.day, r.hunts, succ, r.kills,
                     r.predators_starved, r.knowers[pf], r.mean_mastery[pf], r.mean_mastery[pu], r.mean_mastery[st],
                     r.mean_generation[pf], r.social_acquisitions, r.discoveries, r.watched_alive);
        if (r.day <= 2) { early_s += succ; early_k += r.kills; early_h += r.hunts; }
        if (r.day > days - 2) {
          late_s += succ; late_k += r.kills; late_h += r.hunts;
          kn += r.watched_alive ? static_cast<double>(r.knowers[pf]) / r.watched_alive : 0.0;
          fm += r.mean_mastery[pf];
          pm += r.mean_mastery[pu];
        }
        starve += r.predators_starved;
      });
    }
    const double n2 = 2.0 * seeds;
    std::printf("%-10s %5s | %7.1f %7.1f%% %6.1f %8s | %8s %8s %8s\n", c.name, "1-2", early_h / n2, 100 * early_s / n2, early_k / n2, "", "", "", "");
    std::printf("%-10s %5s | %7.1f %7.1f%% %6.1f %8.1f | %7.0f%% %8.3f %8.3f\n", "", (std::to_string(days - 1) + "-" + std::to_string(days)).c_str(),
                late_h / n2, 100 * late_s / n2, late_k / n2, starve / seeds, 100 * kn / n2, fm / n2, pm / n2);
  }
  std::fclose(csv);
  std::printf("\nhunts = initiated hunts (ambush, pursuit, pack flank); success = initiated hunts ending in a kill\n"
              "*starved = predators dead of starvation over the whole run (per seed)\nper-day data: out/brain/learning.csv\n");
  return 0;
}

int cmd_culture(const Args& a) {
  const Data d = load_data();
  const int days = static_cast<int>(a.num("days", 15)), seeds = static_cast<int>(a.num("seeds", 6));
  std::FILE* csv = open_csv("culture.csv", "seed,day,pack,alive,knowers,mean_mastery,max_generation,innovator_alive");
  std::printf("pack 0 has ONE innovator who knows pack_flank (mastery 0.8); independent invention disabled,\n"
              "so the technique can only spread by observation - or die with its holders.\n\n");
  std::printf("%4s | %-28s | %-16s | %-16s | %s\n", "seed", "pack 0: knowers/alive by day", "pack 1 (final)", "pack 2 (final)", "outcome");
  int spread = 0, lost = 0;
  for (int seed = 1; seed <= seeds; ++seed) {
    EcoConfig cfg;
    cfg.seed = 4242u + static_cast<uint64_t>(seed) * 131u;
    cfg.learn.discovery_scale = 0.f;
    Ecosystem e(cfg, d.species, d.lib);
    populate(e, 3, 5, 2);
    e.watch_species("pallidrake");
    uint32_t innovator = 0;
    for (const auto& ag : e.agents()) if (ag.group == 0) { innovator = ag.id; break; }
    e.teach(innovator, "pack_flank", 0.8f, Source::Discovered);
    const int pf = tech(e, "pack_flank");
    std::string trace;
    int fin_kn[3] = {0, 0, 0}, fin_alive[3] = {0, 0, 0}, fin_gen = 0;
    e.run_days(days, [&](const DayReport& r) {
      bool inn_alive = false;
      for (int g = 0; g < 3; ++g) {
        int alive = 0, kn = 0, maxgen = 0;
        double m = 0;
        for (const auto& ag : e.agents()) {
          if (!ag.alive || ag.group != g) continue;
          if (ag.id == innovator) inn_alive = true;
          ++alive;
          const int ki = ag.mind.known_index(static_cast<uint16_t>(pf));
          if (ki >= 0) { ++kn; m += ag.mind.known[static_cast<size_t>(ki)].mastery; maxgen = std::max<int>(maxgen, ag.mind.known[static_cast<size_t>(ki)].generation); }
        }
        std::fprintf(csv, "%d,%d,%d,%d,%d,%.4f,%d,%d\n", seed, r.day, g, alive, kn, kn ? m / kn : 0.0, maxgen, inn_alive ? 1 : 0);
        fin_kn[g] = kn; fin_alive[g] = alive;
        if (g == 0) { fin_gen = std::max(fin_gen, maxgen); if (r.day % 3 == 0) trace += std::to_string(kn) + "/" + std::to_string(alive) + " "; }
      }
    });
    const bool ok = fin_kn[0] >= 3;
    if (ok) ++spread;
    if (fin_kn[0] == 0) ++lost;
    char p1[32], p2[32];
    std::snprintf(p1, sizeof p1, "%d/%d", fin_kn[1], fin_alive[1]);
    std::snprintf(p2, sizeof p2, "%d/%d", fin_kn[2], fin_alive[2]);
    std::printf("%4d | %-28s | %-16s | %-16s | %s (max generation %d)\n", seed, trace.c_str(), p1, p2,
                ok ? "TRADITION ESTABLISHED" : (fin_kn[0] == 0 ? "LOST with its holders" : "fragile"), fin_gen);
  }
  std::fclose(csv);
  std::printf("\nestablished in %d/%d runs, lost in %d/%d (days %d)\n", spread, seeds, lost, seeds, days);
  return 0;
}

int cmd_tamed(const Args& a) {
  const Data d = load_data();
  const int days = static_cast<int>(a.num("days", 12));
  EcoConfig cfg;
  cfg.seed = 777;
  Ecosystem e(cfg, d.species, d.lib);
  const int wild = e.add_group("pallidrake", 5, 500, 800);
  const int tamed = e.add_group("pallidrake", 5, 1100, 800);
  for (int h = 0; h < 6; ++h) e.add_group("rhynchon", 8, 300 + 200 * h, h % 2 ? 600 : 1000);
  const uint32_t owner = e.add_owner(1100, 800, Trainer::CaptureTrainer);
  e.tame_group(tamed, owner, Command::Capture, 0.4f);
  e.watch_species("pallidrake");
  const int cp = tech(e, "capture_pin");
  std::FILE* csv = open_csv("tamed.csv", "day,group,hunts,kills,captures,capture_knowers,capture_mastery,bond,obedience_capture");
  std::printf("same species, same brain. pack %d wild; pack %d tamed (owner rewards captures, scolds kills, command=capture)\n\n", wild, tamed);
  std::printf("%4s | %-30s | %-46s\n", "day", "WILD: hunts kills captures", "TAMED: hunts kills captures  knows_capture  bond  obey");
  e.run_days(days, [&](const DayReport& r) {
    auto at = [](const std::vector<uint32_t>& v, int g) { return static_cast<size_t>(g) < v.size() ? v[static_cast<size_t>(g)] : 0u; };
    int kn[2] = {0, 0};
    double m[2] = {0, 0};
    for (const auto& ag : e.agents()) {
      if (!ag.alive || (ag.group != wild && ag.group != tamed)) continue;
      const int gi = ag.group == wild ? 0 : 1;
      const int ki = ag.mind.known_index(static_cast<uint16_t>(cp));
      if (ki >= 0) { ++kn[gi]; m[gi] += ag.mind.known[static_cast<size_t>(ki)].mastery; }
    }
    for (int gi = 0; gi < 2; ++gi) {
      const int g = gi ? tamed : wild;
      std::fprintf(csv, "%d,%d,%u,%u,%u,%d,%.4f,%.4f,%.4f\n", r.day, g, at(r.hunts_by_group, g), at(r.kills_by_group, g),
                   at(r.captures_by_group, g), kn[gi], kn[gi] ? m[gi] / kn[gi] : 0.0, gi ? r.mean_bond : 0.0, gi ? r.mean_obedience_capture : 0.0);
    }
    std::printf("%4d | %8u %6u %8u        | %8u %6u %8u   %5d (m=%.2f)  %.2f  %.2f\n", r.day, at(r.hunts_by_group, wild), at(r.kills_by_group, wild),
                at(r.captures_by_group, wild), at(r.hunts_by_group, tamed), at(r.kills_by_group, tamed), at(r.captures_by_group, tamed), kn[1],
                kn[1] ? m[1] / kn[1] : 0.0, r.mean_bond, r.mean_obedience_capture);
  });
  std::fclose(csv);
  return 0;
}

// Generations: real births (no immigration). Instincts are inherited with
// mutation (natural selection acts on them); techniques are inherited only
// culturally, through bonded observation.
int cmd_generations(const Args& a) {
  const Data d = load_data();
  const int days = static_cast<int>(a.num("days", 40)), seeds = static_cast<int>(a.num("seeds", 2));
  std::FILE* csv = open_csv("generations.csv",
                            "seed,day,pred_alive,juveniles,births,juvenile_deaths,max_generation,flank_knowers,vertical,horizontal,oblique,"
                            "bond_parent,bond_packmate,bond_mate,aggression,fear,curiosity,sociability,patience,playfulness,provisioned,prey_alive");
  for (int seed = 1; seed <= seeds; ++seed) {
    EcoConfig cfg;
    cfg.seed = 9001u + static_cast<uint64_t>(seed) * 17u;
    cfg.immigration = false;
    cfg.reproduction = true;
    cfg.max_population_factor = 2.0f;
    Ecosystem e(cfg, d.species, d.lib);
    populate(e, 4, 6, 2);
    e.watch_species("pallidrake");
    const int pf = tech(e, "pack_flank");
    std::printf("\nseed %d\n%4s %6s %5s %6s %5s %5s | %8s | %-11s | %-17s | %-29s\n", seed, "day", "preds", "juv", "births", "gen",
                "prey", "flank%", "transm V/H/O", "bond par/pack/mate", "instincts agg fear soc pat cur");
    uint32_t births = 0, jd = 0;
    std::array<uint32_t, 4> tr{};
    e.run_days(days, [&](const DayReport& r) {
      births += r.births; jd += r.juvenile_deaths;
      for (size_t k = 0; k < 4; ++k) tr[k] += r.transmissions[k];
      uint32_t prey = 0;
      for (const auto& ag : e.agents()) if (ag.alive && d.species[static_cast<size_t>(ag.species)].diet == Diet::Herbivore) ++prey;
      const auto& mi = r.mean_innate;
      std::fprintf(csv, "%d,%d,%u,%u,%u,%u,%u,%u,%u,%u,%u,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%u,%u\n", seed, r.day, r.watched_alive,
                   r.juveniles_alive, r.births, r.juvenile_deaths, r.max_generation, r.knowers[pf], r.transmissions[0], r.transmissions[1],
                   r.transmissions[2], r.mean_bond_by_kind[0], r.mean_bond_by_kind[3], r.mean_bond_by_kind[2], mi[0], mi[1], mi[2], mi[4], mi[5],
                   mi[6], r.provisioned, prey);
      if (r.day % 4 == 0 || r.day == 1)
        std::printf("%4d %6u %5u %6u %5u %5u | %7.0f%% | %3u/%3u/%3u | %.2f / %.2f / %.2f | %.2f %.2f %.2f %.2f %.2f\n", r.day, r.watched_alive,
                    r.juveniles_alive, births, r.max_generation, prey, r.watched_alive ? 100.0 * r.knowers[pf] / r.watched_alive : 0.0, tr[0],
                    tr[1], tr[2], r.mean_bond_by_kind[0], r.mean_bond_by_kind[3], r.mean_bond_by_kind[2], mi[0], mi[1], mi[4], mi[5], mi[2]);
    });
    std::printf("total births %u, juvenile deaths %u\n", births, jd);
  }
  std::fclose(csv);
  return 0;
}

// Imprinting: a tamed pack breeds near its owner; hatchlings imprint on the
// owner instead of the mother and treat it as their parent figure.
int cmd_imprint(const Args& a) {
  const Data d = load_data();
  const int days = static_cast<int>(a.num("days", 12));
  EcoConfig cfg;
  cfg.seed = 31337;
  cfg.immigration = false;
  cfg.reproduction = true;
  Ecosystem e(cfg, d.species, d.lib);
  const int wild = e.add_group("pallidrake", 6, 450, 800);
  const int tamed = e.add_group("pallidrake", 6, 1150, 800);
  for (int h = 0; h < 6; ++h) e.add_group("rhynchon", 8, 300 + 200 * h, h % 2 ? 600 : 1000);
  const uint32_t owner = e.add_owner(1150, 800, Trainer::CaptureTrainer);
  e.tame_group(tamed, owner, Command::Capture, 0.4f);
  e.watch_species("pallidrake");
  const int cp = tech(e, "capture_pin");
  std::FILE* csv = open_csv("imprint.csv", "day,cohort,count,owner_bond,parent_bond,attached_to_owner,knows_capture,capture_mastery,obedience");
  std::printf("tamed pack (owner trains captures) vs wild pack, both breeding. Cohorts:\n"
              "  W-young: wild-born juveniles | T-adult: adults tamed by trust | T-imprint: hatched near the owner\n\n");
  std::printf("%4s | %-34s | %-34s | %-34s\n", "day", "W-young n parentBond knowsCapture", "T-adult n ownerBond knowsCap obey",
              "T-imprint n ownerBond knowsCap obey");
  e.run_days(days, [&](const DayReport& r) {
    struct C { int n = 0, att = 0, kn = 0; double ob = 0, pb = 0, m = 0, obey = 0; } c[3];
    for (const auto& ag : e.agents()) {
      if (!ag.alive || (ag.group != wild && ag.group != tamed)) continue;
      int k;
      if (ag.group == wild) { if (ag.mind.generation == 0) continue; k = 0; }
      else k = ag.mind.generation == 0 ? 1 : (ag.mind.attachment == owner ? 2 : 1);
      C& x = c[k];
      ++x.n;
      x.ob += ag.mind.bond;
      x.pb += ag.mind.bond_with(ag.mind.mother);
      x.att += ag.mind.attachment == owner ? 1 : 0;
      const int ki = ag.mind.known_index(static_cast<uint16_t>(cp));
      if (ki >= 0) { ++x.kn; x.m += ag.mind.known[static_cast<size_t>(ki)].mastery; }
      x.obey += ag.mind.obedience[static_cast<size_t>(Command::Capture)];
    }
    const char* names[3] = {"wild_young", "tamed_adult", "owner_imprinted"};
    for (int k = 0; k < 3; ++k)
      std::fprintf(csv, "%d,%s,%d,%.4f,%.4f,%d,%d,%.4f,%.4f\n", r.day, names[k], c[k].n, c[k].n ? c[k].ob / c[k].n : 0.0,
                   c[k].n ? c[k].pb / c[k].n : 0.0, c[k].att, c[k].kn, c[k].kn ? c[k].m / c[k].kn : 0.0, c[k].n ? c[k].obey / c[k].n : 0.0);
    auto f = [](const C& x, bool owner_cols) {
      char b[80];
      if (owner_cols) std::snprintf(b, sizeof b, "%2d  %.2f  %2d/%-2d  %.2f", x.n, x.n ? x.ob / x.n : 0.0, x.kn, x.n, x.n ? x.obey / x.n : 0.0);
      else std::snprintf(b, sizeof b, "%2d  %.2f  %2d/%-2d", x.n, x.n ? x.pb / x.n : 0.0, x.kn, x.n);
      return std::string(b);
    };
    std::printf("%4d | %-34s | %-34s | %-34s\n", r.day, f(c[0], false).c_str(), f(c[1], true).c_str(), f(c[2], true).c_str());
  });
  std::fclose(csv);
  return 0;
}

int cmd_bench(const Args& a) {
  const Data d = load_data();
  std::string list = a.get("n", "500,2000,8000");
  std::printf("%8s %10s %14s %16s %14s\n", "agents", "world_km", "us/agent/tick", "decisions/s(cpu)", "realtime_x");
  size_t pos = 0;
  while (pos < list.size()) {
    const size_t c = list.find(',', pos);
    const int n = std::atoi(list.substr(pos, c == std::string::npos ? std::string::npos : c - pos).c_str());
    pos = c == std::string::npos ? list.size() : c + 1;
    EcoConfig cfg;
    cfg.seed = 99;
    // keep density constant: 300 agents per 1.6 km square
    cfg.size_m = 1600.0 * std::sqrt(n / 300.0);
    Ecosystem e(cfg, d.species, d.lib);
    const int groups = std::max(1, n / 7);
    for (int g = 0; g < groups; ++g) {
      const double gx = (0.1 + 0.8 * ((g * 0.618034) - std::floor(g * 0.618034))) * cfg.size_m;
      const double gz = (0.1 + 0.8 * ((g * 0.754877) - std::floor(g * 0.754877))) * cfg.size_m;
      if (g % 5 == 0) e.add_group("pallidrake", 5, gx, gz);
      else if (g % 5 == 4) e.add_group("placeron", 6, gx, gz);
      else e.add_group("rhynchon", 8, gx, gz);
    }
    const size_t agents = e.agents().size();
    for (int k = 0; k < 400; ++k) e.step();  // warm-up
    const uint64_t d0 = e.decisions();
    const auto t0 = std::chrono::steady_clock::now();
    const int ticks = 2400;  // 10 simulated minutes
    for (int k = 0; k < ticks; ++k) e.step();
    const double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::printf("%8zu %10.2f %14.2f %16.0f %14.1f\n", agents, cfg.size_m / 1000.0, s * 1e6 / (static_cast<double>(ticks) * agents),
                static_cast<double>(e.decisions() - d0) / s, ticks * cfg.dt / s);
  }
  return 0;
}

int cmd_explain(const Args& a) {
  const Data d = load_data();
  EcoConfig cfg;
  cfg.seed = 5;
  Ecosystem e(cfg, d.species, d.lib);
  populate(e, 2, 4, 1);
  e.run_days(static_cast<int>(a.num("days", 2)), nullptr);
  const SpeciesProfile* sp = find_species(d.species, "pallidrake");
  int shown = 0;
  for (const auto& ag : e.agents()) {
    if (!ag.alive || d.species[static_cast<size_t>(ag.species)].id != "pallidrake") continue;
    std::printf("Pallidrake #%u  (tier %d)  hunger %.2f thirst %.2f fatigue %.2f\n", ag.id, sp->cognition_tier, ag.mind.hunger, ag.mind.thirst, ag.mind.fatigue);
    std::printf("instincts:");
    for (int i = 0; i < kInstinctCount; ++i) std::printf(" %s=%.2f", std::string(instinct_name(static_cast<Instinct>(i))).c_str(), ag.mind.instinct(static_cast<Instinct>(i)));
    std::printf("\n%-14s %-10s %7s %6s %7s  %s\n", "technique", "source", "mastery", "uses", "succ%", "best contexts (q)");
    for (const auto& k : ag.mind.known) {
      static const char* src[] = {"innate", "invented", "observed", "player"};
      std::printf("%-14s %-10s %7.2f %6u %6.0f%% ", d.lib[k.tech].id.c_str(), src[static_cast<int>(k.source)], k.mastery, k.uses,
                  k.uses ? 100.0 * k.successes / k.uses : 0.0);
      for (int c = 0; c < kContexts; ++c) if (k.n[c] >= 3) std::printf(" c%d:%+.2f", c, k.q[c]);
      if (k.source == Source::Observed) std::printf("   <- learned from #%u (generation %u)", k.teacher, k.generation);
      std::printf("\n");
    }
    const auto ex = e.explain(ag.id);
    static const char* in_names[] = {"hunger", "thirst", "fatigue", "threat", "threat_new", "threat_weaker", "prey_quality", "prey_near",
                                     "carcass_near", "herd_near", "packmates", "alone", "health", "stamina", "boredom",
                                     "group_hunt", "attachment_far", "attachment_threat", "juvenile", "young_hungry",
                                     "young_threat", "young_near"};
    static_assert(sizeof(in_names) / sizeof(in_names[0]) == kInputCount, "input names out of sync");
    std::printf("\nperceived inputs:");
    for (int i = 0; i < kInputCount; ++i) if (ex.inputs[static_cast<size_t>(i)] > 0.005f) std::printf(" %s=%.2f", in_names[i], ex.inputs[static_cast<size_t>(i)]);
    std::printf("\n%-14s %8s %8s %8s %8s %8s\n", "why:", "utility", "consider", "instinct", "value", "explore");
    for (const auto& sc : ex.scores)
      std::printf("%-14s %8.3f %8.3f %8.3f %8.3f %8.3f%s\n", d.lib[ag.mind.known[static_cast<size_t>(sc.known_index)].tech].id.c_str(), sc.utility,
                  sc.consideration, sc.instinct, sc.value, sc.explore, sc.known_index == ex.current ? "   <- doing this" : "");
    if (++shown >= static_cast<int>(a.num("count", 1))) break;
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: brain_lab <learning|culture|tamed|generations|imprint|bench|explain> [--options]\n");
    return 2;
  }
  Args a;
  for (int i = 2; i + 1 < argc; i += 2) a.kv[std::string(argv[i]).substr(2)] = argv[i + 1];
  const std::string cmd = argv[1];
  if (cmd == "learning") return cmd_learning(a);
  if (cmd == "culture") return cmd_culture(a);
  if (cmd == "tamed") return cmd_tamed(a);
  if (cmd == "bench") return cmd_bench(a);
  if (cmd == "generations") return cmd_generations(a);
  if (cmd == "imprint") return cmd_imprint(a);
  if (cmd == "explain") return cmd_explain(a);
  std::fprintf(stderr, "unknown command %s\n", cmd.c_str());
  return 2;
}
