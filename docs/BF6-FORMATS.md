# BF6 File Format Notes (community reference)

Field-verified findings from building the BF6 Weapon Previewer entirely out of
extracted game data. Everything below was proven by parsing retail files and
validating the results visually against the game. Where something is inferred
but not fully verified, it is marked as such. Companion deep-dive for weapon
attachment records: [EBX-ATTACHMENT-FORMAT.md](EBX-ATTACHMENT-FORMAT.md).

Field names are stripped in retail EBX reflection — structures below are keyed
by their u32 name hashes as they appear when parsing.

## 1. RIFF-EBX essentials

- Pointer cells are **i32-relative in the LOW dword**; `low & 1` set means an
  import reference with `index = low >> 1`. The `EBXX` chunk is the
  authoritative array table.
- The exported instance GUID sits at `instance_offset - 16`.
- Array fields: after `u32 payloadOffset, u32 count` there is a `u32 hash`
  that MUST be preserved when writing — zeroing it crashes the game.
- Use the **multiplayer** executable's type reflection for weapon types;
  the single-player exe carries stale layouts that misread silently.

## 2. Type reflection in the executable

- `TypeInfoData`: `nameHash u32 @ -8, flags u16 @ -4, size u16 @ -2, guid[16]`.
- `FieldInfo` (stride 24): `nameHash u32 @ +0, flags u16 @ +4, offset u32 @ +8,
  typeInfo u64 @ +12`.
- Names are stripped; only hashes remain. The hash function is
  **non-standard**: it is case-insensitive and non-linear, and an exhaustive
  sweep (FNV-1/1a, DJB2, CRC32 across polynomial space, Murmur2/3, xxHash32,
  SDBM, Jenkins, plus finalizer combinations — and a GF(2)-affine test that
  rules out the whole xor-linear family) eliminates every common candidate.
  It is baked at build time; the routine does not ship in the exe.
- **Workaround that recovers names anyway:** Frostbite type GUIDs are stable
  across games, so BF6's baked reflection (GUID → nameHash, field offsets)
  can be joined against older titles' *named* type dumps (BF2042/BFV era).
  Cross-type consensus on field hashes cleans the noise: ~14k hash→name
  entries at ~99% precision (`data/fieldname_dict.json` in this repo, built
  by `tools/fieldnames.py`). Confirmed anchors: `x`=956422932,
  `y`=1123815262, `Name`=207223302, `Offset`=1341473252, `Size`=3382203005.
- The exe's `.rdata` still retains ~130k reflection name strings — they just
  aren't linked from TypeInfoData. If the hash function is ever identified,
  the whole table maps at once.

## 3. Textures

- `.Texture` resource: the mip0 chunk GUID lives at byte offset **164**
  (not 40 as in some older titles).
- Full-resolution weapon mips ship in a separate HRES superbundle
  (`BF6_HRES_SHARED_DLC\...\initialexperienceinstallpackage\weapons.toc`);
  the base dump caps at low mips for many weapon sheets.
- BCn `*_SRGB` DXGI format codes in headers should be remapped to their
  `_UNORM` twin before decoding with standard BCn decoders.

## 4. Weapon 3D assembly (why identity-assembly works)

- All bone-mounted weapon parts — including a weapon's own barrels, mags and
  slides — are authored at the **shared weapon-skeleton bind pose**
  (`_soldier\_weaponskeleton.ebx`): Wep_Muzzle/Barrel_ATT z=0.551 y=0.0675,
  Wep_Scope_ATT y=0.1046, Wep_MGZ_ATT z=0.1476.
- Weapons are sight-line aligned: optics and rails need no per-weapon delta.
- Per-weapon anchors come from the `md_` record's bone-defaults rows. Note the
  label swap: the field labelled like a rotation holds the **translation**.
  Transform-slot index = 2 + position in the bone list (index 4 = Barrel_ATT,
  validated across pistols/bullpups/snipers/LMGs).
- Barrel records' bone writes carry inch-exact muzzle offsets (+0.0254/inch).
- Attachment compatibility is encoded in **unlock filenames**:
  `u_prg_<weapon>_<slot>_<attachment>.ebx` — one file per legal combination
  (~4,680 in retail). No other compatibility table exists in the data.
- Iron sights swap to dedicated `*folded` meshes while an optic is mounted.

## 5. UI: layered weapon-card icon system

Weapon cards are composited from per-weapon atlases at
`ui\assets\images\hardware\generated\layerediconsatlases\<w>_layerediconatlas.ebx`
(the plain dump may lack these EBX; the full extraction has them).

Root fields (u32 name-hash keys): `3402576385` sprite entry array,
`1457205629` atlas page imports in page order, `3806135047` max page size.

Per sprite entry:

| name hash | meaning (verified numerically) |
|---|---|
| 207223302 | source icon path (string) |
| 2358657797 | DJB2-XOR hash (h=5381; h=h*33^c) of lowercased source path |
| 2317631205 | atlas page index |
| 3880198453 | UV rect (x=956422932, y=1123815262, maxX=849976220, maxY=2088788722) |
| 1341473252 | pixel position in page |
| 3382203005 | pixel size |
| 808112726 | composition canvas (512x256 card layers, 256x256 slot icons) |
| 4232781919 | placement offset on the canvas |

Vec2 members: x = 956422932, y = 1123815262.

- Textures are **two-channel SDFs**: R = line art (smoothstep ~217..233 gives
  the in-game white outline), G = fill silhouette. The raw texture looks like
  orange/green noise until decoded this way.
