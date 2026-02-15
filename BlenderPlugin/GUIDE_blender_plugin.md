# Guide — Blender VDF Plugin

## Installation

1. Download `Blender_vdf_Plugin.py`
2. Open Blender → Edit → Preferences → Add-ons
3. Click **Install...** and select the file
4. Enable the checkbox next to **Import-Export: Two Worlds VDF Format**
5. The addon is ready — no restart needed

## Importing a VDF

1. File → Import → **Two Worlds VDF (.vdf)**
2. Navigate to the `.vdf` file and click Import
3. The model appears in the 3D viewport with:
   - Mesh geometry (vertices, faces)
   - Two UV layers: **UV_Diffuse** and **UV_Lightmap**
   - Materials with shader metadata (visible in material properties)
   - DDS textures auto-loaded if found next to the VDF

Each mesh in the VDF becomes a separate Blender object. Object names match the shader material names from the VDF (e.g. `Wood`, `Metal`).

### What Gets Stored

The plugin stores the complete original VDF data in the scene so it can be restored on export:

- **Scene custom properties** — the full NTF binary tree as base64 chunks
- **Object custom properties** — per-vertex tangent data and normal W components

You can see this data in the Properties panel under "Custom Properties". Do not modify these manually.

### Sidebar Panel

Open the sidebar (press **N** in the 3D viewport) and select the **VDF** tab to see:

- Whether VDF data is stored in the scene
- Original file size
- Shader name and textures for the selected object
- A **Clear VDF Data** button to remove stored data (if you no longer need lossless export)

## Editing the Model

You can use all standard Blender tools:

- **Move, rotate, scale** vertices
- **Add or remove** faces and vertices
- **Edit UVs** in the UV Editor (select UV_Diffuse or UV_Lightmap layer)
- **Apply modifiers** (subdivision, mirror, etc.) — these are applied automatically on export

Things to keep in mind:

- The plugin triangulates on export, so you can work with quads/n-gons
- Vertex count and face count can change freely
- UV_Diffuse is used for the diffuse and bump textures; UV_Lightmap is used for lightmap UVs
- Normals are averaged per-vertex on export (loop normals → vertex normals)

## Exporting a VDF

1. File → Export → **Two Worlds VDF (.vdf)**
2. Choose the output path and click Export

The plugin:

1. Loads the stored NTF tree from the scene
2. For each mesh object, extracts updated geometry and UVs
3. Encodes vertices back to the binary format (36 bytes/vertex)
4. Updates only the mesh chunks (Vertexes, Faces, NumVertexes, NumFaces) and bounding boxes
5. Preserves all shader data, textures, locators, FrameData, and animation references

If the mesh is unchanged, the output is **byte-identical** to the original.

## Workflow Examples

### Simple Mesh Edit

1. Import `ROADSIGN_01.vdf`
2. Select the mesh, enter Edit Mode
3. Move some vertices, adjust UVs
4. Export as `ROADSIGN_01.vdf`
5. Place in your mod's WD archive → works in-game

### Retexturing

1. Import the VDF
2. In the material properties, note the shader texture slots (TexS0, TexS1, TexS2)
3. Replace DDS textures in the game's texture folder
4. No re-export needed — shader data stays the same, only the DDS files change

### Creating a Variant

1. Import `ROADSIGN_L_13.vdf`
2. Modify the mesh (e.g. change the sign shape)
3. Export as `ROADSIGN_L_14.vdf`
4. The new VDF inherits all shader properties from the original

## Troubleshooting

### "No VDF data stored in scene"

You need to import a VDF first before exporting. The plugin needs the stored NTF tree to write a valid VDF.

### Textures not loading

The plugin looks for DDS files in the same directory as the VDF. Make sure the textures referenced by the shaders (TexS0, TexS1, TexS2) are present.

### Blender 5.0 normal warnings

The plugin automatically handles Blender's API changes. If you see warnings about `calc_normals_split`, they can be ignored — the fallback to `corner_normals` is working.

### Export file size differs

If you changed the vertex or face count, the file size will differ. This is expected. Only the mesh chunks change — shader data remains identical.

## Limitations

- Only vertex format 1 (36 bytes/vertex) is supported — this covers all standard Two Worlds models
- Triangle indices are uint16, limiting meshes to 65,535 vertices per sub-mesh
- Tangent vectors are restored from the stored original; they are not recalculated from the edited mesh
- Adding entirely new mesh objects to a VDF is not supported — only modifying existing meshes

## License

MIT
