# VDF / NTF Binary Format Specification

**Reverse-engineered format documentation for Two Worlds 1 model files**

This document describes the binary format used by `.vdf` (model) and `.mtr` (material reference) files in Two Worlds 1 (2007, Reality Pump Studios). Both file types use the same underlying container format called **NTF** (Node Tree Format).

---

## Table of Contents

- [Overview](#overview)
- [NTF Container Format](#ntf-container-format)
  - [File Header](#file-header)
  - [Node Structure](#node-structure)
  - [Chunk Types (Flag 1)](#chunk-types-flag-1)
  - [Child Node Types (Flag 2)](#child-node-types-flag-2)
- [VDF Tree Structure](#vdf-tree-structure)
- [Vertex Format 1](#vertex-format-1)
  - [Layout](#layout)
  - [UBYTE4N Encoding](#ubyte4n-encoding)
  - [UV Channels](#uv-channels)
- [Face Index Buffer](#face-index-buffer)
- [Shader / Material Properties](#shader--material-properties)
- [MTR Files](#mtr-files)
- [LOD Files](#lod-files)
- [Reference Values](#reference-values)

---

## Overview

Every TW1 3D model is stored as a `.vdf` file containing one or more mesh groups, each with its own geometry data and shader/material definition. The format is a binary tree of typed nodes, allowing nested structures.

A typical model on disk:

```
BAR_02_1.vdf        Main model (geometry + embedded materials)
BAR_02_1_LOD.vdf    Optional low-detail variant
BAR_02.mtr          Material reference (also NTF format)
```

---

## NTF Container Format

### File Header

| Offset | Size | Type | Value | Description |
|--------|------|------|-------|-------------|
| 0x00 | 4 | uint32 | `0x9F9966F6` | Magic number (little-endian on disk) |

When read with `struct.unpack('<I')`, the magic value is `0xF666999F`.

### Node Structure

After the header, the file contains a flat sequence of nodes that form a recursive tree. Each node begins with:

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| +0x00 | 1 | uint8 | **Flag**: `1` = Chunk (data leaf), `2` = Child (subtree) |
| +0x01 | 4 | uint32 | **NodeSize**: byte count from this field's position to node end |

**Important**: `NodeSize` is measured from the start of the size field itself, meaning it includes its own 4 bytes. The actual content begins at offset +0x05 and has `NodeSize - 4` bytes.

### Chunk Types (Flag 1)

When Flag = 1, the node is a data chunk. Content after the size field:

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| +0x05 | 1 | uint8 | **ChunkType** (see table below) |
| +0x06 | 4 | uint32 | Name string length |
| +0x0A | N | ASCII | Name string (not null-terminated) |
| +0x0A+N | ... | varies | Payload (depends on ChunkType) |

**ChunkType Table:**

| Type | Data Format | Payload Size | Used For |
|------|-------------|--------------|----------|
| 17 | int32 (signed) | 4 bytes | `Type`, `VertexFormat`, `IsLocator` |
| 18 | uint32 (unsigned) | 4 bytes | `NumVertexes`, `NumFaces` |
| 19 | float32 | 4 bytes | `Alpha`, `NearRange`, `FarRange` |
| 20 | vec4 (4×float32) | 16 bytes | `SpecColor`, `DestColor`, `LDir` |
| 20 | vec4i (4×int32) | 16 bytes | `LPos` only — special case! |
| 21 | mat4x4 (16×float32) | 64 bytes | Transformation matrices |
| 22 | string | remaining bytes | `Name`, `ShaderName`, `TexS0`, `AniFileName` |
| 23 | raw bytes | remaining bytes | `Vertexes`, `Faces` (binary buffers) |

**Note on ChunkType 20**: The field `LPos` (locator position) uses `int32` instead of `float32` for its four components. All other vec4 fields use float. This must be handled as a special case when reading and writing.

### Child Node Types (Flag 2)

When Flag = 2, the node opens a child subtree. Content after the size field:

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| +0x05 | 4 | int32 (signed) | **ChildType** |
| +0x09 | ... | nodes | Recursive node list until NodeEnd |

**ChildType Table:**

| Value | Meaning | Contains |
|-------|---------|----------|
| -254 | Mesh Group | Geometry data + shader child |
| -253 | Shader / Material | Texture refs, colors, properties |
| 5 | Locator (Pivot Point) | Position and direction |

---

## VDF Tree Structure

A typical VDF file has this tree layout:

```
Root (NTF)
│
├── AniFileName: ""                          (string, animation reference)
│
├── Child Type 5: LOCATOR
│   ├── IsLocator: 1                         (int32)
│   ├── LPos: [0, 0, 0, 0]                  (vec4i — integers!)
│   └── LDir: [0.0, 0.0, 0.0, 0.0]         (vec4)
│
├── Child Type -254: MESH GROUP 1
│   ├── Type: 1                              (int32, mesh marker)
│   ├── Name: "mesh_name"                    (string)
│   ├── VertexFormat: 1                      (int32)
│   ├── NumVertexes: 226                     (uint32)
│   ├── NumFaces: 984                        (uint32, index count!)
│   ├── Vertexes: <raw bytes>                (NumVertexes × stride)
│   ├── Faces: <raw bytes>                   (NumFaces × 2 bytes)
│   │
│   └── Child Type -253: SHADER
│       ├── Name: "EN_STONE_02"              (string)
│       ├── ShaderName: "buildings_lmap"      (string)
│       ├── TexS0: "EN_STONE_02.dds"         (diffuse texture)
│       ├── TexS1: "EN_STONE_02f_BUMP.dds"   (normal/bump map)
│       ├── TexS2: "EN_STONE_02_L1.dds"      (lightmap)
│       ├── SpecColor: [0.5, 0.5, 0.5, 16.0] (vec4)
│       ├── DestColor: [0.5, 0.5, 0.5, 1.0]  (vec4)
│       ├── Alpha: 1.0                        (float)
│       ├── NearRange: 0.0                    (float)
│       └── FarRange: 100.0                   (float)
│
├── Child Type -254: MESH GROUP 2            (optional, further groups)
│   └── ...
│
└── ...
```

A single VDF can contain multiple mesh groups, typically one per material. Each mesh group has exactly one shader child.

---

## Vertex Format 1

This is the most common vertex format in TW1 models (`VertexFormat = 1`).

### Layout

**Stride: 36 bytes per vertex**

| Offset | Size | Type | Content |
|--------|------|------|---------|
| 0x00 | 12 | 3×float32 | **Position** (X, Y, Z) |
| 0x0C | 4 | UBYTE4N | **Normal** (X, Y, Z, W) — packed |
| 0x10 | 4 | UBYTE4N | **Tangent** (X, Y, Z, W) — packed |
| 0x14 | 8 | 2×float32 | **UV1** (U, V) — diffuse + bump |
| 0x1C | 8 | 2×float32 | **UV2** (U, V) — lightmap |

Total vertex buffer size = `NumVertexes × 36` bytes.

### UBYTE4N Encoding

Normals and tangents are stored as 4 packed bytes, each representing a normalized float component.

**Decoding** (byte → float):

```
component = (byte - 128) / 127.0
```

This produces values in the range approximately -1.008 to +1.0.

**Encoding** (float → byte):

```
byte = clamp(round(float × 127.0 + 128.0), 0, 255)
```

The 4th byte (W component) is typically 255 (+1.0) and is ignored for normals and tangents during rendering.

**Example**: A normal pointing straight up (0, 1, 0) encodes as bytes `[128, 255, 128, 255]`.

### UV Channels

| UV Channel | Vertex Offset | Maps To | Description |
|------------|---------------|---------|-------------|
| UV1 | 0x14 | TexS0 + TexS1 | Diffuse and bump textures share UV1 |
| UV2 | 0x1C | TexS2 | Lightmap texture coordinates |

---

## Face Index Buffer

| Property | Value |
|----------|-------|
| Index type | uint16 (2 bytes per index) |
| Topology | Triangle list |
| Base | 0-indexed |

**Important**: The `NumFaces` field stores the number of **indices**, not the number of triangles.

```
Number of triangles = NumFaces / 3
Buffer size in bytes = NumFaces × 2
```

**Example**: `NumFaces = 2670` means 890 triangles, stored in 5340 bytes.

The maximum number of unique vertices per mesh group is 65535 (uint16 limit).

---

## Shader / Material Properties

Each mesh group contains a shader child node (ChildType -253) with these fields:

### Texture Slots

| Field | UV Channel | Purpose | Example |
|-------|------------|---------|---------|
| TexS0 | UV1 | Diffuse texture | `"EN_STONE_02.dds"` |
| TexS1 | UV1 | Bump / normal map | `"EN_STONE_02f_BUMP.dds"` |
| TexS2 | UV2 | Lightmap | `"EN_STONE_02_L1.dds"` |

All textures are DDS format. Texture filenames are stored without path — the engine resolves them from its texture directories.

### Color Properties

| Field | Type | Description | Typical Values |
|-------|------|-------------|----------------|
| DestColor | vec4 | Diffuse base color [R, G, B, A] | [0.5, 0.5, 0.5, 1.0] |
| SpecColor | vec4 | Specular color + exponent [R, G, B, Exp] | [0.5, 0.5, 0.5, 16.0] |

Color components are in the range 0.0 to 1.0. The specular exponent (4th component of SpecColor) typically ranges from 8.0 to 64.0.

### Other Properties

| Field | Type | Description |
|-------|------|-------------|
| ShaderName | string | Engine shader program name |
| Alpha | float | Transparency value (1.0 = opaque) |
| NearRange | float | Minimum rendering distance |
| FarRange | float | Maximum rendering distance |

### Known Shader Names

| Shader | Typical Use |
|--------|-------------|
| `buildings_lmap` | Buildings, structures, static objects |
| `equipment_base` | Weapons, armor, items |
| `vegetation_base` | Trees, plants (no lightmap) |
| `vegetation_lmap` | Vegetation with lightmap |
| `character_base` | Characters, NPCs |
| `terrain_base` | Terrain meshes |
| `decal_base` | Decals, overlays |
| `water_base` | Water surfaces |

---

## MTR Files

Material reference files (`.mtr`) use the same NTF container format with the same magic header. They contain shader/material definitions as standalone files and are placed alongside VDF files:

```
BAR_02_1.vdf     ← Model geometry + embedded materials
BAR_02.mtr       ← Material reference (shared across LODs)
```

The MTR tree structure contains one or more shader child nodes (ChildType -253) with the same fields as the shader nodes inside VDF files.

---

## LOD Files

Lower-detail variants follow the naming convention `NAME_LOD.vdf` and use the same format as the main model but with reduced vertex and face counts:

```
CATAPULT_01.vdf       ← Full detail (10215 vertices)
CATAPULT_01_LOD.vdf   ← Low detail (fewer vertices)
```

LOD files have identical tree structure and can be parsed with the same code.

---

## Reference Values

Data from a known working model (`EN_STONE_02_1.vdf`) for validation:

```
Mesh Group "EN_STONE_02":
  VertexFormat:  1
  NumVertexes:   226
  NumFaces:      984  (= 328 triangles)
  Vertex data:   8136 bytes (226 × 36)
  Face data:     1968 bytes (984 × 2)

Shader:
  Name:          "EN_STONE_02"
  ShaderName:    "buildings_lmap"
  TexS0:         "EN_STONE_02.dds"
  TexS1:         "EN_STONE_02f_BUMP.dds"
  TexS2:         "EN_STONE_02_L1.dds"
  DestColor:     [0.5, 0.5, 0.5, 1.0]
  SpecColor:     [0.5, 0.5, 0.5, 16.0]

Locator:
  IsLocator:     1
  LPos:          [0, 0, 0, 0]  (int32!)
  LDir:          [0.0, 0.0, 0.0, 0.0]
```

---

## Credits

- **BugLord** — Original NTF format reverse-engineering
- Additional RE work and vertex format analysis by the TW1 modding community