- **Placement mechanism (solved):** atlas placements alone do not align part
  families to the receiver. Each weapon ships an authored offsets asset,
  `hiao_<weapon>.ebx`, next to its gameplay EBX (root type
  `ea9d5e03-fafe-ea6e-0472-bea75c29a27f`): an array of entries keyed by
  **djb2-xor of the lowercased full icon path** (same id as the atlas
  sprite's path-hash field), each carrying a Vec2 pixel `Offset`. The final
  card position is simply `atlas placement + hiao offset` (the 512x256
  canvas is a reference frame — negative coordinates are legal). Barrel
  entries (48-byte subtype) carry a second Vec2: the muzzle-device anchor
  override used when that barrel is equipped. Mid-zoom scope entries carry
  an anchor for their flip-mounted reflex.
- Muzzle and other generic devices have real 512-canvas card layers in
  `shared_layerediconatlas.ebx`, and weapons can reuse sprites from other
  weapons' atlases — resolve sprites through a global id index across all
  atlas EBX. The wiring runs through `ui\metadata\uiweaponabilitymetadata.ebx`
  (per-weapon record → atlas pointer + hiao pointer) into the
  `weaponattachmentslayerediconsdbd` databinding, rendered by
  `componentlibrary\components\icons\cb_layeredicon.ebx`.
- Related but distinct: `pf_weaponattachmenticonlineoffsetdata.ebx` and
  `aslo_*.ebx` are the 3D inspect-mode callout lines, not the card.
- Shared per-device slot icons: `attachmentatlases\<category>_iconatlas.ebx`
  (muzzle, sight, opticaccessory, bottomrail, magazine, ...), all 256x256
  canvas `_Single_Icon` entries, zoom-to-fit (scale varies per device).
- Composed reference icons per weapon:
  `hardware\<class>\t_ui_<w>_archetype_icon.Texture` (same SDF format).

## 6. Camos, skins, charms

### Weapon UV law (differs from the environment-prop convention)

| channel | density | use |
|---|---|---|
| TexCoord0 | varies per part | cs / nmt / wo atlas |
| TexCoord1 | uniform 2.0 uv-units per meter, every weapon and attachment | camo pattern |
| TexCoord2 | uniform continuous space, base/receiver parts only | sticker/decal placement |

The per-channel uv-units/m are literally the `texCoordRatios[i]` floats in
each MeshSet section. AO lives in texture channels (wo.G, nmt.A), not a UV1
bake.

### Camo (verified recipe)

- Patterns: 157 tiling `t_wep_camo_wcr####` (1024²); unlock EBX are
  parameter-free stubs; shader tiling constant is (1.0, 1.0) universally;
  pattern alpha is a real coverage factor but rarely used.
- The per-weapon paint mask is the `_wo` sheet's **alpha channel** (UV0,
  BC7 linear; excludes rubber, grip pads, mechanical internals).
- `_wo` channels: R = edge-wear mask, G = soft AO bake, A = camo-allowed.
- Composite: `final.rgb = mix(cs.rgb, camo.rgb(UV1), wo.A(UV0) * camo.A(UV1))`
  with smoothness staying `cs.A`.
- Universal weapon shader slots: 0x54bbcd30 cs, 0xec35a757 nmt,
  0xb1a29a3c wo, 0x01c7da1a camo color, 0x01c7d9a9 camo normal,
  0x51008a66 camo tiling.

### Stickers

- 200 die-cut decal sheets `t_wepdec_*_cs` (256², BC7 sRGB); unlock EBX are
  stubs. Placement = a per-weapon UV-rect transform applied to **TexCoord2**
  at runtime (three decal sampler slots exist on every weapon material:
  0x3bfd0654 / 0x21cf0844 / 0x3bfd9a37). The rect values are not present in
  the parsed material defaults. Magazines have no UV2 (no stickers — matches
  the game).

### Scope lenses and reticles

Per-optic records inside the optic's dpf shader-block depot: reticle texture
slot 0xcc64d7f5 (34-texture library `common\hardware\common\reticles\t_ret_*`,
art in the G channel, colored by the coating), lens coating color sheet
0x16ebf114 (`t_mc_lens_red`, `t_mc_lens_teal`, ...), lens dirt 0x49866e89,
fake interior reflection 0x350c4924, glass rim mask 0x5100bf69. The
Anti-Glare Coating attachment is a gameplay-only stub (no material change).
- Skins: standard/rare/epic tiers are baseColor/normal retextures sharing the
  base UVs; legendary (and some epic) skins ship **replacement meshes** with
  their own UVs under `art\skins\<id>\` — retexturing the standard mesh with
  a legendary sheet scrambles.
- Charms: 227 models under `_charms\{che,chr,chl}####`; anchor = world pose of
  skeleton bone 12 (`Wep_Charm`) through the md/bind parent chain.

## 7. Portal SDK creator quick facts (verified in retail SDK 1.3.3.0)

- Grant a weapon with attachments:
  `CreateNewWeaponPackage()` → `AddAttachmentToWeaponPackage(att, pkg)` per
  attachment ("replaces same type") → `AddEquipment(player, weapon, pkg,
  slot?)` → `ForceSwitchInventory`. Build the package **before** AddEquipment;
  packages cannot be applied to an already-held weapon (remove → re-add).
  Let the equip settle (~0.3 s) before `SetInventoryMagazineAmmo`.
- Weapon card UI: there is no card widget; compose `AddUIContainer` +
  `AddUIText` + `AddUIWeaponImage(name, pos, size, anchor, weapon, parent,
  pkg?, visibility?)` — the same package renders the attachments on the card,
  positioned automatically by the game. Widget names must be unique; the
  weapon/package on a created image is immutable (delete + recreate to
  change). Melee gadget images currently render nothing (acknowledged bug).
