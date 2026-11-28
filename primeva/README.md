# Primeva

Survival e taming originale con creature ispirate ai dinosauri. Il mondo è fatto di voxel SDF da 12,5 cm, scavabile ovunque, con un continente della superficie dell'Italia.

Inizia da qui: **[docs/00_ARCHITETTURA.md](docs/00_ARCHITETTURA.md)**.

## Build e test

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/primeva_tests
```

## Strumenti

```bash
# 1) Bake del continente (~36 s a 4096², produce un asset da ~400 MB)
./build/primeva_cli bake --res 4096 --out out/macro.pvm
./build/primeva_cli stats --macro out/macro.pvm
./build/primeva_cli map   --macro out/macro.pvm --layer relief|biome|era|precip|temp --out out/map.png

# 2) Cerca siti interessanti (finestre di 4×4 km ordinate per varietà)
./build/primeva_cli find --macro out/macro.pvm --top 10

# 3) Sezione geologica verticale (strati, grotte, minerali, acqua)
./build/primeva_cli section --macro out/macro.pvm --x 712320 --z 743040 --width 160 --ymin 1890 --ymax 2015 --mpp 0.125 --out out/s.png

# 4) Export 3D (GLB) con demo di scavo, poi render con Blender Cycles
./build/primeva_cli export --macro out/macro.pvm --x 712320 --z 743040 --size 96 --dig --out out/area.glb
blender -b --factory-startup -P tools/blender/render_glb.py -- out/area.glb out/area.png --samples 32

# 5) Benchmark
./build/primeva_cli bench --macro out/macro.pvm
```

## Struttura

| Percorso | Contenuto |
|---|---|
| `core/` | Libreria `primeva_core` (C++20, nessuna dipendenza esterna) |
| `tools/` | `primeva_cli`, script Blender, validatore del roster |
| `tests/` | Suite di test |
| `data/` | Creature (90 specie) e biomi in JSON |
| `docs/` | Architettura, ricerca, design |
