# VDF-to-OBJ Converter v1.1

**Export Two Worlds 1 models to OBJ for editing in Blender, 3ds Max, Maya, etc.**

Reads TW1's proprietary `.vdf` model files and converts them to standard `.obj + .mtl` format with full material data and texture references.

---

## Features

- **Complete NTF parser** — reads all chunk types in the VDF/NTF binary format
- **VertexFormat 1 decoder** — positions, packed normals, UV1 (diffuse/bump), UV2 (lightmap)
- **Generic fallback** — attempts stride detection for unknown vertex formats
- **Multi-group export** — preserves all mesh groups and their materials
- **MTL generation** — diffuse color, specular, textures, alpha
- **LOD merging** — automatically pairs `NAME.vdf` with `NAME_LOD.vdf`
- **Recursive folder scan** — processes entire model directory trees
- **Folder structure mirroring** — output preserves the original directory hierarchy
- **Texture resolver** — finds DDS textures in the `Textures/` folder and copies them next to the OBJ
- **Auto-detection** — locates the `Textures/` folder automatically from the input path
- **GUI + CLI** — Tkinter dark-theme interface or command-line usage

---

## Quick Start

### GUI Mode

Double-click `START_VDF_CONVERTER.bat` or run:

```
python tw1_vdf_converter.py
```

The GUI opens with three fields:

| Field | Purpose | Example |
|-------|---------|---------|
| **Input Folder** | Folder containing `.vdf` files | `WDFiles/Graphics/Models` |
| **Output Folder** | Where to save `.obj` + `.mtl` | auto-filled as `Input/OBJ_Export` |
| **Textures Folder** | DDS texture source | auto-detected from input path |

Click **Convert All** or select specific files and click **Convert Selected**.

### CLI Mode

**Single file:**

```
python tw1_vdf_converter.py path/to/MODEL.vdf
```

**Folder (recursive):**

```
python tw1_vdf_converter.py path/to/Models/ output_folder/
```

---

## Output

For each model, the converter produces:

| File | Contents |
|------|----------|
| `NAME.obj` | Geometry — vertices, normals, UVs, faces, material refs |
| `NAME.mtl` | Materials — colors, specular, texture filenames |
| `*.dds` | Copied texture files (if Textures folder was provided) |

### OBJ Structure

Each mesh group from the VDF becomes a named group in the OBJ:

```
g CATAPULT_01_MXPolanieShader2
usemtl MXPolanieShader2
v ...
vt ...
vn ...
f 1/1/1 2/2/2 3/3/3
```

If a LOD file was found, its groups are appended with a `_LOD_` prefix.

### MTL Mapping

| VDF Field | MTL Field | Description |
|-----------|-----------|-------------|
| DestColor | `Kd` | Diffuse color |
| SpecColor (RGB) | `Ks` | Specular color |
| SpecColor (W) | `Ns` | Specular exponent |
| Alpha | `d` | Transparency |
| TexS0 | `map_Kd` | Diffuse texture |
| TexS1 | `map_bump` | Normal/bump map |
| TexS2 | `map_Ka` | Lightmap (as ambient map) |

---

## Importing into Blender

1. **File → Import → Wavefront (.obj)**
2. Select the exported `.obj` file
3. Textures load automatically if the DDS files are in the same folder
4. Each mesh group appears as a separate object or mesh group

**Tip**: Install a DDS plugin for Blender if textures don't display (Blender 3.x+ supports DDS natively).

---

## Texture Resolver

The converter can automatically find and copy DDS textures referenced by the model. It works by:

1. Auto-detecting the `Textures/` folder by walking up the directory tree from the input path (looks for a sibling `Textures` folder next to `Models`)
2. Building a case-insensitive filename index of all `.dds` files in the textures directory tree
3. Copying matching textures next to the exported OBJ

If the auto-detection doesn't find your textures folder, you can set it manually in the GUI or pass it as a parameter.

---

## Game File Location

TW1's extracted assets are typically at:

```
WDFiles/Graphics/
├── Models/           ← Input (VDF + MTR files)
│   ├── Characters/
│   ├── Equipment/
│   ├── FURNITURE/
│   └── ...
└── Textures/         ← Texture source (DDS files)
    ├── Trees/
    └── ...
```

---

## Limitations

- **VertexFormat 1 only** — this is the most common format; other formats use a generic stride-detection fallback that may not decode normals/UVs correctly
- **No skeleton/animation** — the `AniFileName` reference is read but animation data is not exported
- **MTR files ignored** — material data comes from the shader nodes embedded in the VDF itself

---

## Requirements

- Python 3.8+
- Tkinter (for GUI mode, included with standard Python)
- No additional packages needed
