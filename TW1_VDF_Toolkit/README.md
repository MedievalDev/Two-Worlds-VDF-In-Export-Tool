# TW1 Model Tools

**Modding tools for Two Worlds 1 (2007, Reality Pump Studios)**

Convert 3D models between the proprietary `.vdf` format used by Two Worlds 1 and the standard `.obj` format supported by Blender, 3ds Max, Maya and other 3D software.

---

## Tools

### [VDF-to-OBJ Converter](vdf_to_obj/) — Export from Game

Extracts 3D models from TW1's `.vdf` files into `.obj + .mtl` for editing in any 3D application.

- Batch conversion with recursive folder scanning
- Automatic LOD detection and merging
- Texture resolver (finds and copies DDS textures)
- Multi-group export with full material data

### [OBJ-to-VDF Converter](obj_to_vdf/) — Import into Game

Converts `.obj + .mtl` models back into `.vdf + .mtr` files that TW1 can load.

- Multi-material / multi-group support
- Automatic tangent calculation
- Texture reference mapping (TexS0 / TexS1 / TexS2)
- Built-in roundtrip validation

---

## Full Roundtrip Workflow

```
TW1 Game Files                          Your 3D Editor
─────────────                          ──────────────
 SWORD_01.vdf ──► VDF-to-OBJ ──► SWORD_01.obj ──► Edit in Blender
                                  SWORD_01.mtl     Add textures, modify mesh
                                                          │
 SWORD_01.vdf ◄── OBJ-to-VDF ◄── SWORD_01.obj ◄──────────┘
 SWORD_01.mtr                     SWORD_01.mtl
```

Both converters have been cross-validated against each other — a VDF exported to OBJ and re-imported back to VDF produces identical geometry and material data.

---

## VDF Format Documentation

See **[VDF_FORMAT.md](VDF_FORMAT.md)** for the complete reverse-engineered specification of the VDF/NTF binary format, including the node tree structure, vertex encoding, face buffer layout and shader properties. Useful if you want to build your own tools or parsers.

---

## Requirements

- **Python 3.8+**
- **Tkinter** (included with most Python installations) — required for GUI mode
- No additional pip packages needed

Both tools work as standalone scripts. Each has a `.bat` launcher for Windows (double-click to start GUI) and supports command-line usage.

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
