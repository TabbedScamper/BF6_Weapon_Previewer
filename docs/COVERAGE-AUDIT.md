# Coverage audit vs Portal SDK block definitions

Cross-check of everything the previewer renders against the Portal SDK item
catalog (block-definition enums: `Weapons`, `Gadgets`, `WeaponAttachments`).
Generated joins: `data/portal_names.json` · full join table + per-bucket
leftovers: `data/name_report.txt` · manual pairs: `data/name_overrides.json`
(edit + rerun `tools/portal_names.py` then `tools/build_manifest.py`).

## Weapons — 66 rendered, 58 carry in-game names

Every weapon class joins 1:1 with its catalog bucket (fictionalized renames
resolved via the overrides table: VHS-2→VCR-2, Škorpion→VZ 61, MRAD→PSR,
Minimi→L110, Ultimax 100→KTS100 MK8, G36→B36A4, ...). Battle pickups
(minigun→MP RMG, railgun→RORSCH MK 2 SMRW) are now full weapon-pipeline
citizens (md bone rows, part splits, texture pass).

**In catalog but NOT in the dump** (season content newer than the current
extraction — needs a re-extract of the updated game):

- AssaultRifle_NVO_228E
- SMG_SL9
- Melee_Hunting_Knife
- Melee_Serrated_Blade

**In dump but not in catalog** (cut/unreleased; kept under internal names):
ace32, m16a3, l115a3, rpk74m, ksg (no art), apdw, vector, machete (no art),
dinomachete, gekoknife.

## Attachments

- **Scopes**: internal optics are real-world names, catalog names are
  fictional; 24 joined so far (A-P2 1.75X, CCO 2.00X, PAS 35 3.00X, ROX,
  RO-S/RO-M, Mini Flex, Baker 3.00X, Osa 7, ...). The rest render fine and
  keep prettified internal names until joined — add pairs to
  `name_overrides.json` as they're identified in game.
- **Barrels / Magazines**: the game names these per weapon by length/capacity
  ("14.5 Factory", "30rnd Fast Mag"); internal tokens are generic
  (shortbarrel, extended1). These get deterministic generic labels
  (Short Barrel, Extended Magazine I) — a data bridge would need per-weapon
  stat records (not yet mined).
- **Muzzle/rails/lasers**: real product names in the dump vs 10-12 fictional
  role names in the catalog; kept as prettified real names
  (M4 QD Flash Hider, SV98 Thread Protector, ...).
- **Ammo / Ergonomic / secondary sights**: joined near-fully.

## Gadgets — 76 rendered, 42 named

Joined per dump category (throwables→Throwable, launchers→Launcher, ...).
Catalog-only leftovers are mostly call-ins and class items with no
first-person model in the dump (Air Strike, Ammo Drop, UAV Overwatch, ...)
plus intercept systems. Dump-only extras are campaign/Portal props
(boltcutters, spray can, data drives) — kept, internal names.

## Cosmetics

- **Charms**: 226 extracted and selectable (Charm slot on every weapon);
  anchor = `Wep_Charm` bone down the md/bind parent chain.
- **Camos**: 157 tiling patterns located (`_textures/camo`), shader-param
  decode in progress — separate system from the baked legendary skins the
  previewer already shows.
- **Stickers**: ~200 decal textures + 387 placement EBX located
  (`_textures/decals`, primary/secondary slots); needs a projection decode —
  future work.
