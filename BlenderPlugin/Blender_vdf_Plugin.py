bl_info = {
    "name": "Two Worlds VDF Format",
    "author": "NTF Tools",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "File > Import/Export",
    "description": "Import/Export Two Worlds .vdf model files with full shader data preservation",
    "category": "Import-Export",
}

import bpy
import bmesh
import struct
import os
import json
import math
import base64
from io import BytesIO
from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

# ============================================================
# NTF Parser/Writer (entry-order preserving for byte-identical round-trip)
# ============================================================

HEADER_MAGIC = bytes([0x9f, 0x99, 0x66, 0xf6])
TEXTURE_FIELDS = {"TexS0", "TexS1", "TexS2"}
ENTRY_CHUNK = 'chunk'
ENTRY_CHILD = 'child'


class BinaryReader:
    def __init__(self, data):
        self.data = data; self.offset = 0
    def is_end(self): return self.offset >= len(self.data)
    def read(self, n):
        r = self.data[self.offset:self.offset+n]; self.offset += n; return r
    def uint8(self):   return struct.unpack_from('<B', self.read(1))[0]
    def int32(self):   return struct.unpack_from('<i', self.read(4))[0]
    def uint32(self):  return struct.unpack_from('<I', self.read(4))[0]
    def float32(self): return struct.unpack_from('<f', self.read(4))[0]
    def dstr(self):
        length = self.uint32()
        return self.read(length).decode('ascii', errors='replace')
    def slice_to(self, end):
        d = self.data[self.offset:end]; self.offset = end; return BinaryReader(d)
    def read_to(self, end):
        d = self.data[self.offset:end]; self.offset = end; return d


class BinaryWriter:
    def __init__(self): self.buf = BytesIO()
    def write(self, d): self.buf.write(d)
    def uint8(self, v):   self.buf.write(struct.pack('<B', v))
    def int32(self, v):   self.buf.write(struct.pack('<i', v))
    def uint32(self, v):  self.buf.write(struct.pack('<I', v))
    def float32(self, v): self.buf.write(struct.pack('<f', v))
    def dstr(self, s):
        raw = s.encode('ascii'); self.uint32(len(raw)); self.buf.write(raw)
    def get_bytes(self): return self.buf.getvalue()


class ChunkData:
    def __init__(self, chunk_type, name, value):
        self.chunk_type = chunk_type; self.name = name; self.value = value


class NTFNode:
    def __init__(self, node_type=None):
        self.node_type = node_type; self.entries = []
    @property
    def chunks(self): return [d for t,d in self.entries if t == ENTRY_CHUNK]
    @property
    def children(self): return [d for t,d in self.entries if t == ENTRY_CHILD]
    def add_chunk(self, c): self.entries.append((ENTRY_CHUNK, c))
    def add_child(self, c): self.entries.append((ENTRY_CHILD, c))
    @property
    def data(self): return {c.name: c.value for c in self.chunks}
    @property
    def name(self): return self.data.get("Name", "")

    def get_chunk(self, name):
        for c in self.chunks:
            if c.name == name: return c
        return None

    def set_chunk(self, name, value):
        for et, d in self.entries:
            if et == ENTRY_CHUNK and d.name == name:
                d.value = value; return True
        return False


def parse_node_list(reader, node_type=None):
    node = NTFNode(node_type)
    while not reader.is_end():
        flag = reader.uint8()
        start = reader.offset
        size = reader.uint32()
        if flag == 1:
            ct = reader.uint8(); name = reader.dstr()
            if ct == 17:   val = reader.int32()
            elif ct == 18: val = reader.uint32()
            elif ct == 19: val = reader.float32()
            elif ct == 20:
                val = [reader.int32() for _ in range(4)] if name == "LPos" else [reader.float32() for _ in range(4)]
            elif ct == 21: val = [reader.float32() for _ in range(16)]
            elif ct == 22: val = reader.read_to(start + size).decode('ascii', errors='replace')
            elif ct == 23: val = reader.read_to(start + size)
            else: val = reader.read_to(start + size)
            node.add_chunk(ChunkData(ct, name, val))
        elif flag == 2:
            child_type = reader.int32()
            node.add_child(parse_node_list(reader.slice_to(start + size), child_type))
        else:
            reader.offset = start + size
    return node


