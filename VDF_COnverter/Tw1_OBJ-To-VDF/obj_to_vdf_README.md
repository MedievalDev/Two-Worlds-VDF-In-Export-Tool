# OBJ-to-VDF Converter v1.0

**Import custom 3D models into Two Worlds 1**

Converts standard `.obj + .mtl` files into TW1's proprietary `.vdf + .mtr` format, allowing you to bring new or modified models into the game.

---

## Features

- **Full OBJ support** — vertices, normals, UVs, faces, groups, materials
- **Automatic triangulation** — quads and n-gons are converted to triangles
- **Multi-material export** — each material group becomes a separate VDF mesh group
- **Tangent calculation** — per-triangle tangent generation with Gram-Schmidt orthogonalization
- **Texture mapping** — MTL texture references are mapped to VDF texture slots (TexS0/TexS1/TexS2)
- **Automatic DDS extension** — non-DDS texture names (.png, .tga, .jpg) are converted to .dds
- **MTR file generation** — optional material reference file alongside the VDF
- **Roundtrip validation** — every exported VDF is parsed back and verified
- **Configurable shader** — choose the TW1 engine shader and rendering distance
- **GUI + CLI** — Tkinter dark-theme interface or command-line usage

---

## Quick Start

### GUI Mode

Double-click `START_OBJ_TO_VDF.bat` or run:

```
python tw1_obj_to_vdf.py
```

| Field | Purpose | Default |
|-------|---------|---------|
| **OBJ File** | Your `.obj` model file | — |
| **Output Folder** | Where to save `.vdf` + `.mtr` | Same folder as OBJ |
| **ShaderName** | TW1 engine shader | `buildings_lmap` |
| **NearRange** | Minimum render distance | `0.0` |
| **FarRange** | Maximum render distance | `100.0` |

Options:

| Checkbox | Default | Description |
|----------|---------|-------------|
| Write .mtr file | ✓ | Generate material reference file alongside VDF |
| Roundtrip validation | ✓ | Parse the written VDF back and verify data integrity |

### CLI Mode

```bash
# Basic
python tw1_obj_to_vdf.py model.obj

# With output folder
python tw1_obj_to_vdf.py model.obj output/

# With output folder and shader
python tw1_obj_to_vdf.py model.obj output/ equipment_base
```

---

## Output

| File | Contents |
|------|----------|
| `NAME.vdf` | Complete model with geometry and embedded materials |
| `NAME.mtr` | Material reference file (optional) |

Both files use the NTF binary format. See [VDF_FORMAT.md](../VDF_FORMAT.md) for the full specification.

---

## Preparing Your OBJ

### Materials (MTL)

The converter maps MTL fields to VDF shader properties:

| MTL Field | VDF Field | Description |
|-----------|-----------|-------------|
| `map_Kd` | TexS0 | Diffuse texture |
| `map_bump` / `bump` | TexS1 | Normal/bump map |
| `map_Ka` | TexS2 | Lightmap |
| `Kd` | DestColor (RGB) | Diffuse color |
| `Ks` | SpecColor (RGB) | Specular color |
| `Ns` | SpecColor (W) | Specular exponent |
| `d` | Alpha | Transparency |

**Texture names**: Use the DDS filenames that exist in TW1's `Textures/` folder. If your MTL references `.png` or `.tga` files, the converter automatically changes the extension to `.dds`.

**No MTL?** The converter works without a MTL file — it uses default material values (mid-gray diffuse, no textures).

### Mesh Groups

Organize your model using OBJ groups (`g`) and materials (`usemtl`). Each unique material becomes a separate mesh group in the VDF:

```obj
g wooden_parts
usemtl wood_material
f 1/1/1 2/2/2 3/3/3
...

g metal_parts
usemtl metal_material
f 10/10/10 11/11/11 12/12/12
...
```

### Vertex Limit

Each mesh group supports a maximum of **65535 vertices** (uint16 index buffer). If a group exceeds this limit, the converter will warn you. Split large meshes into multiple groups if needed.

### Face Format

All common OBJ face formats are supported:

| Format | Example | Description |
|--------|---------|-------------|
| `v/vt/vn` | `f 1/1/1 2/2/2 3/3/3` | Position + UV + normal (ideal) |
| `v/vt` | `f 1/1 2/2 3/3` | Position + UV, default normal |
| `v//vn` | `f 1//1 2//2 3//3` | Position + normal, default UV |
| `v` | `f 1 2 3` | Position only, defaults for rest |

Quads and n-gons are automatically triangulated using fan triangulation.

---

## Shader Selection

Choose the appropriate TW1 shader based on what your model is:

| Shader | Use For |
|--------|---------|
| `buildings_lmap` | Buildings, structures, furniture, static objects |
| `equipment_base` | Weapons, armor, wearable items |
| `vegetation_base` | Trees, plants, grass |
| `character_base` | Characters, NPCs, creatures |
| `terrain_base` | Terrain patches |
| `decal_base` | Decals, ground overlays |

The shader name is written into every material group in the VDF. If unsure, `buildings_lmap` is a safe default for most static objects.

---

## Validation

When "Roundtrip validation" is enabled, the converter:

1. Writes the VDF binary
2. Parses it back using a complete NTF parser
3. Verifies that vertex counts, face counts, group counts and data sizes match

A successful validation looks like:

```
✓ Roundtrip OK: 10215 verts, 38208 indices (12736 tris), 4 group(s)
```

This ensures the binary is structurally correct. Final in-game testing is still recommended.

---

## Technical Details

### Vertex Encoding

The converter produces **VertexFormat 1** (36 bytes per vertex):

| Component | Encoding | Size |
|-----------|----------|------|
| Position | 3×float32 | 12 bytes |
| Normal | UBYTE4N (packed) | 4 bytes |
| Tangent | UBYTE4N (packed) | 4 bytes |
| UV1 (diffuse/bump) | 2×float32 | 8 bytes |
| UV2 (lightmap) | 2×float32 | 8 bytes |

**Tangent calculation**: Tangents are computed per-triangle from position and UV deltas, accumulated per-vertex and orthogonalized against the normal using Gram-Schmidt. Degenerate UV triangles fall back to an arbitrary perpendicular vector.

**UV2 (lightmap)**: Always set to (0, 0). The TW1 engine generates lightmap UVs in its own editor.

### NTF Node Size

The `NodeSize` field counts bytes from the start of the size field itself to the end of the node. This means it includes its own 4 bytes. This is a critical detail for writing valid NTF files — an incorrect size will make the entire file unreadable.

---

## Workflow Example

Full roundtrip — export a TW1 model, modify it, and re-import:

```bash
# 1. Export from game
python tw1_vdf_converter.py Models/Equipment/SWORD_01.vdf exported/

# 2. Edit in Blender
#    Open exported/SWORD_01.obj, modify geometry, save

# 3. Import back to game
python tw1_obj_to_vdf.py exported/SWORD_01.obj Models/Equipment/ equipment_base

# 4. Test in TW1
#    The game should now load your modified SWORD_01.vdf
```

---

## Limitations

- **Single file only** — processes one OBJ at a time (no batch mode)
- **No LOD generation** — create LOD models manually and convert them separately as `NAME_LOD.vdf`
- **No animation** — the `AniFileName` field is written as empty; animation references need to be set by other tools
- **VertexFormat 1 only** — the only confirmed format; other formats may exist but are undocumented
- **No DDS conversion** — textures must already be in DDS format; the converter only updates filename extensions in the references

---

## Requirements

- Python 3.8+
- Tkinter (for GUI mode, included with standard Python)
- No additional packages needed
