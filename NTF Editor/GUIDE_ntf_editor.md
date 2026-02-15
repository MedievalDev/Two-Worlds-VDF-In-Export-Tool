# Guide — NTF Editor v1.0

## Installation

1. Place `ntf_editor.py` in any folder
2. Run with `python ntf_editor.py` or use the batch launcher
3. No additional packages required — uses only Python stdlib + tkinter

## Opening a File

File → Open (Ctrl+O)

Supported file types:
- `.vdf` — 3D model files (most common)
- `.bon` — Skeleton/bone files
- `.vif` — Vertex info files
- `.d00` – `.d03` — Detail level variants

The editor parses the NTF binary tree and displays it in the left panel.

## Interface

### Left: Node Tree

The tree shows the full NTF hierarchy. Each node displays:

- **Type number** — the NTF node type (e.g. Type 1 = mesh, Type -253 = shader)
- **Color coding** — different node types have distinct colors for quick identification
- Expandable children — click to expand and see child nodes

### Right: Detail Panel

When you select a node, the detail panel shows all its data chunks:

- **Chunk name** — e.g. `ShaderName`, `TexS0`, `NumVertexes`, `TMin`
- **Type** — data type (string, int32, float32, binary, vector)
- **Value** — the current value, formatted for readability

### Status Bar

Shows file info: path, size, node count, total chunks.

## Editing Chunk Values

1. Select a node in the tree
2. Double-click a chunk in the detail panel (or Edit → Edit Selected Chunk)
3. The edit dialog appears with the current value
4. Change the value and click OK
5. The modification is marked — save to write changes

**Editable types:**
- Strings — text values (e.g. shader names, texture paths, file references)
- Integers — int32 values (e.g. vertex counts, face counts)
- Floats — float32 values (e.g. bounding box coordinates, scale factors)
- Vectors — multi-float values displayed as comma-separated numbers

**Not directly editable:**
- Binary chunks — raw byte data (mesh vertex/face buffers). Use the Blender plugin or OBJ converter to modify mesh geometry.

## Tools Menu

### Show Textures

Scans all shader nodes and lists every texture reference found in TexS0, TexS1, and TexS2 fields. Useful for quickly seeing which DDS files a model needs.

### Show Shaders

Lists all shader nodes with their names and properties — shader effect file, texture slots, and other parameters.

### Statistics

Shows an overview of the file structure: total nodes by type, total chunks, mesh data summary (vertex and face counts per mesh node).

### Shader Transplant

The main workflow tool for restoring shader data after an OBJ roundtrip edit.

**When to use:**
You edited a VDF through the OBJ converter workflow (VDF → OBJ → Blender/3ds Max → OBJ → VDF) and the new VDF has correct geometry but wrong or missing shader properties.

**Steps:**

1. Open the **edited** VDF (File → Open) — this is the file with the new mesh
2. Go to Tools → **Shader Transplant**
3. Select the **original** VDF — the backup copy with the correct shaders
4. The editor shows a preview dialog:
   - Left column: original shaders (source)
   - Right column: edited shaders (target)
   - Matched shaders are shown side by side
5. Click **Apply** to copy all shader properties from original to edited
6. Save the result (File → Save)

**What gets transplanted:**
- Shader effect file references (`.efx`)
- All texture slots (TexS0, TexS1, TexS2)
- Shader parameters and properties
- The shader node structure

**What stays from the edited file:**
- Mesh geometry (vertices, faces)
- UV coordinates
- Bounding boxes
- Node tree structure

### Verify Integrity (F5)

Checks the NTF structure for issues: broken references, unexpected node types, malformed chunks. Useful after manual edits to ensure the file is valid.

## Find Chunk

Edit → Find Chunk (or via the search field)

Searches for chunks by name across the entire node tree. Useful for finding specific properties like a texture reference or a shader parameter. Jumps to the matching node and highlights the chunk.

## Saving

- **Ctrl+S** — Save (overwrites the current file)
- **Ctrl+Shift+S** — Save As (choose a new path)

The editor writes the NTF binary format byte-perfectly. Unchanged data remains identical to the original.

## Common Tasks

### Check what textures a model uses

1. Open the VDF
2. Tools → Show Textures
3. All referenced DDS paths are listed

### Change a texture reference

1. Open the VDF
2. Expand the shader nodes in the tree
3. Find the `TexS0` / `TexS1` / `TexS2` chunks
4. Double-click to edit the path
5. Save

### Fix shaders after OBJ roundtrip

1. Make a backup of the original VDF before editing
2. Do the OBJ roundtrip (VDF → OBJ → edit → OBJ → VDF)
3. Open the edited VDF in the NTF Editor
4. Tools → Shader Transplant → select the original backup
5. Apply and save

### Inspect file structure

1. Open any NTF file
2. Expand the tree to explore the node hierarchy
3. Tools → Statistics for an overview
4. Edit → Find Chunk to search for specific data

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+O | Open file |
| Ctrl+S | Save |
| Ctrl+Shift+S | Save As |
| F5 | Verify Integrity |
| Double-click | Edit selected chunk |

## License

MIT
