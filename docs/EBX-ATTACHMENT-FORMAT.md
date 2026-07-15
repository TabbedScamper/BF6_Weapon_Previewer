# BF6 Weapon-Customization EBX — Reverse-Engineering Notes

Decoded from the retail dump `A:\bf6dump\bundles` (RIFF EBX, EbxVersion 6) with
the reflection tables of the **MP** `bf6.exe`. Producer script:
`tools/decode_attachments.py` → `data/attachment_bindings.json`.
Reader stack: `tools/ebx.py` (RIFF/EFIX, copied from bf6-highpoly-pipeline),
`tools/ebx_deser2.py` (corrected deserializer, this project),
`tools/typesdk.py` (exe reflection reader, EXE path fixed to the MP binary).
`tools/ebx_explore.py` dumps any EBX with type/field labels where the BFV/2042
SDK dumps supply names.

---

## 1. Critical global findings (apply to ALL BF6 EBX work)

### 1.1 SP exe vs MP exe reflection — THE bug
`typesdk.py` in bf6-highpoly-pipeline points at `...\Battlefield 6\SP\bf6.exe`.
The SP binary carries **different (stale) layouts** for the weapon-customization
types: the md part-record type `92422e7d…` is 456 bytes / 22 fields in SP
reflection but **200 bytes / 25 fields** in the MP exe — and the MP layout is
what the dumped data actually uses. Decoding with the SP exe silently misreads
every field (NaN transforms, bogus import indices). Props/terrain types happen
to match between the two exes, which is why the highpoly pipeline never hit
this. **Always use `...\Battlefield 6\bf6.exe`** (typesdk.py here is patched).

### 1.2 Pointer cells are i32-relative in the LOW dword
On-disk PointerRef cells are 8 bytes, upper 4 bytes always 0 (reserved for the
runtime relocation):

    low == 0        -> null
    low & 1         -> import ref, index = low >> 1 into EFIX imports
    else            -> SIGNED i32 offset from the cell to the target instance

The original `ebx_deser.py` read them as i64 — backward (negative) refs then
become huge positives. Import-ref cells appear in EFIX `import_offsets`;
internal refs in `pointer_offsets`; **array-field cells are relocated too and
appear in `pointer_offsets`** even though they are not PointerRefs.

### 1.3 EBXX chunk = authoritative array table
`EBXX` layout (verified byte-exact):

    u32 arrayCount, u32 boxedCount
    arrayCount x 16-byte entries:
      u32 payloadOffset   (of the FIRST ELEMENT; count is also at offset-4)
      u32 count
      u32 hash            (must be preserved on write; game crashes on 0)
      u16 typeFlags       (te = (flags >> 5) & 0x1f)
      u16 typeIndex       (into EFIX type_guids; 0xFFFF = primitive element)

Array **element types must come from EBXX**, not from the exe's ArrayInfoData
heuristics (those picked wrong element types, e.g. `ccd95fe1` instead of
`8b00f74d`). Struct-element stride = align_up(size, align) of the EBXX type.

### 1.4 Exported instance GUIDs
Each exported instance's 16-byte GUID sits at `instance_offset - 16` in the
payload. This is how import `(partitionGuid, instanceGuid)` pairs resolve to a
specific instance of the target file (e.g. which gameplay bone).

### 1.5 Cross-game type GUID matching gives NAMES
EBX type GUIDs are content-derived and survive across Frostbite titles. Types
unchanged since BFV/BF2042 can be named by looking up the EFIX type guid in
`frosty-bf6-mining\type_dumps\BFVSDK.types.json` / `BF2042gen.types.json`
(≈25k guids) — that is how `UnlockAsset`, `SoldierWeaponCustomizationAsset`,
`SoldierWeaponBlueprint`, `SoldierWeaponData`, `WriteVector3GameState` etc.
were identified. BF6-only types (all below) keep hash-only fields; their
semantics were established empirically and are keyed by field name-hash in
`decode_attachments.py` (`F` dict).

---