def parse_ntf(filepath):
    with open(filepath, 'rb') as f: data = f.read()
    if data[:4] != HEADER_MAGIC:
        raise ValueError(f"Invalid NTF header: {data[:4].hex()}")
    root = parse_node_list(BinaryReader(data[4:]))
    while len(root.children) == 1 and len(root.chunks) == 0:
        root = root.children[0]
    return root


def write_chunk_bytes(chunk):
    w = BinaryWriter(); w.uint8(chunk.chunk_type); w.dstr(chunk.name)
    ct = chunk.chunk_type
    if ct == 17:   w.int32(chunk.value)
    elif ct == 18: w.uint32(chunk.value)
    elif ct == 19: w.float32(chunk.value)
    elif ct == 20:
        for v in chunk.value: (w.int32 if chunk.name == "LPos" else w.float32)(v)
    elif ct == 21:
        for v in chunk.value: w.float32(v)
    elif ct == 22: w.write(chunk.value.encode('ascii'))
    elif ct == 23: w.write(chunk.value)
    return w.get_bytes()


def write_node_list(node):
    r = BinaryWriter()
    for et, data in node.entries:
        if et == ENTRY_CHUNK:
            cb = write_chunk_bytes(data); r.uint8(1); r.uint32(len(cb)+4); r.write(cb)
        elif et == ENTRY_CHILD:
            cb = write_node_list(data); r.uint8(2); r.uint32(4+4+len(cb))
            r.int32(data.node_type if data.node_type is not None else -1); r.write(cb)
    return r.get_bytes()


def save_ntf(filepath, root):
    content = write_node_list(root)
    with open(filepath, 'wb') as f:
        f.write(HEADER_MAGIC)
        if root.node_type is not None:
            f.write(struct.pack('<B', 2))
            f.write(struct.pack('<I', 4+4+len(content)))
            f.write(struct.pack('<i', root.node_type))
        f.write(content)


# ============================================================
# VDF Mesh Decode/Encode
# ============================================================

def decode_vertex_format1(raw, num_verts):
    """Decode: 36 bytes/vert = pos(3f) + normal(4B) + tangent(4B) + uv1(2f) + uv2(2f)"""
    positions = []; normals = []; tangents = []; uv1s = []; uv2s = []
    for i in range(num_verts):
        off = i * 36
        px, py, pz = struct.unpack_from('<3f', raw, off)
        positions.append((px, py, pz))

        nb = struct.unpack_from('<4B', raw, off + 12)
        normals.append(((nb[0]-128)/127.0, (nb[1]-128)/127.0, (nb[2]-128)/127.0, nb[3]))

        tb = struct.unpack_from('<4B', raw, off + 16)
        tangents.append(tb)

        u1, v1 = struct.unpack_from('<2f', raw, off + 20)
        uv1s.append((u1, v1))

        u2, v2 = struct.unpack_from('<2f', raw, off + 28)
        uv2s.append((u2, v2))

    return positions, normals, tangents, uv1s, uv2s


def decode_vertex_generic(raw, num_verts, vfmt):
    """Fallback for unknown vertex formats."""
    if num_verts == 0:
        return [], [], [], [], []
    stride = len(raw) // num_verts
    positions = []; normals = []; tangents = []; uv1s = []; uv2s = []
    for i in range(num_verts):
        off = i * stride
        if stride >= 12:
            px, py, pz = struct.unpack_from('<3f', raw, off)
            positions.append((px, py, pz))
        else:
            positions.append((0,0,0))

        if stride >= 20:
            nb = struct.unpack_from('<4B', raw, off + 12)
            normals.append(((nb[0]-128)/127.0, (nb[1]-128)/127.0, (nb[2]-128)/127.0, nb[3]))
            tb = struct.unpack_from('<4B', raw, off + 16) if stride >= 20 else (128,128,128,128)
            tangents.append(tb)
        else:
            normals.append((0, 1, 0, 128))
            tangents.append((128,128,128,128))

        if stride >= 28:
            uv_off = 20 if stride >= 36 else 16
            u, v = struct.unpack_from('<2f', raw, off + uv_off)
            uv1s.append((u, v))
        else:
            uv1s.append((0, 0))

        if stride >= 36:
            u2, v2 = struct.unpack_from('<2f', raw, off + 28)
            uv2s.append((u2, v2))
        else:
            uv2s.append((0, 0))

    return positions, normals, tangents, uv1s, uv2s


