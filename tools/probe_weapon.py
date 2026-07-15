"""Probe: can the existing highpoly pipeline convert weapon/attachment MeshSets?

Answers three make-or-break questions before batch conversion:
 1. Do weapon 1p MeshSets convert through Assembler.parts() (textures + UVs)?
 2. What texture resolution gets picked (want max available)?
 3. Do parts assemble at identity in weapon space (base vs barrel vs mag AABBs),
    and do SHARED attachments (scope/suppressor) come in weapon-space or local space?

Outputs GLBs to A:\bf6weapons\probe\ and prints AABB + material image sizes.
"""
import os
import sys

PIPE = r"C:\Users\mwalt\Dropbox\Personal-Files\Portal\bf6-highpoly-pipeline\tools"
sys.path.insert(0, PIPE)
import trimesh
from assemble_portal import Assembler

OUT = r"A:\bf6weapons\probe"

# NOTE: meshset_index() keys strip the trailing "_mesh"
MESHES = [
    "ob_wep_carbine_m4a1_base_1p",
    "ob_wep_carbine_m4a1_barrel12inch_1p",
    "ob_wep_carbine_m4a1_magazine_1p",
    "ob_wep_carbine_m4a1_ironsights_1p",
    "ob_wepatt_reflex_compm5b_base_1p",
    "ob_wepatt_suppressor_nt4_base_1p",
]


def main():
    os.makedirs(OUT, exist_ok=True)
    a = Assembler()
    for mesh_name in MESHES:
        try:
            name = a.mesh_for(mesh_name)
            if name is None:
                print(f"{mesh_name}: NOT EXTRACTABLE")
                print("-" * 72)
                continue
            ps = a.parts(name, False)
            if not ps:
                print(f"{mesh_name}: no parts")
                print("-" * 72)
                continue
            sc = trimesh.Scene()
            texinfo = []
            for subkey, g in ps:
                sc.add_geometry(g, node_name=subkey, geom_name=subkey)
                mat = getattr(g.visual, "material", None)
                img = getattr(mat, "baseColorTexture", None) if mat else None
                nrm = getattr(mat, "normalTexture", None) if mat else None
                texinfo.append(
                    "  %s: faces=%d tex=%s nrm=%s"
                    % (
                        subkey,
                        len(g.faces),
                        getattr(img, "size", None),
                        getattr(nrm, "size", None),
                    )
                )
            b = sc.bounds
            dest = os.path.join(OUT, mesh_name + ".glb")
            sc.export(dest)
            kb = os.path.getsize(dest) // 1024
            print(f"{mesh_name}: {len(ps)} submeshes, {kb} KB")
            print(f"  AABB min={b[0].round(3)} max={b[1].round(3)}")
            for t in texinfo:
                print(t)
        except Exception as e:
            import traceback

            print(f"{mesh_name}: FAILED {type(e).__name__}: {e}")
            traceback.print_exc()
        print("-" * 72, flush=True)


if __name__ == "__main__":
    main()
