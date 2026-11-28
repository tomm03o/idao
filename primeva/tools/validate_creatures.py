#!/usr/bin/env python3
"""Validate primeva/data/creatures/creatures.json against schema + distribution rules.

Usage: python3 tools/validate_creatures.py [path/to/creatures.json]
Exits 0 on success, 1 on any failure.
"""
import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent / "data" / "creatures" / "creatures.json"

ERAS = ["carboniferous", "permian", "triassic", "jurassic", "cretaceous", "paleogene", "neogene", "pleistocene"]
BIOMES = """carboniferous_coal_swamp carboniferous_giant_fern_forest permian_red_desert permian_salt_flats
triassic_conifer_badlands triassic_rift_lakes jurassic_fern_prairie jurassic_araucaria_forest
jurassic_lagoon_archipelago cretaceous_floodplain_delta cretaceous_angiosperm_forest cretaceous_volcanic_highlands
cretaceous_chalk_coast paleogene_tropical_rainforest neogene_savanna pleistocene_mammoth_steppe
pleistocene_glacial_alps shallow_reef_sea open_ocean_pelagic karst_caves lava_tubes crystal_geode_caverns
underground_rivers fungal_deep_caverns abyssal_magma_depths""".split()
UNDERGROUND_BIOMES = {"karst_caves", "lava_tubes", "crystal_geode_caverns", "underground_rivers",
                      "fungal_deep_caverns", "abyssal_magma_depths"}
LAYERS = ["surface", "underground", "aquatic", "aerial", "amphibious"]
DIETS = ["carnivore", "herbivore", "omnivore", "piscivore", "insectivore", "scavenger", "filter_feeder", "lithovore"]
LOCO = ["biped", "quadruped", "facultative_biped", "flyer", "glider", "swimmer", "burrower", "climber", "crawler"]
SOCIAL = ["solitary", "pair", "pack", "herd", "colony", "swarm"]
ROLES = ["mount", "flying_mount", "aquatic_mount", "combat", "harvest", "dig", "transport", "scout", "guard",
         "fishing", "capture", "utility", "companion"]
SKILLS = """hunting_ambush hunting_pursuit hunting_cooperative fishing digging_burrowing foraging harvesting
defense_guarding defense_herd_circle combat_melee combat_ranged evasion stealth tracking scouting_aerial
transport_hauling construction climbing swimming_diving capture_nonlethal communication territory_patrol
retrieval_rescue""".split()
TAMING = ["trust_building", "imprinting_egg", "dominance", "feeding_passive", "rescue_bond", "mimic_courtship",
          "symbiosis_offer"]
SENSES = ["vision", "smell", "hearing", "tremor", "thermal", "echolocation"]
INSTINCTS = ["aggression", "fear", "curiosity", "territoriality", "sociability", "patience", "playfulness"]
KEYS = {"id", "name", "inspiration", "era", "habitats", "layer", "size", "diet", "locomotion", "senses", "social",
        "instincts", "skill_affinity", "innate_techniques", "roles", "dig", "taming", "abilities", "wild_behavior",
        "tier"}

errors = []


def err(cid, msg):
    errors.append(f"[{cid}] {msg}")


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def unit(x):
    return num(x) and 0 <= x <= 1


def nonempty_str(x):
    return isinstance(x, str) and x.strip() != ""


