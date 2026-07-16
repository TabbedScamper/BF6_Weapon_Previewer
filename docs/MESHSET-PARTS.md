# BF6 MeshSet — part table & data-driven mechanical part split

How to split a BF6 weapon mesh into its game-defined mechanical parts (bolt,
charging handle, slide, mag release, trigger, fire selector...) **by data**,
no geometry guessing. Implemented in `tools/meshset_parts.py`.

Validated byte-for-byte on:
- `ob_wep_carbine_m4a1_base_1p_mesh.MeshSet` (M4 receiver → 10 parts)
- `ob_wep_secondary_g22_slide135mm_1p_mesh.MeshSet` (pistol slide → 1 part)
- `ob_wepatt_reflex_compm5b_base_1p_mesh.MeshSet` (reflex sight → 1 part)
- `com_carsedan_01_mesh.MeshSet` (Composite destructible prop → 27 parts)

## VERDICT (the short version)

**Weapon 1p meshes are SKINNED, not Composite** — 1,697 of 1,718
`*_1p_mesh.MeshSet` under `common\hardware\weapons\` have `meshType=1`
(21 are Rigid, none Composite). The Composite "PartCount × AABB +
LinearTransform + section→part bitmap" mechanism from the Frosty docs is the
**destructible-prop/vehicle** path, not the weapon path.

For weapons the movable pieces are **BONES** of the shared 66-bone weapon
skeleton (`common\characters\_soldier\_weaponskeleton.ebx`): `Wep_Bolt1`,
`Wep_Bolt2`, `Wep_BoltCatch`, `Wep_Trigger`, `Wep_MagRelease`,
`Wep_SelectFireMode`, `Wep_Extra1..4`, `Wep_Charm`, `Wep_MGZ_*`, ... Every
vertex carries a `BoneIndices` stream (usage 2, UShort4) in the geometry
chunk; mechanical parts are single-weighted, so the dominant bone IS the
part id. Triangles are assigned per-vertex — fully data-driven.

Bonus: the MeshSet header carries the game's own **sparse per-bone part
table** (`boneIndices[] + AxisAlignedBox[]`) listing the bones the engine
treats as parts, with their exact boxes. m4a1 receiver: bone 3 `Wep_Align`
(whole body) + bone 10 `Wep_Bolt2` (box min(-0.004, 0.079, -0.214)
max(0.020, 0.103, -0.029) — the charging-handle-sized region at the top/rear
of the receiver). Histogram across all 1p weapon meshes: 1372×1 part,
276×2, 45×3, 4×4. The per-vertex channel is finer (m4 receiver: 10 bones
with geometry) — use the channel for splitting, the header table for
"which parts does the game itself animate/cull".

## File framing

Dumped `.MeshSet` files (toc_bf6 dumper) start with a **16-byte resMeta
prefix**; all offsets below are payload-relative (`payload = file[16:]`).
The header stub is self-contained (typically 2048 bytes); geometry lives in
a chunk file `chunks\<chunkId bytes hex UPPERCASE>.chunk`.

BF6 stores Vec3s 16-byte aligned (4 floats, w unused):
`AxisAlignedBox` = **32 bytes** (min.xyzw, max.xyzw),
`LinearTransform` = **64 bytes** (right/up/forward/trans Vec4s).
This is the key delta vs the packed-24-byte reading — get it wrong and every
field after the bbox lands 8 bytes off.

## MeshSet header (payload offsets)

| offset | type | field |
|---|---|---|
| 0x00 | float4×2 | boundingBox (min.xyzw, max.xyzw) |
| 0x20 | u64[6] | lodOffsets (payload-relative; 0 = no LOD) |
| 0x50 | u64 | unknown (0) |
| 0x58 | u64 | fullnameOffset → cstring `common/hardware/...` |
| 0x60 | u64 | nameOffset → cstring (basename) |
| 0x68 | u32 | nameHash (FNV1 of lowercased fullname) |
| 0x6C | u8 | **meshType** 0=Rigid 1=Skinned 2=Composite |
| 0x6D | u8 | unknown |
| 0x6E | u16[11] | lodFadeDistanceFactors |
| 0x84 | u32[4] | unknown |
| 0x94 | u32 | MeshSetLayoutFlags |
| 0x98 | u8,u8,i16 | shaderDrawOrder, userSlot, subOrder |
| 0x9C | u16 | lodCount |
| 0x9E | u16 | sectionCount (total across LODs) |
| 0xA0 | u16[6] | unknown |
| 0xAC | — | bone/part block, meshType-dependent (below) |
| pad16 | | first LOD begins at lodOffsets[0] |

### Bone/part block @0xAC

**Skinned (1):**
```
0xAC u16 boneCount            // skeleton size (weapons: 66)
0xAE u16 bonePartCount        // # entries in the sparse part table (1..4)
0xB0 u64 -> u16 boneIndices[bonePartCount]     // skeleton bone ids
0xB8 u64 -> AxisAlignedBox[bonePartCount]      // 32B each, per-bone boxes
```
**Composite (2):** counts swapped, pointers become part transforms/boxes:
```
0xAC u16 bonePartCount        // # parts (carsedan_01: 27)
0xAE u16 boneCount
0xB0 u64 -> LinearTransform[bonePartCount]     // 64B each; **0 in all 228
                                               // composite retail meshes
                                               // scanned — never authored**
