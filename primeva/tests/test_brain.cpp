#include <cmath>
#include <string>

#include "primeva/brain/ecosystem.hpp"
#include "primeva/json.hpp"
#include "test.hpp"

using namespace primeva;
using namespace primeva::brain;

namespace {
std::string root() {
  for (const char* r : {".", "..", "../.."}) {
    std::FILE* f = std::fopen((std::string(r) + "/data/brain/techniques.json").c_str(), "r");
    if (f) { std::fclose(f); return r; }
  }
  return ".";
}
struct Data {
  std::vector<SpeciesProfile> species;
  TechniqueLibrary lib;
  bool ok = false;
};
const Data& data() {
  static Data d = [] {
    Data x;
    std::string err;
    x.ok = load_species(root() + "/data/creatures/creatures.json", x.species, &err) && x.lib.load(root() + "/data/brain/techniques.json", &err);
    if (!x.ok) std::printf("    data load error: %s\n", err.c_str());
    return x;
  }();
  return d;
}
}  // namespace

PTEST(json_parser_strict_and_complete) {
  const auto v = json::parse(R"({"a": [1, 2.5e1, -0.5, true, false, null], "s": "x\u00e8\n\"q\"", "o": {"k": {}}})");
  CHECK(v.has_value());
  if (v) {
    CHECK((*v)["a"].size() == 6);
    CHECK((*v)["a"][1].num() == 25.0);
    CHECK((*v)["a"][2].num() == -0.5);
    CHECK((*v)["a"][3].boolean());
    CHECK((*v)["a"][5].is_null());
    CHECK((*v)["s"].str() == "x\xc3\xa8\n\"q\"");
    CHECK((*v)["o"]["k"].is_object());
    CHECK((*v)["missing"].is_null());
  }
  json::ParseError e;
  CHECK(!json::parse("{\"a\": 01}", &e).has_value());       // leading zero
  CHECK(!json::parse("[1, 2,]", &e).has_value());            // trailing comma
  CHECK(!json::parse("{\"a\": \"\\x\"}", &e).has_value());   // bad escape
  CHECK(!json::parse("[1] 2", &e).has_value());              // trailing data
  CHECK(!json::parse("\"\\ud800\"", &e).has_value());        // lone surrogate
  std::string deep(1000, '[');
  CHECK(!json::parse(deep, &e).has_value());                 // depth limit, no stack overflow
}

PTEST(brain_data_loads_and_is_consistent) {
  const Data& d = data();
  CHECK(d.ok);
  CHECK(d.species.size() >= 72);
  CHECK(d.lib.size() >= 15);
  const SpeciesProfile* pal = find_species(d.species, "pallidrake");
  CHECK(pal != nullptr);
  if (pal) {
    CHECK(pal->cognition_tier >= 3);           // pack carnivore -> imitation
    CHECK(pal->bonds.alloparental);
    CHECK(pal->sprint_speed > 2.f && pal->sprint_speed < 20.f);
  }
  for (const auto& s : d.species) {
    CHECK(s.cognition_tier >= 1 && s.cognition_tier <= 4);
    CHECK(s.bonds.clutch >= 1 && s.bonds.clutch <= 5);
    CHECK(s.bonds.maturation_days > 0.f);
  }
}

PTEST(offspring_inherit_instincts_not_knowledge) {
  const Data& d = data();
  const SpeciesProfile* pal = find_species(d.species, "pallidrake");
  if (!pal) return;
  Mind mom = make_mind(1, *pal, d.lib, 7), dad = make_mind(2, *pal, d.lib, 7);
  mom.innate.fill(0.2f);
  dad.innate.fill(0.8f);
  const int pf = d.lib.find("pack_flank");
  KnownTechnique k;
  k.tech = static_cast<uint16_t>(pf);
  k.mastery = 0.9f;
  k.source = Source::Discovered;
  mom.known.push_back(k);
  double mean = 0;
  for (uint32_t id = 10; id < 210; ++id) {
    const Mind c = make_offspring(id, *pal, d.lib, 7, mom, &dad, 0.03f);
    CHECK(c.juvenile && c.generation == 1 && c.mother == 1 && c.father == 2);
    CHECK(c.known_index(static_cast<uint16_t>(pf)) < 0);  // culture is not genetic
    for (float v : c.innate) { CHECK(std::abs(v - 0.5f) < 0.1f); mean += v; }
  }
  CHECK(std::abs(mean / (200.0 * kInstinctCount) - 0.5) < 0.01);
}

PTEST(ecosystem_is_deterministic) {
  const Data& d = data();
  auto run = [&]() {
    EcoConfig cfg;
    cfg.seed = 123;
    cfg.reproduction = true;
    cfg.immigration = false;
    Ecosystem e(cfg, d.species, d.lib);
    e.add_group("pallidrake", 5, 600, 800);
    e.add_group("rhynchon", 8, 800, 800);
    for (int k = 0; k < 6000; ++k) e.step();
    return e.state_hash();
  };
  const uint64_t a = run(), b = run();
  CHECK(a == b);
}

PTEST(bonds_attachment_and_social_learning_by_bond) {
  const Data& d = data();
  const SpeciesProfile* pal = find_species(d.species, "pallidrake");
  if (!pal) return;
  Mind young = make_mind(5, *pal, d.lib, 3);
  young.juvenile = true;
  young.strengthen(1, BondKind::Parent, 0.6f);
  young.strengthen(1, BondKind::Parent, 0.6f);
  CHECK(std::abs(young.bond_with(1) - 1.0f) < 1e-6f);  // clamped
  CHECK(young.bond_with(99) == 0.f);
  young.owner = 1000000;
  young.bond = 0.5f;
  young.strengthen(1000000, BondKind::Owner, 0.2f);
  CHECK(std::abs(young.bond_with(1000000) - 0.7f) < 1e-6f);
  // follow_attachment is only usable with an attachment figure
  const TechniqueDef& follow = d.lib[static_cast<size_t>(d.lib.find("follow_attachment"))];
  CHECK(!can_use(follow, *pal, young));
  young.attachment = 1;
  CHECK(can_use(follow, *pal, young));
  // provisioning only for parents with dependents
  const TechniqueDef& prov = d.lib[static_cast<size_t>(d.lib.find("provision_young"))];
  Mind adult = make_mind(6, *pal, d.lib, 3);
  CHECK(!can_use(prov, *pal, adult));
  adult.dependents = 2;
  CHECK(can_use(prov, *pal, adult));
  // imitation needs repeated exposures: one observation never suffices
  LearningParams lp;
  const int pf = d.lib.find("pack_flank");
  Mind obs = make_mind(7, *pal, d.lib, 3);
  CHECK(!observe(obs, *pal, d.lib, static_cast<uint16_t>(pf), 1, 0.9f, 0, 1.f, 1.f, true, lp));
  int acquired_after = -1;
  for (int k = 2; k <= 60 && acquired_after < 0; ++k)
    if (observe(obs, *pal, d.lib, static_cast<uint16_t>(pf), 1, 0.9f, 0, 1.f, 1.f, true, lp)) acquired_after = k;
  CHECK(acquired_after >= 4);
  CHECK(obs.mastery_of(static_cast<uint16_t>(pf)) <= 0.45f);
}