def check_creature(c):
    cid = c.get("id", "<no id>")
    if set(c) != KEYS:
        err(cid, f"keys mismatch: missing={sorted(KEYS - set(c))} extra={sorted(set(c) - KEYS)}")
        return
    import re
    if not (isinstance(c["id"], str) and re.fullmatch(r"[a-z][a-z0-9_]*", c["id"])):
        err(cid, "id must be snake_case")
    if not nonempty_str(c["name"]):
        err(cid, "name empty")
    if not (isinstance(c["inspiration"], list) and c["inspiration"] and all(nonempty_str(x) for x in c["inspiration"])):
        err(cid, "inspiration must be non-empty list of strings")
    if c["era"] not in ERAS:
        err(cid, f"bad era {c['era']}")
    h = c["habitats"]
    if not (isinstance(h, list) and 1 <= len(h) <= 4 and len(set(h)) == len(h)):
        err(cid, "habitats must be 1-4 unique ids")
    else:
        for b in h:
            if b not in BIOMES:
                err(cid, f"unknown biome {b}")
    if c["layer"] not in LAYERS:
        err(cid, f"bad layer {c['layer']}")
    s = c["size"]
    if not (isinstance(s, dict) and set(s) == {"length_m", "height_m", "mass_kg"} and all(num(v) and v > 0 for v in s.values())):
        err(cid, "bad size")
    if c["diet"] not in DIETS:
        err(cid, f"bad diet {c['diet']}")
    lo = c["locomotion"]
    if not (isinstance(lo, list) and lo and len(set(lo)) == len(lo) and all(x in LOCO for x in lo)):
        err(cid, "bad locomotion")
    se = c["senses"]
    if not (isinstance(se, dict) and set(se) == set(SENSES) and all(unit(v) for v in se.values())):
        err(cid, "bad senses")
    so = c["social"]
    if not (isinstance(so, dict) and set(so) == {"structure", "group_size"} and so["structure"] in SOCIAL):
        err(cid, "bad social")
    else:
        g = so["group_size"]
        if not (isinstance(g, list) and len(g) == 2 and all(isinstance(x, int) for x in g) and 1 <= g[0] <= g[1]):
            err(cid, "bad group_size")
    ins = c["instincts"]
    if not (isinstance(ins, dict) and set(ins) == set(INSTINCTS) and all(unit(v) for v in ins.values())):
        err(cid, "bad instincts")
    sk = c["skill_affinity"]
    if not (isinstance(sk, dict) and 4 <= len(sk) <= 10 and all(k in SKILLS and unit(v) for k, v in sk.items())):
        err(cid, f"bad skill_affinity (need 4-10 valid entries, got {len(sk) if isinstance(sk, dict) else '?'})")
    t = c["innate_techniques"]
    if not (isinstance(t, list) and 2 <= len(t) <= 5 and all(isinstance(x, str) and re.fullmatch(r"[a-z][a-z0-9_]*", x) for x in t)):
        err(cid, "innate_techniques must be 2-5 snake_case names")
    r = c["roles"]
    if not (isinstance(r, list) and r and len(set(r)) == len(r) and all(x in ROLES for x in r)):
        err(cid, "bad roles")
    d = c["dig"]
    if not (isinstance(d, dict) and set(d) == {"max_hardness", "speed"} and num(d["max_hardness"])
            and 0 <= d["max_hardness"] <= 10 and unit(d["speed"])):
        err(cid, "bad dig")
    ta = c["taming"]
    if not (isinstance(ta, dict) and set(ta) == {"method", "description"} and ta["method"] in TAMING and nonempty_str(ta["description"])):
        err(cid, "bad taming")
    ab = c["abilities"]
    if not (isinstance(ab, list) and 2 <= len(ab) <= 4 and all(isinstance(a, dict) and set(a) == {"name", "description"}
                                                               and nonempty_str(a["name"]) and nonempty_str(a["description"]) for a in ab)):
        err(cid, "abilities must be 2-4 {name,description}")
    if not nonempty_str(c["wild_behavior"]):
        err(cid, "wild_behavior empty")
    if not (isinstance(c["tier"], int) and 1 <= c["tier"] <= 5):
        err(cid, "tier must be int 1..5")

    # ---- coherence checks (only if basic types are fine) ----
    if errors and any(e.startswith(f"[{cid}]") for e in errors):
        return
    if c["layer"] == "underground":
        bad = [b for b in c["habitats"] if b not in UNDERGROUND_BIOMES]
        if bad:
            err(cid, f"underground layer but non-underground habitats {bad}")
    if c["layer"] == "aerial" and not ({"flyer", "glider"} & set(lo)):
        err(cid, "aerial layer needs flyer/glider locomotion")
    if c["layer"] in ("aquatic", "amphibious") and "swimmer" not in lo:
        err(cid, "aquatic/amphibious needs swimmer locomotion")
    if "flying_mount" in r and "flyer" not in lo:
        err(cid, "flying_mount requires flyer")
    if "aquatic_mount" in r and "swimmer" not in lo:
        err(cid, "aquatic_mount requires swimmer")
    if "dig" in r and d["max_hardness"] <= 0:
        err(cid, "dig role requires dig.max_hardness > 0")
    if "burrower" in lo and d["max_hardness"] <= 0:
        err(cid, "burrower locomotion requires dig.max_hardness > 0")
    if d["max_hardness"] > 0 and d["speed"] <= 0:
        err(cid, "dig speed must be > 0 when hardness > 0")
    if so["structure"] in ("pack", "herd", "colony", "swarm") and ins["sociability"] < 0.5:
        err(cid, "group-living species should have sociability >= 0.5")
    if so["structure"] == "solitary" and ins["sociability"] > 0.5:
        err(cid, "solitary species should have sociability <= 0.5")
    if so["structure"] == "solitary" and so["group_size"] != [1, 1]:
        err(cid, "solitary group_size must be [1,1]")
    if so["structure"] == "pair" and so["group_size"][0] > 2:
        err(cid, "pair group_size min must be <= 2")
    if so["structure"] in ("pack", "herd", "colony", "swarm") and so["group_size"][1] < 3:
        err(cid, "group structure needs max group_size >= 3")
    if "hunting_cooperative" in sk and sk["hunting_cooperative"] >= 0.6 and ins["sociability"] < 0.5:
        err(cid, "high hunting_cooperative needs sociability >= 0.5")
    if "defense_herd_circle" in sk and sk["defense_herd_circle"] >= 0.6 and so["structure"] in ("solitary",):
        err(cid, "defense_herd_circle high for solitary species")
    if "digging_burrowing" in sk and sk["digging_burrowing"] >= 0.6 and d["max_hardness"] <= 0:
        err(cid, "high digging affinity but cannot dig")
    if "fishing" in sk and sk["fishing"] >= 0.6 and c["diet"] not in ("piscivore", "carnivore", "omnivore"):
        err(cid, "high fishing affinity but non-fish-eating diet")
    if "scouting_aerial" in sk and sk["scouting_aerial"] >= 0.6 and not ({"flyer", "glider"} & set(lo)):
        err(cid, "high scouting_aerial needs flyer/glider")
    if c["diet"] == "herbivore" and ins["aggression"] > 0.7:
        err(cid, "herbivore aggression suspiciously high (>0.7)")
    if c["diet"] in ("carnivore",) and ins["aggression"] < 0.4:
        err(cid, "carnivore aggression suspiciously low (<0.4)")
    if se["echolocation"] >= 0.5 and se["vision"] > 0.6:
        err(cid, "strong echolocation with strong vision is incoherent for this roster")


