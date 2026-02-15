# Blender VDF Plugin

A Blender addon for direct import/export of Two Worlds 1 `.vdf` model files with full shader data preservation.

![Blender 3.0+](https://img.shields.io/badge/blender-3.0%E2%80%935.0-orange) ![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

- **Lossless round-trip** — the complete NTF tree is stored in the Blender scene; on export only mesh data is updated while all shader properties, locators, FrameData and animation references remain untouched
- **Dual UV layers** — UV_Diffuse (texture/bump mapping) and UV_Lightmap are imported as separate Blender UV maps
- **Auto texture loading** — DDS textures referenced by shaders are loaded as materials if found in the same directory
- **Tangent & normal preservation** — original tangent vectors and normal W components are stored as object custom properties and restored on export
- **Byte-identical output** — exporting an unmodified mesh produces a file identical to the original VDF
- **Blender 3.x – 5.0** — three-tier API fallback system handles normals across all Blender versions
- **3D Viewport panel** — sidebar panel (N-panel > VDF) shows shader info, stored VDF status, and clear data option

## Installation

1. Open Blender → Edit → Preferences → Add-ons
2. Click "Install..." and select `io_scene_vdf.py`
3. Enable the checkbox next to "Import-Export: Two Worlds VDF Format"

The addon adds entries to File → Import and File → Export.

## Files

| File | Description |
|------|-------------|
| `io_scene_vdf.py` | Blender addon (single file, no dependencies) |

## Usage

See [GUIDE_blender_plugin.md](GUIDE_blender_plugin.md) for a detailed walkthrough.

**Import:** File → Import → Two Worlds VDF (.vdf)

**Export:** File → Export → Two Worlds VDF (.vdf)

**Sidebar:** 3D Viewport → N-panel → VDF tab — shows shader info for selected object

## How It Works

**Import:**
1. Parses the VDF using an entry-order preserving NTF parser
2. Decodes vertex format 1 (36 bytes/vertex: position 3×float + normal UBYTE4N + tangent UBYTE4N + UV1 2×float + UV2 2×float)
3. Creates Blender meshes with two UV layers
4. Stores the entire original VDF as base64 in scene custom properties (chunked for Blender's string limit)
5. Stores per-object tangent data and normal W as custom properties

**Export:**
1. Loads the stored NTF tree from scene properties
2. Extracts updated positions, normals, and UVs from Blender meshes
3. Restores original tangents and normal W from stored properties
4. Encodes back to vertex format 1, updates mesh chunks in the NTF tree
5. Recalculates bounding boxes (TMin/TMax)
6. Writes the full NTF tree — all non-mesh data remains byte-identical

## Technical Notes

- Vertex format: 36 bytes per vertex (position 12B + normal 4B UBYTE4N + tangent 4B UBYTE4N + UV1 8B + UV2 8B)
- Triangle indices: uint16
- Base64 storage uses 60KB chunks to stay within Blender's custom property string limits
- Normal API compatibility: `use_auto_smooth` (3.x) → `normals_split_custom_set_from_vertices` (4.1+) → `corner_normals` (5.0)

## License

MIT
