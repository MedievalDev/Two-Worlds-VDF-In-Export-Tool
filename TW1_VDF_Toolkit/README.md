# TW1 VDF Toolkit v1.0

**Unified Two Worlds 1 Model Tool** — Convert, edit and rebuild VDF model files.

Combines three separate tools into one application:
- VDF → OBJ Converter
- OBJ → VDF Converter  
- NTF Binary Editor

## Features

### Tab 1 — VDF Import (VDF → OBJ)
- Convert single VDF files or batch-process entire folders (2000+ files)
- Generates OBJ + MTL + Metadata JSON per model
- Automatic LOD detection and pairing
- Texture copying (scans for referenced DDS files)
- Progress bar with cancel support for batch operations

### Tab 2 — OBJ Export (OBJ → VDF)
- Convert OBJ files back to VDF format
- Searchable metadata template library (type to filter)
- Per-mesh shader and texture configuration
- Build from scratch or restore original VDF structure via metadata
- Optional MTR file generation

### Tab 3 — Edit VDF Data
- Full NTF binary tree editor for VDF, MTR and metadata files
- Node tree with search/filter
- Chunk editing with type-aware validation (int32, uint32, float, string)
- Texture overview across all shaders
- Stats view (node counts, data sizes)
- Shader transplant from original VDF
- Byte-identical roundtrip verification

## Requirements

- Python 3.8+
- Tkinter (included with standard Python on Windows)

No additional packages required.

## Installation

1. Place `tw1_vdf_toolkit.py` and `tw1_vdf_toolkit.bat` in any folder
2. Double-click `tw1_vdf_toolkit.bat` to launch (or run `python tw1_vdf_toolkit.py`)

## Quick Start

### Extract a VDF model
1. Open **Tab 1 — VDF Import**
2. Click **Browse File** and select a `.vdf` file
3. Set an output folder
4. Optionally set a Textures folder (for DDS copying)
5. Click **Convert**

### Convert an OBJ back to VDF
1. Open **Tab 2 — OBJ Export**
2. Select your `.obj` file
3. Choose a metadata template from the library (or leave empty for default)
4. Configure shader and textures per mesh
5. Click **Convert**

### Edit VDF internals
1. Open **Tab 3 — Edit VDF Data**
2. Click **Open** and select a `.vdf`, `.mtr` or `_vdf_metadata.json` file
3. Browse the node tree, double-click chunks to edit values
4. Save with **Save** or **Save As**

## Metadata System

When importing VDF files, the toolkit generates a JSON sidecar file containing:
- Original shader settings (ShaderName, textures, colors)
- Mesh statistics (vertex count, face count, format)
- Locator data
- Base64-encoded NTF skeleton (full VDF structure minus mesh data)

This metadata enables lossless round-trips: export to OBJ, edit in Blender, re-import with all original VDF properties preserved. External OBJ files can also use metadata from similar models as templates.

## Supported Formats

| Extension | Description |
|-----------|-------------|
| `.vdf` | Two Worlds 1 model file |
| `.mtr` | Two Worlds 1 material file |
| `.chm` | Chunked mesh |
| `.chv` | Chunked vertices |
| `.xfn` | XFN data |
| `.hor` | Horizon data |

## Vertex Format

Format 1 — 36 bytes per vertex:
- Position: 3x float32 (12 bytes)
- Normal: UBYTE4N packed (4 bytes)
- Tangent: UBYTE4N packed (4 bytes)
- UV Set 1: 2x float32 (8 bytes)
- UV Set 2: 2x float32 (8 bytes)

## Known Shaders

`buildings_lmap`, `equipment_base`, `vegetation_base`, `vegetation_lmap`, `character_base`, `terrain_base`, `decal_base`, `water_base`, `particle_base`, `character_dx`, `buildings_base`

## Settings

Accessible via **Settings** in the menu bar:
- **Metadata Folder** — where JSON sidecar files are stored (default: `./vdf_metadata/`)
- **Default Shader** — used when building VDF without metadata
- **Default Textures Folder** — for texture lookups

Settings are saved in `toolkit_config.json` next to the script.

## License

Tool created for the Two Worlds 1 modding community.