def main(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa
        print(f"FAIL: cannot load JSON: {e}")
        return 1
    if not isinstance(data, list):
        print("FAIL: root must be a JSON array")
        return 1
    ids = Counter(c.get("id") for c in data if isinstance(c, dict))
    for i, n in ids.items():
        if n > 1:
            err(i, "duplicate id")
    names = Counter(c.get("name") for c in data if isinstance(c, dict))
    for i, n in names.items():
        if n > 1:
            err(i, "duplicate name")
    for c in data:
        if not isinstance(c, dict):
            err("?", "entry is not an object")
            continue
        check_creature(c)

    n = len(data)
    if n < 72:
        errors.append(f"[roster] need >= 72 species, have {n}")
    valid = [c for c in data if isinstance(c, dict) and set(c) == KEYS]
    layer = Counter(c["layer"] for c in valid)
    era = Counter(c["era"] for c in valid)
    diet = Counter(c["diet"] for c in valid)
    tier = Counter(c["tier"] for c in valid)
    biome = Counter(b for c in valid for b in c["habitats"] if isinstance(c["habitats"], list))
    if layer["underground"] < 12:
        errors.append(f"[roster] underground >= 12 required, have {layer['underground']}")
    if layer["aquatic"] < 8:
        errors.append(f"[roster] aquatic >= 8 required, have {layer['aquatic']}")
    if layer["aerial"] < 8:
        errors.append(f"[roster] aerial >= 8 required, have {layer['aerial']}")
    for e in ERAS:
        if era[e] < 4:
            errors.append(f"[roster] era {e} needs >= 4 species, have {era[e]}")
    for b in BIOMES:
        if biome[b] < 2:
            errors.append(f"[roster] biome {b} needs >= 2 species, have {biome[b]}")
    if n:
        hp = diet["herbivore"] / n
        cp = diet["carnivore"] / n
        if not 0.38 <= hp <= 0.52:
            errors.append(f"[roster] herbivore share {hp:.0%} outside 38-52% (target ~45%)")
        if not 0.25 <= cp <= 0.35:
            errors.append(f"[roster] carnivore share {cp:.0%} outside 25-35% (target ~30%)")
        for t in range(1, 6):
            if not 0.10 <= tier[t] / n <= 0.30:
                errors.append(f"[roster] tier {t} share {tier[t] / n:.0%} outside 10-30%")
    masses = [c["size"]["mass_kg"] for c in valid if isinstance(c["size"], dict) and num(c["size"].get("mass_kg"))]
    if masses:
        if min(masses) >= 1:
            errors.append("[roster] need at least one species < 1 kg")
        if max(masses) <= 30000:
            errors.append("[roster] need at least one species > 30,000 kg")
    for c in valid:
        for r in ("combat", "mount"):
            pass
    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for e in errors:
            print("  -", e)
        return 1
    print(f"OK: {n} species")
    print("  layers:", dict(layer))
    print("  eras:  ", {e: era[e] for e in ERAS})
    print("  diets: ", dict(diet))
    print("  tiers: ", dict(sorted(tier.items())))
    print(f"  mass range: {min(masses)} - {max(masses)} kg; biomes min coverage: {min(biome[b] for b in BIOMES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