0xB8 u64 -> AxisAlignedBox[bonePartCount]      // 32B each, per-part boxes
```
**Rigid (0):** block absent.

## MeshSetLod (at lodOffsets[i], offsets LOD-relative)

| offset | type | field |
|---|---|---|
| +0 | u32 | meshType (repeats header) |
| +4 | u32 | maxInstances |
| +8 | u32 | sectionCount (this LOD) |
| +12 | u64 | sectionOffset → section array (368 B/section) |
| +20 | (i32,u64)×5 | subset categories: count + ptr to u8 section indices (cat 0=opaque render ... 3/4=shadow) |
| +80 | u32 | MeshLayoutFlags |
| +84 | u32 | indexBufferFormat (RenderFormat: 33=R16_UINT, 46=R32_UINT) |
| +88 | u32 | indexBufferSize (bytes) |
| +92 | u32 | vertexBufferSize (bytes) |
| +96 | 20 B | unknown (zeros on every mesh checked) |
| +116 | 16 B | **chunkId** — chunk file = `chunks\<hex upper>.chunk` |
| +132 | i32 | inlineDataOffset (−1 = chunk-backed) |
| +136 | i32 | −1 |
| +140 | u64 | → cstring shaderDebugName (`Mesh:common/...`) |
| +148 | u64 | → cstring name (`common/..._lod0`) |
| +156 | u64 | → cstring shortName |
| +164 | u32 | nameHash |
| +168 | u64 | unknown (0) |
| +176 | — | meshType-dependent (below), then pad16 |

**Skinned:** `+176 u32 bonePartCount; +180 u64 → u32 boneArray[bonePartCount]`
— the LOD's bone palette (skeleton bone ids; weapons: 66 entries = 0..65).
**Composite:** `+176 u64 → per-section part bitmaps`, **24 bytes (192 bits)
per section** in section order; bit *p* set = section contains geometry of
part *p*. **Rigid:** nothing.

## MeshSetSection (368 bytes each, at sectionOffset + 368·i)

| offset | type | field |
|---|---|---|
| +0 | u64 | runtime ptr (0) |
| +8 | u64 | → cstring materialName (`M_Receiver`, `M_..._Shadow`) |
| +16 | u64 | → boneList |
| +24 | u16 | boneCount |
| +26 | u8 | unknown (0x30 observed) |
| +27 | u8 | element count hint (mirrors decl0.elementCount) |
| +28 | u16 | materialId |
| +30 | u8 | vertexStride (= Σ stream strides) |
| +31 | u8 | primitiveType (3 = TriangleList) |
| +32 | u32 | primitiveCount (triangles) |
| +36 | u32 | startIndex (in index units, shared LOD index buffer) |
| +40 | u32 | **vertexOffset — BYTE offset into the LOD vertex buffer** |
| +44 | u32 | vertexCount |
| +48 | 28 B | unknown (zeros) |
| +76 | f32[6] | texCoordRatios |
| +100 | 100 B | geometry declaration 0 (see below) |
| +200 | 100 B | geometry declaration 1 (alt/depth-only layout) |
| +300 | 36 B | hashes + pad |
| +336 | 32 B | section AxisAlignedBox |

**GeometryDeclarationDesc (100 bytes):** 16 × element
`{u8 usage, u8 format, u8 offset, u8 streamIndex}` (unused = 00 00 FF 00),
then 16 × stream `{u8 stride, u8 classification}`, then
`u8 elementCount, u8 streamCount, u16 pad`.
Usages: 1=Pos 2=BoneIndices 4=BoneWeights 6=Normal 9=BinormalSign
30=Color0 33..40=TexCoord0..7 51=SubMaterialIndex.
Formats: 8=Half4 6=Half2 23=UShort4 22=UShort2 13=UByte4N 12=UByte4.
Weapon render sections put **each element in its own stream**
(Pos Half4 s0, BinormalSign Half4 s1, BoneIndices **UShort4** s2,
BoneWeights UByte4N s3, ...); shadow sections use a cut-down decl.

## Geometry chunk layout

```
chunk = [vertex buffer  vertexBufferSize bytes]
        [index buffer   indexBufferSize bytes]  (+ ≤16 B tail pad)
