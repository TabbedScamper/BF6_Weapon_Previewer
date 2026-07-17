# BF6 Weapon Previewer

Browser-based 3D armory for Battlefield 6: pick any weapon, swap attachments per
slot, and preview the result — plus gadgets and throwables. Slot lists and
weapon→attachment compatibility come straight from the game's own data, so only
combinations the game actually allows are offered.

![preview](docs/preview.png)

## Features

- Full-screen 3D stage: orbit / scroll zoom / RMB freelook + WASD fly
- 66 weapons (battle pickups included), 4,600+ real weapon×attachment pairs
  across 11 slots (Scope, Secondary Sight, Barrel, Muzzle, Magazine, Ammo,
  Bottom/Top/Left/Right Rail, Ergonomic)
- In-game names for weapons, gadgets and attachments, joined from the
  Portal SDK item catalog (see `docs/COVERAGE-AUDIT.md`)
- Format research notes for modders: `docs/BF6-FORMATS.md` (EBX, textures,
  weapon assembly, the layered card-icon system) and
  `docs/EBX-ATTACHMENT-FORMAT.md`
- Weapon skins, 157 tiling camo patterns, and 226 weapon charms
- Gadgets & throwables browser
- Portal creator tools: `</> PORTAL CODE` generates verified Portal SDK
  TypeScript for the current build (give-weapon-with-attachments and
  weapon-card UI), and a live weapon card composited from the game's own
  layered card icons updates as you swap parts
- Downloadable master armory list (⤓ in the header): a single offline HTML
  file with every weapon, slot, and available attachment plus the game's own
  armory renders — includes a CSV export button (`data/armory-list.html`).
  Also available as a navigable Excel workbook — Home sheet → category →
  weapon sheets with renders and back links (`data/compatibility.xlsx`) —
  and a raw flat sheet (`data/compatibility.csv`)
- First-person-grade meshes with full-resolution PBR textures

## Run locally

The site is static; models are served from a local staging folder.

```
python site/serve.py            # http://localhost:8087
```

Set `BF6WPN_MODELS` to point at your models folder (default `A:\bf6weapons\models`).

## Tools

Everything under `tools/` rebuilds the data from a local BF6 installation dump:

| tool | purpose |
|---|---|
| `scrape_armory.py` | build `data/armory_db.json` (weapons, parts, slots, compatibility, skins, gadgets) |
| `build_manifest.py` | produce `site/data/manifest.json` for the site |
| `convert_all_weapons.py` | batch-convert every weapon part / attachment / gadget mesh to textured GLB |
| `probe_weapon.py`, `check_tex_res.py`, `verify_hres.py`, `find_mip0.py`, `tex_res_sweep.py` | one-off verification utilities |

Mesh/texture conversion reuses the
[high-poly pipeline](https://github.com/TabbedScamper/BF6_High_Poly_Godot_Plugin)
tooling.