def decode_faces(raw, num_indices):
    """uint16 triangle indices."""
    faces = []
    actual = min(num_indices, len(raw) // 2)
    indices = struct.unpack_from(f'<{actual}H', raw)
    for i in range(0, actual - 2, 3):
        faces.append((indices[i], indices[i+1], indices[i+2]))
    return faces


def encode_vertex_format1(positions, normals, tangents, uv1s, uv2s):
    """Encode back to 36 bytes/vert binary."""
    buf = bytearray()
    for i in range(len(positions)):
        px, py, pz = positions[i]
        buf += struct.pack('<3f', px, py, pz)

        # Normal: float -> UBYTE4N
        nx, ny, nz = normals[i][0], normals[i][1], normals[i][2]
        nw = normals[i][3] if len(normals[i]) > 3 else 128
        nb0 = max(0, min(255, int(round(nx * 127 + 128))))
        nb1 = max(0, min(255, int(round(ny * 127 + 128))))
        nb2 = max(0, min(255, int(round(nz * 127 + 128))))
        nb3 = max(0, min(255, int(nw)))
        buf += struct.pack('<4B', nb0, nb1, nb2, nb3)

        # Tangent: pass through original bytes
        if tangents and i < len(tangents):
            t = tangents[i]
            buf += struct.pack('<4B', t[0], t[1], t[2], t[3])
        else:
            buf += struct.pack('<4B', 128, 128, 255, 128)

        # UV1
        u1, v1 = uv1s[i] if i < len(uv1s) else (0, 0)
        buf += struct.pack('<2f', u1, v1)

        # UV2
        u2, v2 = uv2s[i] if i < len(uv2s) else (0, 0)
        buf += struct.pack('<2f', u2, v2)

    return bytes(buf)


def encode_faces(faces):
    """Encode triangle list to uint16 indices."""
    buf = bytearray()
    for f in faces:
        buf += struct.pack('<3H', f[0], f[1], f[2])
    return bytes(buf)


def compute_bbox(positions):
    """Compute bounding box as TMin/TMax float32[4]."""
    if not positions:
        return [0,0,0,0], [0,0,0,0]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    return (
        [min(xs), min(ys), min(zs), 0.0],
        [max(xs), max(ys), max(zs), 0.0]
    )


# ============================================================
# NTF Tree helpers
# ============================================================

def find_nodes(node, pred, res=None):
    if res is None: res = []
    if pred(node): res.append(node)
    for c in node.children: find_nodes(c, pred, res)
    return res


def find_mesh_nodes(root):
    """Find all mesh nodes (Type=1 with Vertexes)."""
    return find_nodes(root, lambda n: n.data.get('Type') == 1 and n.get_chunk('Vertexes') is not None)


def find_shader_child(node):
    """Find shader child node (type -253)."""
    for c in node.children:
        if c.node_type == -253: return c
    return None


# ============================================================
# Original VDF Storage (store in scene as base64 for undo safety)
# ============================================================

def store_original_vdf(scene, filepath):
    """Store the original VDF file as base64 in scene custom properties."""
    with open(filepath, 'rb') as f:
        data = f.read()
    # Store in chunks to avoid Blender string limit
    encoded = base64.b64encode(data).decode('ascii')
    chunk_size = 60000  # safe limit for Blender string props
    num_chunks = (len(encoded) + chunk_size - 1) // chunk_size

    scene["vdf_original_path"] = filepath
    scene["vdf_original_chunks"] = num_chunks
    scene["vdf_original_size"] = len(data)
    for i in range(num_chunks):
        scene[f"vdf_original_{i}"] = encoded[i*chunk_size:(i+1)*chunk_size]


def load_original_vdf(scene):
    """Reconstruct original VDF binary from stored scene properties."""
    num_chunks = scene.get("vdf_original_chunks", 0)
    if num_chunks == 0:
        return None
    encoded = ""
    for i in range(num_chunks):
        encoded += scene.get(f"vdf_original_{i}", "")
    return base64.b64decode(encoded)


def clear_original_vdf(scene):
    """Remove stored VDF data."""
    num_chunks = scene.get("vdf_original_chunks", 0)
    for key in ["vdf_original_path", "vdf_original_chunks", "vdf_original_size"]:
        if key in scene: del scene[key]
    for i in range(num_chunks):
        key = f"vdf_original_{i}"
        if key in scene: del scene[key]


# ============================================================
# Blender Import
# ============================================================

class ImportVDF(bpy.types.Operator, ImportHelper):
    """Import Two Worlds VDF model"""
    bl_idname = "import_scene.vdf"
    bl_label = "Import VDF"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".vdf"
    filter_glob: StringProperty(default="*.vdf", options={'HIDDEN'})

    import_uv2: BoolProperty(
        name="Import UV2 (Lightmap)",
        description="Import second UV channel for lightmap",
        default=True,
    )

    def execute(self, context):
        return self.import_vdf(context, self.filepath)

    def import_vdf(self, context, filepath):
        try:
            root = parse_ntf(filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse VDF: {e}")
            return {'CANCELLED'}

        mesh_nodes = find_mesh_nodes(root)
        if not mesh_nodes:
            self.report({'WARNING'}, "No mesh data found in VDF")
            return {'CANCELLED'}

        # Store original VDF for lossless export
        store_original_vdf(context.scene, filepath)

        basename = os.path.splitext(os.path.basename(filepath))[0]

        # Create a parent empty for the model
        parent_empty = bpy.data.objects.new(basename, None)
        context.collection.objects.link(parent_empty)
        parent_empty["vdf_source"] = filepath
        parent_empty["vdf_is_root"] = True

        imported_count = 0

        for mesh_idx, mnode in enumerate(mesh_nodes):
            raw_verts = mnode.data.get('Vertexes', b'')
            raw_faces = mnode.data.get('Faces', b'')
            num_verts = mnode.data.get('NumVertexes', 0)
            num_faces = mnode.data.get('NumFaces', 0)
            vfmt = mnode.data.get('VertexFormat', 1)

            if num_verts == 0 or num_faces == 0:
                continue

            # Decode
            if vfmt == 1 and len(raw_verts) == num_verts * 36:
                positions, normals, tangents, uv1s, uv2s = decode_vertex_format1(raw_verts, num_verts)
            else:
                positions, normals, tangents, uv1s, uv2s = decode_vertex_generic(raw_verts, num_verts, vfmt)

            faces = decode_faces(raw_faces, num_faces)

            # Shader info
            shader = find_shader_child(mnode)
            shader_name = shader.data.get('Name', 'default') if shader else 'default'

            # Object name
            node_name = mnode.name or f"mesh_{mesh_idx}"
            obj_name = f"{basename}_{shader_name}_{mesh_idx}"

            # Create Blender mesh
            bl_mesh = bpy.data.meshes.new(obj_name)
            bl_obj = bpy.data.objects.new(obj_name, bl_mesh)
            context.collection.objects.link(bl_obj)
            bl_obj.parent = parent_empty

            # Store mesh index for export mapping
            bl_obj["vdf_mesh_index"] = mesh_idx
            bl_obj["vdf_node_name"] = node_name
            bl_obj["vdf_vertex_format"] = vfmt

            # Store original tangent data (not editable in Blender, pass through)
            tangent_b64 = base64.b64encode(
                b''.join(struct.pack('<4B', *t) for t in tangents)
            ).decode('ascii')
            bl_obj["vdf_tangents"] = tangent_b64

            # Store original normal W component
            nw_data = base64.b64encode(
                struct.pack(f'<{len(normals)}B', *[int(n[3]) if len(n)>3 else 128 for n in normals])
            ).decode('ascii')
            bl_obj["vdf_normal_w"] = nw_data

            # Build mesh geometry
            bl_mesh.from_pydata(positions, [], faces)

            # UV1 (Diffuse/Bump)
            uv1_layer = bl_mesh.uv_layers.new(name="UV_Diffuse")
            for poly in bl_mesh.polygons:
                for li in poly.loop_indices:
                    vi = bl_mesh.loops[li].vertex_index
                    if vi < len(uv1s):
                        u, v = uv1s[vi]
                        uv1_layer.data[li].uv = (u, 1.0 - v)  # Flip V for Blender

            # UV2 (Lightmap)
            if self.import_uv2 and uv2s:
                uv2_layer = bl_mesh.uv_layers.new(name="UV_Lightmap")
                for poly in bl_mesh.polygons:
                    for li in poly.loop_indices:
                        vi = bl_mesh.loops[li].vertex_index
                        if vi < len(uv2s):
                            u, v = uv2s[vi]
                            uv2_layer.data[li].uv = (u, 1.0 - v)

            # Custom normals
            bl_mesh.update()
            if normals:
                nor_list = [(n[0], n[1], n[2]) for n in normals]
                try:
                    # Blender 4.0 and earlier
                    bl_mesh.use_auto_smooth = True
                    bl_mesh.normals_split_custom_set_from_vertices(nor_list)
                except AttributeError:
                    try:
                        # Blender 4.1+ / 5.0
                        bl_mesh.normals_split_custom_set_from_vertices(nor_list)
                    except Exception:
                        pass  # Normals will use Blender defaults

            bl_mesh.update()

            # Create material placeholder
            if shader:
                mat = bpy.data.materials.new(name=f"{shader_name}")
                mat.use_nodes = True
                mat["vdf_shader_name"] = shader.data.get('ShaderName', '')
                mat["vdf_tex_diffuse"] = shader.data.get('TexS0', '')
                mat["vdf_tex_normal"] = shader.data.get('TexS1', '')
                mat["vdf_tex_lightmap"] = shader.data.get('TexS2', '')

                # Try to load diffuse texture
                tex_dir = os.path.dirname(filepath)
                diff_name = shader.data.get('TexS0', '')
                if diff_name:
                    diff_path = os.path.join(tex_dir, diff_name)
                    if os.path.isfile(diff_path):
                        try:
                            bsdf = mat.node_tree.nodes.get("Principled BSDF")
                            if bsdf:
                                tex_node = mat.node_tree.nodes.new('ShaderNodeTexImage')
                                tex_node.image = bpy.data.images.load(diff_path)
                                mat.node_tree.links.new(bsdf.inputs['Base Color'], tex_node.outputs['Color'])
                        except:
                            pass

                bl_obj.data.materials.append(mat)

            imported_count += 1

        self.report({'INFO'}, f"Imported {imported_count} mesh(es) from {os.path.basename(filepath)}")
        return {'FINISHED'}


# ============================================================
# Blender Export
# ============================================================

class ExportVDF(bpy.types.Operator, ExportHelper):
    """Export Two Worlds VDF model (preserves original shader data)"""
    bl_idname = "export_scene.vdf"
    bl_label = "Export VDF"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".vdf"
    filter_glob: StringProperty(default="*.vdf", options={'HIDDEN'})

    export_uv2: BoolProperty(
        name="Export UV2 (Lightmap)",
        description="Export second UV channel",
        default=True,
    )

    def execute(self, context):
        return self.export_vdf(context, self.filepath)

    def export_vdf(self, context, filepath):
        scene = context.scene

        # Load original VDF data
        original_data = load_original_vdf(scene)
        if original_data is None:
            self.report({'ERROR'}, "No original VDF data found. Import a VDF first!")
            return {'CANCELLED'}

        # Re-parse original NTF tree
        try:
            reader = BinaryReader(original_data[4:])  # skip magic
            root = parse_node_list(reader)
            while len(root.children) == 1 and len(root.chunks) == 0:
                root = root.children[0]
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse stored VDF: {e}")
            return {'CANCELLED'}

        # Find mesh nodes in original tree
        mesh_nodes = find_mesh_nodes(root)

        # Find Blender objects that belong to this VDF
        vdf_objects = []
        for obj in scene.objects:
            if obj.type == 'MESH' and "vdf_mesh_index" in obj:
                vdf_objects.append(obj)

        # Sort by mesh index
        vdf_objects.sort(key=lambda o: o["vdf_mesh_index"])

        if not vdf_objects:
            self.report({'ERROR'}, "No VDF mesh objects found in scene")
            return {'CANCELLED'}

        updated = 0

        for obj in vdf_objects:
            mesh_idx = obj["vdf_mesh_index"]
            vfmt = obj.get("vdf_vertex_format", 1)

            if mesh_idx >= len(mesh_nodes):
                self.report({'WARNING'}, f"Mesh index {mesh_idx} out of range, skipping {obj.name}")
                continue

            mnode = mesh_nodes[mesh_idx]

            # Get evaluated mesh (apply modifiers)
            depsgraph = context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)
            bl_mesh = eval_obj.to_mesh()

            # Triangulate
            bm = bmesh.new()
            bm.from_mesh(bl_mesh)
            bmesh.ops.triangulate(bm, faces=bm.faces)
            bm.to_mesh(bl_mesh)
            bm.free()

            num_verts = len(bl_mesh.vertices)
            num_loops = len(bl_mesh.loops)

            # Positions
            positions = [(v.co.x, v.co.y, v.co.z) for v in bl_mesh.vertices]

            # Normals - compatible with Blender 3.x through 5.x
            vert_normals = {}
            try:
                # Blender 4.1+ / 5.0: use corner_normals
                try:
                    bl_mesh.calc_normals()
                except (AttributeError, RuntimeError):
                    pass  # Blender 5.0 auto-calculates
                for li, corner in enumerate(bl_mesh.corner_normals):
                    vi = bl_mesh.loops[li].vertex_index
                    n = corner.vector
                    if vi not in vert_normals:
                        vert_normals[vi] = [0, 0, 0, 0]
                    vert_normals[vi][0] += n[0]
                    vert_normals[vi][1] += n[1]
                    vert_normals[vi][2] += n[2]
                    vert_normals[vi][3] += 1
            except AttributeError:
                try:
                    # Blender 3.x / 4.0: use calc_normals_split
                    bl_mesh.calc_normals_split()
                    for loop in bl_mesh.loops:
                        vi = loop.vertex_index
                        n = loop.normal
                        if vi not in vert_normals:
                            vert_normals[vi] = [0, 0, 0, 0]
                        vert_normals[vi][0] += n[0]
                        vert_normals[vi][1] += n[1]
                        vert_normals[vi][2] += n[2]
                        vert_normals[vi][3] += 1
                except AttributeError:
                    # Fallback: use vertex normals
                    for v in bl_mesh.vertices:
                        vert_normals[v.index] = [v.normal[0], v.normal[1], v.normal[2], 1]

            # Restore original normal W component
            nw_data = None
            if "vdf_normal_w" in obj:
                try:
                    nw_raw = base64.b64decode(obj["vdf_normal_w"])
                    nw_data = struct.unpack(f'<{len(nw_raw)}B', nw_raw)
                except:
                    pass

            normals = []
            for vi in range(num_verts):
                if vi in vert_normals:
                    cnt = vert_normals[vi][3]
                    nx = vert_normals[vi][0] / cnt
                    ny = vert_normals[vi][1] / cnt
                    nz = vert_normals[vi][2] / cnt
                    # Normalize
                    ln = math.sqrt(nx*nx + ny*ny + nz*nz)
                    if ln > 0:
                        nx /= ln; ny /= ln; nz /= ln
                else:
                    nx, ny, nz = 0, 1, 0
                nw = nw_data[vi] if nw_data and vi < len(nw_data) else 128
                normals.append((nx, ny, nz, nw))

            # Tangents: restore from stored data or generate defaults
            tangents = []
            if "vdf_tangents" in obj:
                try:
                    traw = base64.b64decode(obj["vdf_tangents"])
                    for i in range(0, len(traw), 4):
                        tangents.append(struct.unpack_from('<4B', traw, i))
                except:
                    pass

            # Pad or trim tangents to match vertex count
            while len(tangents) < num_verts:
                tangents.append((128, 128, 255, 128))
            tangents = tangents[:num_verts]

            # UV1
            uv1s = [(0.0, 0.0)] * num_verts
            if bl_mesh.uv_layers:
                uv_layer = bl_mesh.uv_layers[0]  # First UV = diffuse
                for poly in bl_mesh.polygons:
                    for li in poly.loop_indices:
                        vi = bl_mesh.loops[li].vertex_index
                        u, v = uv_layer.data[li].uv
                        uv1s[vi] = (u, 1.0 - v)  # Flip V back

            # UV2
            uv2s = [(0.0, 0.0)] * num_verts
            if self.export_uv2 and len(bl_mesh.uv_layers) >= 2:
                uv2_layer = bl_mesh.uv_layers[1]
                for poly in bl_mesh.polygons:
                    for li in poly.loop_indices:
                        vi = bl_mesh.loops[li].vertex_index
                        u, v = uv2_layer.data[li].uv
                        uv2s[vi] = (u, 1.0 - v)

            # Faces
            faces = []
            for poly in bl_mesh.polygons:
                if len(poly.vertices) == 3:
                    faces.append(tuple(poly.vertices))

            # Encode
            if vfmt == 1:
                vert_data = encode_vertex_format1(positions, normals, tangents, uv1s, uv2s)
            else:
                vert_data = encode_vertex_format1(positions, normals, tangents, uv1s, uv2s)

            face_data = encode_faces(faces)
            num_indices = len(faces) * 3

            # Update NTF node
            mnode.set_chunk('Vertexes', vert_data)
            mnode.set_chunk('Faces', face_data)
            mnode.set_chunk('NumVertexes', num_verts)
            mnode.set_chunk('NumFaces', num_indices)

            # Update bounding box
            tmin, tmax = compute_bbox(positions)
            if mnode.get_chunk('TMin'):
                mnode.set_chunk('TMin', tmin)
            if mnode.get_chunk('TMax'):
                mnode.set_chunk('TMax', tmax)

            # Also update parent bbox node (type -252)
            for child in mnode.children:
                if child.node_type == -252:
                    if child.get_chunk('TMin'):
                        child.set_chunk('TMin', tmin)
                    if child.get_chunk('TMax'):
                        child.set_chunk('TMax', tmax)

            eval_obj.to_mesh_clear()
            updated += 1

        # Save
        try:
            save_ntf(filepath, root)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save VDF: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Exported {updated} mesh(es) to {os.path.basename(filepath)}")
        return {'FINISHED'}


# ============================================================
# Panel (in Properties > Scene)
# ============================================================

class VDF_PT_panel(bpy.types.Panel):
    bl_label = "Two Worlds VDF"
    bl_idname = "VDF_PT_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        orig_path = scene.get("vdf_original_path", "")
        orig_size = scene.get("vdf_original_size", 0)

        if orig_path:
            box = layout.box()
            box.label(text="Original VDF Loaded", icon='FILE_3D')
            box.label(text=f"File: {os.path.basename(orig_path)}")
            box.label(text=f"Size: {orig_size:,} bytes")

            # Count VDF objects
            vdf_objs = [o for o in scene.objects if o.type == 'MESH' and "vdf_mesh_index" in o]
            box.label(text=f"Meshes: {len(vdf_objs)}")

            layout.operator("export_scene.vdf", text="Export VDF", icon='EXPORT')
            layout.operator("vdf.clear_data", text="Clear Stored VDF", icon='TRASH')
        else:
            layout.label(text="No VDF loaded", icon='INFO')
            layout.operator("import_scene.vdf", text="Import VDF", icon='IMPORT')


class VDF_OT_clear(bpy.types.Operator):
    """Clear stored VDF data from scene"""
    bl_idname = "vdf.clear_data"
    bl_label = "Clear VDF Data"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        clear_original_vdf(context.scene)
        self.report({'INFO'}, "VDF data cleared")
        return {'FINISHED'}


# ============================================================
# Registration
# ============================================================

def menu_func_import(self, context):
    self.layout.operator(ImportVDF.bl_idname, text="Two Worlds VDF (.vdf)")

def menu_func_export(self, context):
    self.layout.operator(ExportVDF.bl_idname, text="Two Worlds VDF (.vdf)")

classes = [ImportVDF, ExportVDF, VDF_PT_panel, VDF_OT_clear]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