## 2. The weapon-customization file family (per weapon `<w>`)

    cust_<w>.ebx        SoldierWeaponCustomizationAsset {md ref, wb ref} (stub)
    <w>_wb.ebx          SoldierWeaponBlueprint + SoldierWeaponData
                        (gameplay config, per-weapon modifier table)
    md_<w>.ebx          MODEL DEFINITION - the visual-customization motherlode
                        (sometimes at art\md_<w>.ebx; resolve via cust import!)
    equipment_<w>.ebx   unlock registry + PACKAGE GRANTS (factory config)
    gs_<w>.ebx, dicefeature_<w>.ebx, <w>_ability.ebx, ...
    attachment_<w>_<slot>_<name>.ebx     one per armory item
    u_prg_<w>_<slot>_<name>.ebx          progression unlock (bare UnlockAsset)
    u_<w>_pkg_factory.ebx                factory package unlock (bare)

Shared attachment art: `_attachments\<class>\<name>\` → `u_att_*.ebx`
(art unlock), `wpm_*.ebx` (stat module), `art\*.MeshSet` (+skins).
Weapon-own part art: `<w>\art\*.MeshSet` (barrels, mags, panels, ironsights).
`shotgun/ksg` ships only `attachment_`/`u_prg_` stubs — no cust/md/wb exist.

## 3. attachment_<w>_<slot>_<name>.ebx (type `a6a8168e…`, 1 instance)

| fieldHash  | meaning                                   |
|------------|-------------------------------------------|
| 4269271465 | -> import `attachmentcategory_<cat>.ebx`  |
| 360349044  | -> import `u_prg_<w>_<slot>_<name>.ebx`   |
| 1860724133 | sort index in slot                        |
| 4137720976 | array of {unlock ref, sort} (same data)   |
| 1188981180 | inline struct {3249354714: category id}   |
| 3731841971 | asset id (u32)                            |
| 27836196   | array — empty on every one of the 4,680   |
| 207223302  | asset name                                |

## 4. equipment_<w>.ebx — root type `a878a81c…`

Key root field **2219803012** = grants table, elements `6732a95b…`:

| fieldHash  | meaning                                        |
|------------|-------------------------------------------------|
| 4167959603 | grantor unlock (u_prg_* or u_<w>_pkg_factory)   |
| 3532520192 | granted item -> import attachment_*.ebx         |

* `u_<w>_pkg_factory` grants = **FACTORY/STOCK CONFIG** (e.g. M4A1: scp/xps3,
  brl/shortbarrel, mzl/m4qdflashhider, mag/regular, amo/fmj; other slots empty).
* every `u_prg_X` grants its own `attachment_X` (confirms the chain).
Other root fields: 1961309300 = 799-item unlockable registry ({import, tag}),
1736464461 = package list (8 for m4a1: factory + skin packages `u_pkg_*`).

## 5. md_<w>.ebx — the visual customization data

Instance 0 = exported root (type `d28e8aeb…`):

| fieldHash  | meaning                                                    |
|------------|-------------------------------------------------------------|
| 947075724  | array {74564025: pos vec4, 1039914489: rot quat vec4, 2982296999: transform-slot idx} — per-weapon gameplay-transform DEFAULTS table (62 entries on m4a1). idx 2..13 correspond to the gameplay bones (idx 4 = Barrel_ATT sits e.g. (0, 0.0602, 0.4332) on m4a1); higher idx = additional gameplay points (ADS poses, canted-rotation quats at idx 19/20, scale rows w=0.001 at 44-46). |
| 4265094687 | array -> the ~21 SLOT-GROUP instances                       |
| 3559625904 | -> import `common\characters\_soldier\_weaponskeleton.ebx`  |
| 990019666  | 66x {2503654506, 4289392427} u32 pairs (uninterpreted)      |

### 5.1 Slot group (type `b2834625…`, ~21 per weapon)

| fieldHash  | meaning                                              |
|------------|-------------------------------------------------------|
| 1693403371 | -> import slot-type EBX (`muzzle.ebx`, `sight.ebx`, `barrel.ebx`, `muzzledevice.ebx`, `bottomrailattachment.ebx`, `charm.ebx`, `camo_spo.ebx`, ...) under common\gameplay\weapons\template\definitionslots_weapons\ |
| 3280051868 | -> member part records                                |
| 814846733  | {4290404592: [u32 art-unlock ids]} parallel id list   |
| 3778210562 | -> socket placement instance (7a1f7eff) for the group |

m4a1 groups: charm(227 members), sight(34), bottomrail(30), magazine(17),
muzzle(13, =flash hiders on MuzzleAdaptor_ATT), muzzledevice(5, =suppressors
on Muzzle_ATT), barrel(8), ironsight(11), secondarysight(8), toprail(8),
rightrail(6), ergonomic(5), base(5), railcover_left/right, ammo(1: a wpm stat
module only -> **ammo has no visual**), offsetreflextrigger(1), spo skin groups.

### 5.2 Part-variation record (type `92422e7d…`, size 200, ~350-400/weapon)

| off | fieldHash  | te     | meaning                                          |
|-----|------------|--------|--------------------------------------------------|
| 24  | 3281382875 | CStr   | dpf bundle name 3p (`dpf_<art>_<tok>_bundle_3p`) |
| 40  | 546520075  | Array  | ATTACH BINDINGS (elem `ccd95fe1…`, see 5.3)      |
| 48  | 1571580288 | Array  | socket-placement refs (rarely used)              |
| 56  | 1887819232 | Ptr*   | -> import **u_att art unlock** (typeVA==0 in     |
|     |            |        | reflection; decode as pointer via EFIX fixups)   |
| 80  | 2182525970 | Array  | part AABBs {2397252117 min, 3794091819 max} vec3 |
| 96  | 3913110952 | CStr   | (usually empty)                                  |
| 104 | 1296849196 | Array  | BONE WRITES {470635321: [{pos,rot,idx}]} — the   |
|     |            |        | transform-slot overrides applied when equipped   |
| 120 | 232919999  | Array  | condition list A (s16/u32 pairs; gamestate keyed)|
| 72  | 2323969484 | Array  | condition list B                                 |
| 144 | 1526166064 | CStr   | dpf bundle name 1p                               |
| 160 | 252274761  | Array  | elem `8b00f74d…` = {2449067340:[], 2981400700:[]}|
| 168 | 4176908330 | CStr   | (usually empty)                                  |
| 176.. | 5 u32s + bool at 199 (ids/flags)                                   |

### 5.3 Attach binding (struct `ccd95fe1…`, 96 B, usually 2-3 = 1p/3p/zoom)

| off | fieldHash  | meaning                                             |
|-----|------------|------------------------------------------------------|
| 0   | 3824396538 | LinearTransform (right/up/front/trans vec3s) —      |
|     |            | LOCAL MOUNT OFFSET relative to the gameplay bone    |
| 64  | 74453267   | ptr (null)                                          |
| 72  | 3883213010 | ptr (null)                                          |
| 80  | 3287516531 | -> import `_weaponskeleton.ebx` (skeleton instance) |
| 88  | 4117705232 | -> import `weapongameplaybones.ebx` **bone**        |

Example: canted red dot binds `SecondarySight_ATT` with trans
(-0.0423, 0.1098, 0.0389); NT4 suppressor binds `Muzzle_ATT` at identity.

### 5.4 Socket placement (type `7a1f7eff…`, ~93/weapon)

| fieldHash  | meaning                                        |
|------------|-------------------------------------------------|
| 1931345991 | -> import weapongameplaybones instance (bone)   |
| 1341473252 | LinearTransform — socket transform for the group|

### 5.5 Gameplay bones (common\gameplay\bone\weapongameplaybones.ebx)
14 exported instances: name + i32 hash id:
`WeaponRoot, WeaponAlign, Barrel_ATT, Muzzle_ATT, MuzzleAdaptor_ATT,
Sight_ATT, SecondarySight_ATT, Magnifier_ATT, Laser_ATT, Flashlight_ATT,
Rangefinder_ATT, UnderBarrel_ATT, Magazine01` (+ asset root).
Import instance-guids resolve against the guid at `instance_offset-16`.

### 5.6 How a mount position composes (model)
world = **bone default transform** (md root table 947075724, plus any
equipped-part **bone_writes** overrides for that transform slot)
∘ **group socket placement** (5.4) ∘ **record binding transform** (5.3).
Barrel dependence: barrel meshes carry/write the muzzle & underbarrel
transform slots (their `bone_writes` reference those slot indices), and the
barrel's own AABB (5.2) tells where its muzzle end is. All four data layers
are emitted per weapon in attachment_bindings.json; final composition should
be validated visually in the previewer (enum idx>13 semantics not fully
pinned).

## 6. Mesh binding chain (answer to "which mesh")

Authoritative chain per record:
1. record → u_att import → its `_attachments\<class>\<name>\` folder →
   `art\ob_wepatt_*_mesh.MeshSet` inventory (shared attachments), or
2. record → dpf bundle name (`dpf_<ART_TOKEN>_<hash>_bundle_{1p,3p}`) —
   the game's own string naming the runtime blueprint bundle. For weapon-own
   parts the token embeds weapon+part (`dpf_m4a1_barrelshort_...`) → matches
   `<w>\art\ob_wep_<class>_<w>_<part>_{1p,3p}_mesh`.
   The dpf bundle EBX themselves ("BlueprintBundle") are NOT in the dump for
   weapons (only their `_win32_shaderstate` sidecars) — the bundle-content
   walk is therefore not possible offline; the token+folder resolution above
   is the game's own data, not fuzzing.

## 7. u_prg ↔ u_att join (the one non-GUID hop)

The armory equips `u_prg_<w>_<slot>_<name>`; the md records key on
`u_att_<artname>`. No file in the weapon family maps the two by GUID/id (the
u_att id appears only in md's own id lists; equipment grants map u_prg →
attachment_* only; wb's modifier table keys on u_wpm ids). At runtime the
selection goes through the gamestate system (records carry condition lists;
modifier modules write gamestates). Offline we join by normalized name token
constrained to the slot's own md groups (+ a small verified alias table:
uglmount→m320base, kacverticalgrip→kabroomstick, zenitcork1→rk1,
trijiconrco→trijiconm150, cantedreflex→cantedreddot, eflxmini→eotechelfx,
g43magnifier→eotechg43, mag regular→magazine, mag fast→magmapull, ...).
Every pairing carries `join.method/score/ambiguous`; unpaired items carry
`record_candidates` (the slot's full member list) for manual/visual pick.
Coverage: **80.9%** token-paired + 6.0% classified no-visual (ammo) = 86.9%
of the 4,680; 89.5% of paired records resolve to concrete MeshSet names.
Magazines are the main unresolved family (design names `extended1/compact2`
vs art names `pmag40rnd/pufgun45` are not derivable offline).

## 8. Cross-slot exclusions — what the data actually says

* `cust_<w>.ebx` is a 2-pointer stub (md + wb). No exclusion data.
* `_logic\*blockingchannels*.ebx` are **soldier ability channel blockers**
  (which ability channels a state blocks — e.g. `primaryability_
  blockingchannels` lists channel refs into `soldieronlypublicchannels.ebx`).
  They gate ACTIONS (deploying bipod, firing UGL), not armory combinations.
* `attachment_*.ebx` field 27836196 (a plausible exclusion list) is empty on
  all 4,680 assets.
* Cross-slot exclusivity is therefore STRUCTURAL: each md slot group is one
  mount point; UGL mounts, bipods and grips are all members of the same
  `bottomrailattachment` group (mutually exclusive by design), canted/offset
  optics all live in `secondarysight`/`offsetreflextrigger`, lasers/lights in
  the top/right/left rail groups. The 11 `sc_*.ebx` slot categories carry only
  {id, 4226398153: 1|3|6, 598884486: 1..4} (UI grouping values), no exclusion
  rules. 415 records carry gamestate condition lists (emitted raw as
  cond_a/cond_b) — these switch VISUAL variants, not armory legality.

## 9. Open items

* u_prg↔u_att exact link: runtime goes through gamestates; the remaining
  ~13% (mostly mags + a few renamed optics) need either the frontend armory
  metadata (not found in this dump) or one-time visual confirmation.
* md root field 990019666 (66 u32 pairs) and record u32s at 176-196
  uninterpreted.
* Transform-slot enum for idx > 13 (ADS/pose entries) unmapped — emitted raw.
* SP-exe reflection also mislabels several small structs; anything decoded
  before the MP-exe switch should be re-checked if reused.