```
- Index buffer: u16 unless `indexBufferFormat == 46` (then u32). Section i's
  triangles are `indices[startIndex : startIndex + 3·primitiveCount]`,
  values indexing the section's own 0..vertexCount-1 range.
- Vertex buffer: per-section block at `vertexOffset`, inside which the
  declared streams are laid out **sequentially** (not interleaved):
  stream j starts at `vertexOffset + vertexCount·Σ(stride[k<j])` and holds
  `vertexCount · stride[j]` bytes.
  Verified exactly: m4a1 s0 = 28100·56 B, s1 starts at byte 1,573,600, and
  s1 end == vertexBufferSize; index bytes 163,236·2 == indexBufferSize.

## Part assignment recipe

**Skinned (weapons):**
1. Read section decl → find usage 2 (BoneIndices, UShort4) and usage 4
   (BoneWeights, UByte4N) streams; decode from the chunk.
2. Per vertex: dominant index = `boneIndices[argmax(weights)]`
   (mechanical parts are single-weighted; weights only blend on straps etc.)
3. Map through `section.boneList` → **skeleton bone id** (weapon meshes ship
   identity lists 0..65, but non-identity lists exist — always map).
4. Bone id → name via `_weaponskeleton.ebx` bone-name array
   (field nameHash 94280276). That name IS the part
   (`Wep_Bolt2` = charging handle/bolt carrier group, etc.).
5. Triangle part = its corners' part (majority vote for safety).

**Composite (props/vehicles):** identical decode; the BoneIndices channel
carries the **part index** (via section.boneList), matching the header part
boxes and the LOD per-section bitmaps. Destruction state per part comes from
the sibling prop `.ebx` (struct array nameHash 1536505244:
`{u32 stateIndex, u32 pieceIndex}` per part — see
`bf6-highpoly-pipeline/tools/member_mesh.py`).

**Rigid:** no bone data — one implicit part.

## Validation results

- **m4a1 receiver**: 10 parts from the vertex channel — Wep_Align (body,
  46,294 tris), Wep_Bolt1 (top, z 0.14..0.25), **Wep_Bolt2 (top/rear,
  y 0.079..0.103, z −0.214..−0.029 — computed box == header stored box to
  the float)**, Wep_BoltCatch, Wep_MagRelease, Wep_SelectFireMode,
  Wep_Trigger, Wep_Extra1..3 (small internals).
- **g22 slide135mm**: everything bound to Wep_Bolt1 — the slide is the
  reciprocating part; box == mesh bbox == header part box.
- **compm5b reflex**: all on Wep_Scope_ATT (attachment mount bone).
- **carsedan_01**: 27 parts; per-vertex split matches the per-section
  bitmaps and stored boxes (body / door / hood / trunk / glass with
  intact+damaged twins, 8 wheel parts).

## Tool

```
python tools/meshset_parts.py <path.MeshSet> --summary
python tools/meshset_parts.py <path.MeshSet> -o parts.json --assign assign.json
       [--skeleton <ebx>] [--no-chunk]
```
`parts.json`: header + part table (+names) + per-LOD sections/decls +
per-part vertex/tri counts and computed boxes.
`assign.json`: per LOD/section `vertexParts[]` and `triParts[]` — the
part id of every vertex and triangle, ready to split any export.
