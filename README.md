# TW1 Model Tools

**Modding tools for Two Worlds 1 (2007, Reality Pump Studios)**

A complete toolkit for working with Two Worlds 1 game assets — 3D models, shader data, and game parameters.

---

## Tools

### Blender VDF Plugin (io_scene_vdf/)

Direct import/export of `.vdf` model files in Blender — no OBJ roundtrip needed.

- Lossless shader preservation (stores full NTF tree, only updates mesh data on export)
- Dual UV layer support: UV_Diffuse and UV_Lightmap
- Auto-loads DDS textures from the same directory
- Preserves tangent data, normal W component, FrameData, locators, animations
- Byte-identical round-trip for unchanged meshes
- Compatible with Blender 3.x through 5.0 (three-tier API fallback for normals)
- 3D Viewport panel showing shader info and stored VDF status

### NTF Editor (ntf_editor/)

GUI editor for NTF/VDF binary files — inspect and modify the node tree, shaders, textures and chunk data.

- Full NTF node tree visualization with type-based icons and color coding
- Edit any chunk value directly (strings, ints, floats, vectors)
- Shader Transplant — restore original shader data to an edited VDF after OBJ roundtrip
- Texture overview, shader listing, file statistics
- Find Chunk search across the entire node tree
- Integrity verification
- Supports all NTF file types: `.vdf`, `.bon`, `.vif`, `.d00`–`.d03`

### VDF-to-OBJ Converter (vdf_to_obj/)

Extracts 3D models from TW1's `.vdf` files into `.obj + .mtl` for editing in any 3D application.

- Batch conversion with recursive folder scanning
- Automatic LOD detection and merging
- Texture resolver (finds and copies DDS textures)
- Multi-group export with full material data

### OBJ-to-VDF Converter (obj_to_vdf/)

Converts `.obj + .mtl` models back into `.vdf + .mtr` files that TW1 can load.

- Multi-material / multi-group support
- Automatic tangent calculation
- Texture reference mapping (TexS0 / TexS1 / TexS2)
- Built-in roundtrip validation

---

## Recommended Workflows

### Best: Blender Plugin (lossless)

```
TW1 Game Files                              Blender
─────────────                              ────────
 SWORD_01.vdf ──► Blender Import ──► Edit mesh, UVs, materials
                                     All shader data preserved
                                              │
 SWORD_01.vdf ◄── Blender Export ◄────────────┘
                   (byte-identical shaders, updated mesh only)
```

### Alternative: OBJ Roundtrip + Shader Transplant

```
TW1 Game Files                          Any 3D Editor
─────────────                          ──────────────
 SWORD_01.vdf ──► VDF-to-OBJ ──► SWORD_01.obj ──► Edit in 3ds Max / Maya
                                  SWORD_01.mtl     Modify mesh, add textures
                                                          │
 SWORD_01.vdf ◄── OBJ-to-VDF ◄── SWORD_01.obj ◄──────────┘
 SWORD_01.mtr                     SWORD_01.mtl
                  │
                  └──► NTF Editor (Shader Transplant)
                       Restore original shader data from backup
```

---

## VDF Format Documentation

See **VDF_FORMAT.md** for the complete reverse-engineered specification of the VDF/NTF binary format, including the node tree structure, vertex encoding, face buffer layout and shader properties.

---

## Requirements

- **Python 3.8+**
- **Tkinter** (included with most Python installations) — required for GUI tools
- **Blender 3.0+** — required for the VDF plugin (tested up to Blender 5.0)
- No additional pip packages needed

---

## Game File Structure

TW1's extracted model assets are typically organized as:

```
WDFiles/Graphics/
├── Models/              ← VDF + MTR files
│   ├── Characters/
│   ├── Environment/
│   ├── Equipment/
│   ├── FURNITURE/
│   ├── Houses/
│   └── ...
└── Textures/            ← DDS textures
    ├── Trees/
    ├── Grasses/
    └── ...
```

Each model consists of:

| File | Purpose |
|------|---------|
| `NAME.vdf` | Main model (geometry + materials) |
| `NAME_LOD.vdf` | Optional lower-detail variant |
| `NAME.mtr` | Material reference file |

---

## Credits

- **BugLord** — Original NTF format reverse-engineering and documentation
- Format research, tool development and additional RE work by the TW1 modding community

---

## License

MIT License — see individual tool directories for details.
