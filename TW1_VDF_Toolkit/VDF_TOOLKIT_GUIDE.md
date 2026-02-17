# TW1 VDF Toolkit — User Guide

A complete guide for working with Two Worlds 1 model files using the VDF Toolkit.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Installation & Setup](#2-installation--setup)
3. [Tab 1 — VDF Import (VDF → OBJ)](#3-tab-1--vdf-import)
4. [Tab 2 — OBJ Export (OBJ → VDF)](#4-tab-2--obj-export)
5. [Tab 3 — Edit VDF Data](#5-tab-3--edit-vdf-data)
6. [The Metadata System](#6-the-metadata-system)
7. [Workflow Examples](#7-workflow-examples)
8. [Technical Reference](#8-technical-reference)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Overview

The TW1 VDF Toolkit is a unified tool for converting, editing and rebuilding Two Worlds 1 model files (`.vdf`). It combines three separate tools into a single application with a tabbed GUI.

**The core problem it solves:** TW1 uses a proprietary binary format (NTF) for its models. These contain not just mesh data (vertices, faces) but also shader assignments, texture paths, material colors, LOD settings, locator positions and more. When you export to OBJ for editing in Blender, all of that extra data is lost. The toolkit's metadata system preserves this data so you can make a clean round-trip.

---

## 2. Installation & Setup

### Requirements
- Python 3.8 or newer
- Tkinter (included with Python on Windows by default)
- No additional pip packages needed

### Files
- `tw1_vdf_toolkit.py` — the main application (≈2300 lines)
- `tw1_vdf_toolkit.bat` — Windows launcher (double-click to start)

### First Launch
1. Place both files in any folder
2. Double-click `tw1_vdf_toolkit.bat`
3. The GUI opens with three tabs

### Initial Settings
Go to **Edit → Settings** and configure:
- **Metadata Folder** — where JSON sidecar files will be stored. Default is `./vdf_metadata/` next to the script. This folder will be created automatically.
- **Default Shader** — used when converting OBJ to VDF without a metadata template. Default: `buildings_lmap`
- **Default Textures Folder** — the toolkit searches here for DDS textures referenced by models. Point this to your TW1 `Textures` folder.

---

## 3. Tab 1 — VDF Import

**Purpose:** Convert VDF model files to OBJ + MTL for editing in Blender or other 3D software.

### Single File Conversion

1. Click **Browse File** and select a `.vdf` file
2. Set the **Output Folder** where OBJ/MTL files will be saved
3. Optionally set a **Textures Folder** — the toolkit will copy referenced DDS files to the output
4. Click **Convert**

**Output per model:**
- `MODELNAME.obj` — mesh geometry (vertices, normals, UVs, faces)
- `MODELNAME.mtl` — material definitions with texture references
- `MODELNAME_vdf_metadata.json` — saved in the metadata folder (not the output folder)
- Referenced `.dds` textures copied to output (if textures folder is set)

### Batch Conversion

1. Click **Browse Folder** and select a folder containing VDF files
2. Check **Recursive** if you want to scan subfolders
3. The file list populates automatically, showing LOD detection
4. Set output folder and textures folder
5. Click **Convert All**

The progress bar shows current file, counter (e.g. "247/2031 (12%)") and estimated time. Click **Cancel** to stop between files — already converted files are kept.

### LOD Handling

The toolkit automatically detects LOD pairs. TW1 models often have:
- `ROCK_01.vdf` — base model
- `ROCK_01_LOD.vdf` — LOD version

Both are listed in the file tree. The base model always gets converted. LOD files are optional.

---

## 4. Tab 2 — OBJ Export

**Purpose:** Convert OBJ files back to VDF format for use in TW1.

### With Metadata Template (Recommended)

This is the best approach — it preserves all original VDF properties.

1. Select your `.obj` file
2. In the **Metadata Template** dropdown, type to search for a matching template
3. Select a template — the mesh panels below auto-fill with shader and texture info
4. Adjust shader/textures per mesh if needed
5. Set output folder
6. Click **Convert**

The toolkit restores the original NTF structure from the base64-encoded skeleton in the metadata, then injects your new mesh data (vertices, faces) into it. This means all original shader settings, material colors, LOD parameters and locator data are preserved.

### Without Metadata (From Scratch)

For completely new models or external OBJ files with no matching template:

1. Select your `.obj` file
2. Leave the metadata dropdown empty
3. Configure each mesh manually:
   - **ShaderName** — choose from the dropdown (e.g. `buildings_lmap`)
   - **TexS0** — diffuse texture path (e.g. `Textures/rocks/rock_diffuse.dds`)
   - **TexS1** — secondary texture (often empty)
   - **TexS2** — lightmap texture
4. Click **Convert**

The toolkit builds a VDF from scratch with default values for NearRange (0.0), FarRange (100.0) and automatic bounding box calculation.

### MTR File

Check **Write .mtr** to generate a separate material file alongside the VDF. Some TW1 setups require this.

### Mesh Panel Details

Each mesh group from the OBJ gets its own panel showing:
- Mesh name (from OBJ group name)
- ShaderName dropdown
- TexS0 / TexS1 / TexS2 texture path entries with browse buttons
- Vertex and face counts

### Texture Browse

The browse buttons for textures open a file dialog. Selected paths are stored relative to the TW1 data root (e.g. `Textures/buildings/wall_01.dds`).

---

## 5. Tab 3 — Edit VDF Data

**Purpose:** Directly inspect and edit the NTF binary structure of VDF files, MTR files, or metadata JSON files.

### Opening Files

Click **Open** or use the menu. Supported file types:
- `.vdf` — model files
- `.mtr` — material files
- `_vdf_metadata.json` — metadata files (opens the embedded NTF skeleton)

### The Node Tree

The left panel shows the hierarchical NTF structure:
- **Root node** — top level
- **Child nodes** — nested, each with a type number
  - Type `-253` = Shader node
  - Type `-252` = Mesh/geometry node
  - Type `-1` = Common container
- **Chunks** — data fields within each node

The tree shows icons indicating node type:
- 🔷 Standard nodes
- 🟠 Shader nodes
- 🟦 Mesh nodes
- 🟢 Locator nodes

### Search/Filter

Type in the search bar to filter the tree. Matches node names and chunk values. Press Enter or just type — filtering is live.

### Editing Chunks

1. Select a node in the tree
2. The right panel shows all chunks for that node
3. Double-click a chunk (or select and click **Edit**)
4. An edit dialog appears with type-aware validation:
   - `int32` — accepts integer values
   - `uint32` — accepts unsigned integer values
   - `float32` — accepts decimal values
   - `text` — accepts string values
   - `binary` — displayed as hex, not directly editable
5. Click **OK** to apply

### Toolbar Functions

- **Open** — load a file
- **Save** — save to the same file (overwrites)
- **Save As** — save to a new file
- **Textures** — shows all texture references (TexS0/TexS1/TexS2) across all shaders in the file
- **Stats** — shows node counts, binary data size, field names
- **Transplant** — shader transplant: loads an original VDF and copies shader settings into the current file, matching by name. Useful when you've rebuilt a VDF but want the original shader/material setup.
- **Verify** — performs a byte-identical roundtrip check: saves to temp file, compares with original. If it matches, the parser and writer are working correctly.

---

## 6. The Metadata System

### What It Stores

Each metadata JSON file contains:

```
{
  "toolkit_version": "1.0",
  "source_vdf": "ROCK_01.vdf",
  "source_path": "/full/path/to/ROCK_01.vdf",
  "created": "2026-02-17T04:15:00",
  "mesh_count": 2,
  "total_vertices": 1842,
  "total_triangles": 2106,
  "meshes": [
    {
      "name": "Rock_Surface",
      "vertex_count": 921,
      "face_count": 1053,
      "triangle_count": 1053,
      "vertex_format": 1,
      "shader": {
        "ShaderName": "buildings_lmap",
        "TexS0": "Textures/rocks/rock_diffuse.dds",
        "TexS1": "",
        "TexS2": "Textures/rocks/rock_lmap.dds",
        "DestColor": [0.5, 0.5, 0.5, 1.0],
        "SpecColor": [0.3, 0.3, 0.3, 16.0],
        "Alpha": 1.0
      }
    }
  ],
  "locator": {"IsLocator": 1, "LPos": [0,0,0,0]},
  "ani_file_name": "",
  "raw_ntf_skeleton": "<base64-encoded NTF>"
}
```

### The NTF Skeleton

The most important field is `raw_ntf_skeleton`. This is the complete NTF binary structure of the original VDF file, with the vertex and face data buffers stripped out (replaced with empty placeholders). Everything else is preserved: node hierarchy, shader assignments, material colors, LOD settings, bounding boxes, locator data.

When converting back to VDF, the toolkit:
1. Decodes the base64 skeleton back to binary
2. Parses it into the NTF node tree
3. Injects new vertex and face buffers from your OBJ
4. Recalculates bounding boxes
5. Writes the final VDF

### Metadata Library

All metadata files are stored in one central folder (configured in Settings). Tab 2 scans this folder and presents all templates in a searchable dropdown. This means:
- Extract 2000 VDF models → get 2000 metadata templates
- When converting any OBJ back, you can choose the most similar template
- External models (not from TW1) can use any template for shader/material defaults

### File Naming

Metadata files are named `MODELNAME_vdf_metadata.json` where MODELNAME matches the source VDF filename (without extension).

---

## 7. Workflow Examples

### Workflow A — Edit an Existing TW1 Model

1. **Import:** Tab 1 → select `building_house.vdf` → Convert
   - Creates `building_house.obj` + `building_house.mtl`
   - Creates `building_house_vdf_metadata.json` in metadata folder
2. **Edit:** Open `building_house.obj` in Blender, make changes, export as OBJ
3. **Export:** Tab 2 → select edited OBJ → choose `building_house` metadata template → Convert
   - New VDF has your mesh changes but all original shader/material data

### Workflow B — Import a New Model into TW1

1. Create or download a model in Blender, export as OBJ
2. Tab 2 → select OBJ → choose a metadata template from a similar TW1 model
3. Adjust shader and textures in the mesh panels
4. Convert → get a VDF ready for the game

### Workflow C — Batch Extract All Game Models

1. Tab 1 → Browse Folder → select the TW1 models directory
2. Check **Recursive**, set output and textures folders
3. Click **Convert All** → go get a coffee
4. You now have OBJ/MTL for every model plus a complete metadata library

### Workflow D — Fix Shader Issues

1. Tab 3 → Open the problematic VDF
2. Browse the node tree to find shader nodes (orange icons)
3. Edit ShaderName, TexS0, TexS1, TexS2 directly
4. Or use **Transplant** to copy shaders from a working VDF
5. Save

### Workflow E — Verify File Integrity

1. Tab 3 → Open any VDF file
2. Click **Verify** in the toolbar
3. The toolkit parses the file, writes it back to a temp file, and compares byte-by-byte
4. "Roundtrip OK" = parser and writer are working correctly for this file

---

## 8. Technical Reference

### NTF Binary Format

TW1 model files use the NTF (Node Tree Format) binary container:

- **Header:** 4-byte magic `9F 99 66 F6`
- **Nodes:** Hierarchical tree structure
  - Each node has a type (int32) and a list of entries
  - Entries are either chunks (data) or child nodes
- **Chunks:** Named data fields with typed values
  - Type 17: int32
  - Type 18: uint32
  - Type 19: float32
  - Type 20: float32[4] (vector/color)
  - Type 21: float32[16] (matrix)
  - Type 22: text string
  - Type 23: binary blob

### Vertex Format 1 (36 bytes per vertex)

| Offset | Size | Type | Content |
|--------|------|------|---------|
| 0 | 12 | 3x float32 | Position (X, Y, Z) |
| 12 | 4 | UBYTE4N | Normal (packed) |
| 16 | 4 | UBYTE4N | Tangent (packed) |
| 20 | 8 | 2x float32 | UV Set 1 (U, V) |
| 28 | 8 | 2x float32 | UV Set 2 (U, V) |

UBYTE4N packing: each component is a byte mapped from [0,255] to [-1.0, 1.0] via `(byte / 127.5) - 1.0`

### Tangent Calculation

When converting OBJ → VDF, tangents are calculated from UV-space derivatives using the standard Gram-Schmidt orthogonalization method. This ensures correct normal mapping in the game.

### Bounding Box

The toolkit automatically calculates axis-aligned bounding boxes (AABB) from vertex positions when building VDF files. The BBox is stored as two float32[4] chunks (BBoxMin, BBoxMax) in the mesh node.

### Face Buffer

Faces are stored as triangle lists with 16-bit indices (uint16). Each triangle is 3 indices = 6 bytes.

---

## 9. Troubleshooting

### "No meshes found in VDF"
The VDF file may use a vertex format other than Format 1 (36 bytes). The toolkit currently supports Format 1 only, which covers the vast majority of TW1 models. Check the vertex format field in Tab 3.

### OBJ has wrong normals in game
TW1 uses packed UBYTE4N normals. If your OBJ normals look wrong, make sure you're exporting from Blender with normals included and the correct coordinate system (Y-up or Z-up may need adjustment).

### Textures not found during import
Set the Textures Folder in Tab 1 to your TW1 `Textures` directory. The toolkit does case-insensitive filename matching, so the paths in the VDF don't need exact case matches.

### Metadata template not showing up
Make sure the metadata folder in Settings points to the folder containing your `_vdf_metadata.json` files. The dropdown scans this folder on Tab 2 activation.

### Roundtrip verification fails
Some VDF files may have unusual structures that the parser doesn't handle identically. This doesn't necessarily mean the output VDF is broken — it may just have minor byte differences in padding or ordering. Test the output VDF in the game/editor.

### Batch conversion stops
Check the log area for error messages. The toolkit continues past errors (logging them) and only stops if you click Cancel. Files that failed are listed in the end summary.
