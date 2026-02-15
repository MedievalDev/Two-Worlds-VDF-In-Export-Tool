# NTF Editor

A GUI editor for Two Worlds 1 NTF binary files — inspect and modify the internal node tree structure of `.vdf` model files, `.bon` skeleton files, and other NTF-based formats.

![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green) ![Platform: Windows/Linux/Mac](https://img.shields.io/badge/platform-Win%20%7C%20Linux%20%7C%20Mac-lightgrey)

## Features

- **Full NTF tree visualization** — hierarchical node tree with type-based color coding and icons
- **Direct chunk editing** — double-click any chunk to edit strings, integers, floats, and vectors
- **Shader Transplant** — copies shader data from an original VDF to an edited VDF, restoring material properties lost during OBJ roundtrip conversion
- **Texture overview** — lists all textures referenced by shaders in the file
- **Shader listing** — shows all shader nodes with their properties
- **File statistics** — node counts, total chunks, mesh info
- **Find Chunk** — search for any chunk by name across the entire node tree
- **Integrity verification** — validates the NTF structure for corruption
- **Multi-format support** — `.mtr & .chm: Animation,
.vdf Models,
.chm,
.chv Model With Bones,
.xfn Font Cache,
.hor Horizon data


## Quick Start

```
python ntf_editor.py
```

Or double-click the launcher script on Windows.

**Requirements:** Python 3.6+ with tkinter (included in standard Python on Windows).

## Files

| File | Description |
|------|-------------|
| `ntf_editor.py` | Main editor script (GUI + NTF parser/writer) |

## Usage

See [GUIDE_ntf_editor.md](GUIDE_ntf_editor.md) for a detailed walkthrough.

**Open:** File → Open (Ctrl+O) — select any NTF-based file

**Navigate:** Click nodes in the tree to see their chunks in the detail panel. Double-click a chunk to edit its value.

**Shader Transplant:** Tools → Shader Transplant — load the original VDF to restore shader data to the currently loaded (edited) VDF.

**Save:** File → Save (Ctrl+S) or Save As (Ctrl+Shift+S)

## Shader Transplant

The main power feature. When you edit a VDF model through the OBJ roundtrip workflow (VDF → OBJ → edit → OBJ → VDF), shader data like effect files, texture slots, and render parameters are lost. Shader Transplant fixes this:

1. Open the **edited** VDF (the one with new mesh but broken shaders)
2. Tools → Shader Transplant
3. Select the **original** VDF (backup with correct shaders)
4. The editor matches shaders by name and shows a preview
5. Confirm to copy all shader properties from original to edited

The result is a VDF with your new mesh geometry and the original shader properties.

## NTF Format

NTF (Node Tree Format) is the binary container format used by Reality Pump's engine (Earth 2150/2160, Two Worlds). It stores a hierarchical tree of typed nodes, each containing named data chunks. VDF files are NTF files containing model-specific nodes (meshes, shaders, locators, animations).

Key node types:
- **Type 1** — Mesh/Model nodes (contain vertex and face data)
- **Type -253** — Shader nodes (contain texture references and effect parameters)
- **Type -252** — FrameData (animation keyframes)
- **Type -251** — Locator nodes (attachment points)

## License

MIT
