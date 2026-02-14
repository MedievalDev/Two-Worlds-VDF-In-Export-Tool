#!/usr/bin/env python3
"""TW1 OBJ-to-VDF Converter v1.0 — Converts .obj + .mtl to Two Worlds 1 .vdf + .mtr model files"""

import struct
import os
import sys
import math
import io
from pathlib import Path
from collections import OrderedDict

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    HAS_TK = True
except ImportError:
    HAS_TK = False

# ═══════════════════════════════════════════════════════════════════════════════
# NTF FORMAT CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

NTF_MAGIC = 0xF666999F   # Little-endian: F6 66 99 9F on disk

# Chunk types (Flag=1)
CHUNK_INT32    = 17   # int32  (Type, VertexFormat, IsLocator)
CHUNK_UINT32   = 18   # uint32 (NumVertexes, NumFaces)
CHUNK_FLOAT    = 19   # float  (Alpha, NearRange, FarRange)
CHUNK_VEC4     = 20   # vec4   (SpecColor, DestColor, LDir) or vec4i (LPos)
CHUNK_MAT4X4   = 21   # mat4x4
CHUNK_STRING   = 22   # string (Name, ShaderName, TexS0, AniFileName)
CHUNK_RAW      = 23   # raw bytes (Vertexes, Faces)

# Child types (Flag=2)
CHILD_SHADER   = -253
CHILD_MESH     = -254
CHILD_LOCATOR  = 5

# ═══════════════════════════════════════════════════════════════════════════════
# OBJ / MTL PARSER
# ═══════════════════════════════════════════════════════════════════════════════

class ObjMaterial:
    """Material parsed from .mtl file."""
    __slots__ = ('name', 'kd', 'ks', 'ns', 'alpha',
                 'map_kd', 'map_bump', 'map_ka')
    def __init__(self, name):
        self.name = name
        self.kd = [0.5, 0.5, 0.5]      # Diffuse color
        self.ks = [0.5, 0.5, 0.5]       # Specular color
        self.ns = 16.0                   # Specular exponent
        self.alpha = 1.0
        self.map_kd = ""                 # Diffuse texture -> TexS0
        self.map_bump = ""               # Bump/Normal map -> TexS1
        self.map_ka = ""                 # Ambient/Lightmap -> TexS2


class ObjGroup:
    """A mesh group from the OBJ file (one per g/usemtl combo)."""
    __slots__ = ('name', 'material_name', 'faces')
    def __init__(self, name, material_name=""):
        self.name = name
        self.material_name = material_name
        self.faces = []   # List of triangulated face tuples: [(vi, vti, vni), ...]


class ObjData:
    """Complete parsed OBJ data."""
    def __init__(self):
        self.positions = []    # [(x, y, z), ...]
        self.normals = []      # [(nx, ny, nz), ...]
        self.uvs = []          # [(u, v), ...]
        self.groups = []       # [ObjGroup, ...]
        self.materials = {}    # name -> ObjMaterial


def parse_mtl(mtl_path):
    """Parse .mtl file. Returns dict of name -> ObjMaterial."""
    materials = {}
    current = None

    if not os.path.isfile(mtl_path):
        return materials

    with open(mtl_path, 'r', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split(None, 1)
            if len(parts) < 1:
                continue
            key = parts[0].lower()
            val = parts[1] if len(parts) > 1 else ""

            if key == 'newmtl':
                name = val.strip()
                current = ObjMaterial(name)
                materials[name] = current
            elif current is None:
                continue
            elif key == 'kd':
                rgb = _parse_floats(val, 3)
                if rgb:
                    current.kd = rgb
            elif key == 'ks':
                rgb = _parse_floats(val, 3)
                if rgb:
                    current.ks = rgb
            elif key == 'ns':
                try:
                    current.ns = float(val.strip())
                except ValueError:
                    pass
            elif key == 'd':
                try:
                    current.alpha = float(val.strip())
                except ValueError:
                    pass
            elif key == 'tr':
                # Tr = 1 - d (alternative transparency)
                try:
                    current.alpha = 1.0 - float(val.strip())
                except ValueError:
                    pass
            elif key == 'map_kd':
                current.map_kd = _extract_filename(val)
            elif key in ('map_bump', 'bump'):
                current.map_bump = _extract_filename(val)
            elif key == 'map_ka':
                current.map_ka = _extract_filename(val)

    return materials


def _parse_floats(text, count):
    """Parse space-separated floats."""
    try:
        vals = [float(x) for x in text.split()[:count]]
        return vals if len(vals) == count else None
    except ValueError:
        return None


def _extract_filename(val):
    """Extract filename from MTL texture path (strip options like -bm 1.0)."""
    # MTL can have: -bm 1.0 textures/foo.dds  or  just foo.dds
    parts = val.strip().split()
    # Walk past any -flag value pairs
    i = 0
    while i < len(parts):
        if parts[i].startswith('-'):
            i += 2   # skip flag + value
        else:
            break
    if i < len(parts):
        # Take everything from here (could be path with spaces? unlikely)
        raw = " ".join(parts[i:])
        # Return just the filename, not directory path
        return os.path.basename(raw)
    return ""


def parse_obj(obj_path, log_func=None):
    """Parse .obj file. Returns ObjData with positions, normals, uvs, groups, materials."""
    def log(msg):
        if log_func:
            log_func(msg)

    data = ObjData()
    current_group = None
    current_material = ""

    # Parse MTL
    obj_dir = os.path.dirname(obj_path)
    mtl_libs = []

    with open(obj_path, 'r', errors='replace') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split(None, 1)
            key = parts[0]
            val = parts[1] if len(parts) > 1 else ""

            if key == 'v':
                coords = _parse_floats(val, 3)
                if coords:
                    data.positions.append(tuple(coords))

            elif key == 'vn':
                coords = _parse_floats(val, 3)
                if coords:
                    data.normals.append(tuple(coords))

            elif key == 'vt':
                coords = _parse_floats(val, 2)
                if coords:
                    data.uvs.append(tuple(coords))
                else:
                    # Some OBJ have 3-component UVs
                    coords = _parse_floats(val, 3)
                    if coords:
                        data.uvs.append((coords[0], coords[1]))

            elif key == 'mtllib':
                mtl_file = val.strip()
                mtl_path = os.path.join(obj_dir, mtl_file)
                if os.path.isfile(mtl_path):
                    mtl_libs.append(mtl_path)

            elif key == 'usemtl':
                current_material = val.strip()
                # Start new group for this material
                group_name = current_group.name if current_group else "default"
                current_group = ObjGroup(group_name, current_material)
                data.groups.append(current_group)

            elif key in ('g', 'o'):
                group_name = val.strip() if val.strip() else "default"
                current_group = ObjGroup(group_name, current_material)
                data.groups.append(current_group)

            elif key == 'f':
                if current_group is None:
                    current_group = ObjGroup("default", current_material)
                    data.groups.append(current_group)

                face_verts = _parse_face(val)
                if len(face_verts) < 3:
                    continue

                # Fan triangulation for quads / n-gons
                for i in range(1, len(face_verts) - 1):
                    current_group.faces.append((
                        face_verts[0],
                        face_verts[i],
                        face_verts[i + 1]
                    ))

    # Parse all referenced MTL files
    for mtl_path in mtl_libs:
        log(f"  Parsing {os.path.basename(mtl_path)}...")
        mtl_mats = parse_mtl(mtl_path)
        data.materials.update(mtl_mats)

    # Remove empty groups
    data.groups = [g for g in data.groups if g.faces]

    # Merge groups with same material into one
    data.groups = _merge_groups_by_material(data.groups)

    log(f"  OBJ: {len(data.positions)} positions, {len(data.normals)} normals, "
        f"{len(data.uvs)} uvs, {len(data.groups)} group(s)")

    return data


def _parse_face(val):
    """Parse a face line: returns list of (vi, vti, vni) tuples (0-indexed, -1 = missing)."""
    verts = []
    for token in val.split():
        parts = token.split('/')
        try:
            vi = int(parts[0]) - 1
        except (ValueError, IndexError):
            continue

        vti = -1
        vni = -1
        if len(parts) > 1 and parts[1]:
            try:
                vti = int(parts[1]) - 1
            except ValueError:
                pass
        if len(parts) > 2 and parts[2]:
            try:
                vni = int(parts[2]) - 1
            except ValueError:
                pass
        verts.append((vi, vti, vni))
    return verts


def _merge_groups_by_material(groups):
    """Merge groups that share the same material name."""
    merged = OrderedDict()
    for g in groups:
        key = g.material_name if g.material_name else g.name
        if key in merged:
            merged[key].faces.extend(g.faces)
        else:
            new_g = ObjGroup(g.name, g.material_name)
            new_g.faces = list(g.faces)
            merged[key] = new_g
    return list(merged.values())


# ═══════════════════════════════════════════════════════════════════════════════
# VERTEX PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

class ProcessedMesh:
    """Mesh ready for VDF encoding."""
    __slots__ = ('name', 'material_name', 'positions', 'normals', 'tangents',
                 'uvs1', 'uvs2', 'indices')
    def __init__(self):
        self.name = ""
        self.material_name = ""
        self.positions = []    # [(x,y,z), ...]
        self.normals = []      # [(nx,ny,nz), ...]
        self.tangents = []     # [(tx,ty,tz), ...]
        self.uvs1 = []         # [(u,v), ...]
        self.uvs2 = []         # [(u,v), ...]  — always (0,0)
        self.indices = []      # [i0, i1, i2, ...]  flat uint16 list


def process_group(obj_data, group, log_func=None):
    """Convert an OBJ group into a ProcessedMesh with unique vertices and tangents."""
    def log(msg):
        if log_func:
            log_func(msg)

    mesh = ProcessedMesh()
    mesh.name = group.name
    mesh.material_name = group.material_name

    # Build unique vertex map: (pos_idx, norm_idx, uv_idx) -> new_index
    vertex_map = {}
    unique_positions = []
    unique_normals = []
    unique_uvs = []
    new_indices = []

    # Default normal/uv for missing data
    default_normal = (0.0, 1.0, 0.0)
    default_uv = (0.0, 0.0)

    for tri in group.faces:
        tri_indices = []
        for vi, vti, vni in tri:
            key = (vi, vti, vni)
            if key in vertex_map:
                tri_indices.append(vertex_map[key])
            else:
                new_idx = len(unique_positions)
                vertex_map[key] = new_idx
                tri_indices.append(new_idx)

                # Position
                if 0 <= vi < len(obj_data.positions):
                    unique_positions.append(obj_data.positions[vi])
                else:
                    unique_positions.append((0.0, 0.0, 0.0))

                # Normal
                if 0 <= vni < len(obj_data.normals):
                    unique_normals.append(obj_data.normals[vni])
                else:
                    unique_normals.append(default_normal)

                # UV
                if 0 <= vti < len(obj_data.uvs):
                    unique_uvs.append(obj_data.uvs[vti])
                else:
                    unique_uvs.append(default_uv)

        new_indices.extend(tri_indices)

    num_verts = len(unique_positions)
    num_indices = len(new_indices)

    # Check uint16 limit
    if num_verts > 65535:
        log(f"    WARNING: Group '{group.name}' has {num_verts} vertices (>65535)! "
            f"VDF uint16 indices will overflow!")

    mesh.positions = unique_positions
    mesh.normals = unique_normals
    mesh.uvs1 = unique_uvs
    mesh.uvs2 = [(0.0, 0.0)] * num_verts   # Lightmap UV = zero
    mesh.indices = new_indices

    # Calculate tangents
    mesh.tangents = _calculate_tangents(
        unique_positions, unique_normals, unique_uvs, new_indices
    )

    log(f"    Group '{mesh.name}': {num_verts} verts, {num_indices // 3} tris")

    return mesh


def _calculate_tangents(positions, normals, uvs, indices):
    """Calculate per-vertex tangents from triangle geometry.
    Uses the standard UV-space tangent derivation, accumulated per vertex.
    """
    num_verts = len(positions)
    # Accumulate tangent vectors
    tan_accum = [[0.0, 0.0, 0.0] for _ in range(num_verts)]

    num_tris = len(indices) // 3
    for t in range(num_tris):
        i0 = indices[t * 3]
        i1 = indices[t * 3 + 1]
        i2 = indices[t * 3 + 2]

        p0 = positions[i0]
        p1 = positions[i1]
        p2 = positions[i2]

        uv0 = uvs[i0]
        uv1 = uvs[i1]
        uv2 = uvs[i2]

        # Edges
        dx1 = p1[0] - p0[0]
        dy1 = p1[1] - p0[1]
        dz1 = p1[2] - p0[2]

        dx2 = p2[0] - p0[0]
        dy2 = p2[1] - p0[1]
        dz2 = p2[2] - p0[2]

        du1 = uv1[0] - uv0[0]
        dv1 = uv1[1] - uv0[1]

        du2 = uv2[0] - uv0[0]
        dv2 = uv2[1] - uv0[1]

        denom = du1 * dv2 - du2 * dv1
        if abs(denom) < 1e-10:
            # Degenerate UV triangle, skip
            continue

        r = 1.0 / denom
        tx = (dv2 * dx1 - dv1 * dx2) * r
        ty = (dv2 * dy1 - dv1 * dy2) * r
        tz = (dv2 * dz1 - dv1 * dz2) * r

        # Accumulate for all 3 vertices
        for idx in (i0, i1, i2):
            tan_accum[idx][0] += tx
            tan_accum[idx][1] += ty
            tan_accum[idx][2] += tz

    # Normalize and orthogonalize against normal (Gram-Schmidt)
    tangents = []
    for i in range(num_verts):
        n = normals[i]
        t = tan_accum[i]

        # Gram-Schmidt: t' = normalize(t - n * dot(n, t))
        dot_nt = n[0] * t[0] + n[1] * t[1] + n[2] * t[2]
        tx = t[0] - n[0] * dot_nt
        ty = t[1] - n[1] * dot_nt
        tz = t[2] - n[2] * dot_nt

        length = math.sqrt(tx * tx + ty * ty + tz * tz)
        if length > 1e-10:
            tangents.append((tx / length, ty / length, tz / length))
        else:
            # Fallback: generate arbitrary tangent perpendicular to normal
            tangents.append(_arbitrary_tangent(n))

    return tangents


def _arbitrary_tangent(normal):
    """Generate an arbitrary tangent vector perpendicular to the given normal."""
    nx, ny, nz = normal
    # Choose the axis least aligned with normal
    if abs(nx) < abs(ny) and abs(nx) < abs(nz):
        up = (1.0, 0.0, 0.0)
    elif abs(ny) < abs(nz):
        up = (0.0, 1.0, 0.0)
    else:
        up = (0.0, 0.0, 1.0)

    # Cross product: tangent = normalize(up × normal)
    tx = up[1] * nz - up[2] * ny
    ty = up[2] * nx - up[0] * nz
    tz = up[0] * ny - up[1] * nx
    length = math.sqrt(tx * tx + ty * ty + tz * tz)
    if length > 1e-10:
        return (tx / length, ty / length, tz / length)
    return (1.0, 0.0, 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# VERTEX ENCODING (VertexFormat 1, 36 Bytes per Vertex)
# ═══════════════════════════════════════════════════════════════════════════════

def encode_ubyte4n(x, y, z, w=1.0):
    """Encode a normalized vector to UBYTE4N (4 bytes).
    float -> byte: clamp(round(float * 127.0 + 128), 0, 255)
    """
    def f2b(f):
        return max(0, min(255, int(round(f * 127.0 + 128.0))))
    return struct.pack('<4B', f2b(x), f2b(y), f2b(z), f2b(w))


def encode_vertex_buffer(mesh):
    """Encode ProcessedMesh vertices into raw bytes (VertexFormat 1, 36 bytes/vert).
    Layout: Position(3f) + Normal(UBYTE4N) + Tangent(UBYTE4N) + UV1(2f) + UV2(2f)
    """
    buf = bytearray()
    for i in range(len(mesh.positions)):
        px, py, pz = mesh.positions[i]
        nx, ny, nz = mesh.normals[i]
        tx, ty, tz = mesh.tangents[i]
        u1, v1 = mesh.uvs1[i]
        u2, v2 = mesh.uvs2[i]

        buf += struct.pack('<3f', px, py, pz)
        buf += encode_ubyte4n(nx, ny, nz, 1.0)
        buf += encode_ubyte4n(tx, ty, tz, 1.0)
        buf += struct.pack('<2f', u1, v1)
        buf += struct.pack('<2f', u2, v2)

    return bytes(buf)


def encode_face_buffer(indices):
    """Encode face indices as uint16 triangle list."""
    return struct.pack(f'<{len(indices)}H', *indices)


# ═══════════════════════════════════════════════════════════════════════════════
# NTF BINARY WRITER
# ═══════════════════════════════════════════════════════════════════════════════

class NTFWriter:
    """Writes NTF binary format (used for both VDF and MTR files)."""

    def __init__(self):
        self.buf = io.BytesIO()
        # Write NTF magic header
        self.buf.write(struct.pack('<I', NTF_MAGIC))

    def write_chunk_int32(self, name, value):
        """Write a ChunkType 17 (int32) node."""
        payload = struct.pack('<i', value)
        self._write_chunk(CHUNK_INT32, name, payload)

    def write_chunk_uint32(self, name, value):
        """Write a ChunkType 18 (uint32) node."""
        payload = struct.pack('<I', value)
        self._write_chunk(CHUNK_UINT32, name, payload)

    def write_chunk_float(self, name, value):
        """Write a ChunkType 19 (float) node."""
        payload = struct.pack('<f', value)
        self._write_chunk(CHUNK_FLOAT, name, payload)

    def write_chunk_vec4(self, name, values):
        """Write a ChunkType 20 (vec4 float) node."""
        payload = struct.pack('<4f', *values)
        self._write_chunk(CHUNK_VEC4, name, payload)

    def write_chunk_vec4i(self, name, values):
        """Write a ChunkType 20 (vec4 int32) node — used for LPos."""
        payload = struct.pack('<4i', *values)
        self._write_chunk(CHUNK_VEC4, name, payload)

    def write_chunk_string(self, name, value):
        """Write a ChunkType 22 (string) node."""
        payload = value.encode('ascii', errors='replace')
        self._write_chunk(CHUNK_STRING, name, payload)

    def write_chunk_raw(self, name, raw_bytes):
        """Write a ChunkType 23 (raw bytes) node."""
        self._write_chunk(CHUNK_RAW, name, raw_bytes)

    def begin_child(self, child_type):
        """Begin a child node list (Flag=2). Returns position for size patching."""
        self.buf.write(b'\x02')                              # Flag = 2 (Child)
        size_pos = self.buf.tell()
        self.buf.write(struct.pack('<I', 0))                 # Size placeholder
        self.buf.write(struct.pack('<i', child_type))        # ChildType (signed)
        return size_pos

    def end_child(self, size_pos):
        """Patch the size field of a child node."""
        end = self.buf.tell()
        size = end - size_pos   # Size = bytes from size field to end (includes own 4 bytes)
        self.buf.seek(size_pos)
        self.buf.write(struct.pack('<I', size))
        self.buf.seek(end)

    def get_bytes(self):
        """Return the complete NTF binary."""
        return self.buf.getvalue()

    def _write_chunk(self, chunk_type, name, payload_bytes):
        """Write a chunk node: Flag(1) + Size(4) + ChunkType(1) + Name(len+str) + Payload."""
        name_bytes = name.encode('ascii', errors='replace')
        content = b''
        content += struct.pack('<B', chunk_type)
        content += struct.pack('<I', len(name_bytes))
        content += name_bytes
        content += payload_bytes

        self.buf.write(b'\x01')                              # Flag = 1 (Chunk)
        self.buf.write(struct.pack('<I', len(content) + 4))  # Size (includes own 4 bytes)
        self.buf.write(content)


# ═══════════════════════════════════════════════════════════════════════════════
# VDF BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

# Known TW1 shader names (fuer Dropdown)
KNOWN_SHADERS = [
    "buildings_lmap",
    "equipment_base",
    "vegetation_base",
    "vegetation_lmap",
    "character_base",
    "terrain_base",
    "decal_base",
    "water_base",
    "particle_base",
]

DEFAULT_SHADER = "buildings_lmap"
DEFAULT_NEAR_RANGE = 0.0
DEFAULT_FAR_RANGE = 100.0


def build_vdf(meshes, materials, shader_name=DEFAULT_SHADER,
              near_range=DEFAULT_NEAR_RANGE, far_range=DEFAULT_FAR_RANGE):
    """Build VDF binary from processed meshes and materials.
    
    Args:
        meshes: list of ProcessedMesh
        materials: dict of name -> ObjMaterial
        shader_name: TW1 engine shader name
        near_range: rendering near range
        far_range: rendering far range
    
    Returns: bytes (complete VDF file)
    """
    w = NTFWriter()

    # AniFileName (empty string)
    w.write_chunk_string("AniFileName", "")

    # Locator (Pivot) — Child Type 5
    loc_pos = w.begin_child(CHILD_LOCATOR)
    w.write_chunk_int32("IsLocator", 1)
    w.write_chunk_vec4i("LPos", [0, 0, 0, 0])
    w.write_chunk_vec4("LDir", [0.0, 0.0, 0.0, 0.0])
    w.end_child(loc_pos)

    # Mesh Groups — one per processed mesh
    for mesh in meshes:
        mesh_pos = w.begin_child(CHILD_MESH)

        # Mesh properties
        w.write_chunk_int32("Type", 1)
        w.write_chunk_string("Name", mesh.name)
        w.write_chunk_int32("VertexFormat", 1)
        w.write_chunk_uint32("NumVertexes", len(mesh.positions))
        w.write_chunk_uint32("NumFaces", len(mesh.indices))   # NumFaces = index count!

        # Vertex buffer
        vert_data = encode_vertex_buffer(mesh)
        w.write_chunk_raw("Vertexes", vert_data)

        # Face buffer
        face_data = encode_face_buffer(mesh.indices)
        w.write_chunk_raw("Faces", face_data)

        # Shader child — Type -253
        shader_pos = w.begin_child(CHILD_SHADER)

        mat = materials.get(mesh.material_name)
        mat_name = mesh.material_name if mesh.material_name else mesh.name

        w.write_chunk_string("Name", mat_name)
        w.write_chunk_string("ShaderName", shader_name)

        # Texture slots
        tex_s0 = ""
        tex_s1 = ""
        tex_s2 = ""
        dest_color = [0.5, 0.5, 0.5, 1.0]
        spec_color = [0.5, 0.5, 0.5, 16.0]
        alpha = 1.0

        if mat:
            tex_s0 = _ensure_dds(mat.map_kd)
            tex_s1 = _ensure_dds(mat.map_bump)
            tex_s2 = _ensure_dds(mat.map_ka)
            dest_color = [mat.kd[0], mat.kd[1], mat.kd[2], mat.alpha]
            spec_color = [mat.ks[0], mat.ks[1], mat.ks[2], mat.ns]
            alpha = mat.alpha

        w.write_chunk_string("TexS0", tex_s0)
        w.write_chunk_string("TexS1", tex_s1)
        w.write_chunk_string("TexS2", tex_s2)
        w.write_chunk_vec4("SpecColor", spec_color)
        w.write_chunk_vec4("DestColor", dest_color)
        w.write_chunk_float("Alpha", alpha)
        w.write_chunk_float("NearRange", near_range)
        w.write_chunk_float("FarRange", far_range)

        w.end_child(shader_pos)   # end Shader
        w.end_child(mesh_pos)     # end Mesh Group

    return w.get_bytes()


def build_mtr(meshes, materials, shader_name=DEFAULT_SHADER,
              near_range=DEFAULT_NEAR_RANGE, far_range=DEFAULT_FAR_RANGE):
    """Build MTR binary (material reference file, also NTF format).
    Contains shader/material references as a standalone file.
    """
    w = NTFWriter()

    for mesh in meshes:
        mat = materials.get(mesh.material_name)
        mat_name = mesh.material_name if mesh.material_name else mesh.name

        shader_pos = w.begin_child(CHILD_SHADER)

        w.write_chunk_string("Name", mat_name)
        w.write_chunk_string("ShaderName", shader_name)

        tex_s0 = ""
        tex_s1 = ""
        tex_s2 = ""
        dest_color = [0.5, 0.5, 0.5, 1.0]
        spec_color = [0.5, 0.5, 0.5, 16.0]
        alpha = 1.0

        if mat:
            tex_s0 = _ensure_dds(mat.map_kd)
            tex_s1 = _ensure_dds(mat.map_bump)
            tex_s2 = _ensure_dds(mat.map_ka)
            dest_color = [mat.kd[0], mat.kd[1], mat.kd[2], mat.alpha]
            spec_color = [mat.ks[0], mat.ks[1], mat.ks[2], mat.ns]
            alpha = mat.alpha

        w.write_chunk_string("TexS0", tex_s0)
        w.write_chunk_string("TexS1", tex_s1)
        w.write_chunk_string("TexS2", tex_s2)
        w.write_chunk_vec4("SpecColor", spec_color)
        w.write_chunk_vec4("DestColor", dest_color)
        w.write_chunk_float("Alpha", alpha)
        w.write_chunk_float("NearRange", near_range)
        w.write_chunk_float("FarRange", far_range)

        w.end_child(shader_pos)

    return w.get_bytes()


def _ensure_dds(filename):
    """Make sure texture filename ends with .dds (TW1 expects DDS textures)."""
    if not filename:
        return ""
    name = filename.strip()
    # If it has a non-DDS extension, replace it
    base, ext = os.path.splitext(name)
    if ext.lower() in ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tif', '.tiff'):
        return base + ".dds"
    if not ext:
        return name + ".dds"
    return name


# ═══════════════════════════════════════════════════════════════════════════════
# NTF PARSER (for Roundtrip Validation)
# ═══════════════════════════════════════════════════════════════════════════════

class NTFNode:
    """Parsed NTF node for validation."""
    __slots__ = ('type', 'data', 'children')
    def __init__(self, node_type=None):
        self.type = node_type
        self.data = {}
        self.children = []


def parse_ntf(data):
    """Parse NTF binary. Returns root NTFNode."""
    pos = [0]
    size = len(data)

    def read_fmt(fmt):
        s = struct.calcsize(fmt)
        if pos[0] + s > size:
            raise ValueError(f"Read past end at offset {pos[0]}")
        val = struct.unpack_from('<' + fmt, data, pos[0])
        pos[0] += s
        return val[0] if len(val) == 1 else val

    def read_dstr():
        length = read_fmt('I')
        if length > 100000:
            raise ValueError(f"Unreasonable string length {length}")
        txt = data[pos[0]:pos[0]+length].decode('ascii', errors='replace')
        pos[0] += length
        return txt

    def parse_node_list(end_pos, node_type=None):
        node = NTFNode(node_type)
        while pos[0] < end_pos:
            flag = read_fmt('B')
            start = pos[0]
            node_size = read_fmt('I')
            node_end = start + node_size

            if node_end > size:
                node_end = size

            if flag == 1:
                chunk_type = read_fmt('B')
                name = read_dstr()

                if chunk_type == 17:
                    value = read_fmt('i')
                elif chunk_type == 18:
                    value = read_fmt('I')
                elif chunk_type == 19:
                    value = read_fmt('f')
                elif chunk_type == 20:
                    if name == 'LPos':
                        value = [read_fmt('i') for _ in range(4)]
                    else:
                        value = [read_fmt('f') for _ in range(4)]
                elif chunk_type == 21:
                    value = [read_fmt('f') for _ in range(16)]
                elif chunk_type == 22:
                    remaining = node_end - pos[0]
                    value = data[pos[0]:pos[0]+remaining].decode('ascii', errors='replace')
                    pos[0] = node_end
                elif chunk_type == 23:
                    remaining = node_end - pos[0]
                    value = bytes(data[pos[0]:node_end])
                    pos[0] = node_end
                else:
                    pos[0] = node_end
                    value = None

                node.data[name] = value

            elif flag == 2:
                child_type = read_fmt('i')
                child = parse_node_list(node_end, child_type)
                node.children.append(child)
            else:
                pos[0] = node_end

        return node

    header = read_fmt('I')
    if header != NTF_MAGIC:
        raise ValueError(f"Not NTF: header 0x{header:08X}, expected 0x{NTF_MAGIC:08X}")

    return parse_node_list(size)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUNDTRIP VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def validate_vdf(vdf_bytes, expected_meshes, log_func=None):
    """Validate a VDF by parsing it back and checking against expected data.
    
    Args:
        vdf_bytes: the raw VDF binary
        expected_meshes: list of ProcessedMesh (what we wrote)
        log_func: logging function
    
    Returns: (success: bool, message: str)
    """
    def log(msg):
        if log_func:
            log_func(msg)

    try:
        root = parse_ntf(vdf_bytes)
    except Exception as e:
        return False, f"Parse error: {e}"

    # Collect mesh groups from parsed tree
    parsed_groups = []

    def walk(node):
        if node.type == CHILD_MESH and 'NumVertexes' in node.data:
            parsed_groups.append(node)
        for child in node.children:
            walk(child)

    walk(root)

    # Check group count
    if len(parsed_groups) != len(expected_meshes):
        return False, (f"Group count mismatch: wrote {len(expected_meshes)}, "
                       f"read back {len(parsed_groups)}")

    # Check each group
    for i, (pg, em) in enumerate(zip(parsed_groups, expected_meshes)):
        nv = pg.data.get('NumVertexes', 0)
        nf = pg.data.get('NumFaces', 0)
        exp_nv = len(em.positions)
        exp_nf = len(em.indices)

        if nv != exp_nv:
            return False, (f"Group {i} vertex count mismatch: "
                           f"wrote {exp_nv}, read {nv}")
        if nf != exp_nf:
            return False, (f"Group {i} face index count mismatch: "
                           f"wrote {exp_nf}, read {nf}")

        # Check vertex data size
        raw_verts = pg.data.get('Vertexes', b'')
        expected_size = exp_nv * 36
        if len(raw_verts) != expected_size:
            return False, (f"Group {i} vertex data size mismatch: "
                           f"expected {expected_size}, got {len(raw_verts)}")

        # Check face data size
        raw_faces = pg.data.get('Faces', b'')
        expected_fsize = exp_nf * 2
        if len(raw_faces) != expected_fsize:
            return False, (f"Group {i} face data size mismatch: "
                           f"expected {expected_fsize}, got {len(raw_faces)}")

        # Verify VertexFormat
        vfmt = pg.data.get('VertexFormat', -1)
        if vfmt != 1:
            return False, f"Group {i} VertexFormat={vfmt}, expected 1"

    # Check locator exists
    has_locator = False
    for child in root.children:
        if child.type == CHILD_LOCATOR:
            has_locator = True
            break
    if not has_locator:
        return False, "No locator node found"

    # All good
    total_v = sum(len(m.positions) for m in expected_meshes)
    total_i = sum(len(m.indices) for m in expected_meshes)
    total_t = total_i // 3
    msg = (f"Roundtrip OK: {total_v} verts, {total_i} indices "
           f"({total_t} tris), {len(expected_meshes)} group(s)")
    return True, msg


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CONVERSION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def convert_obj_to_vdf(obj_path, output_dir, shader_name=DEFAULT_SHADER,
                       near_range=DEFAULT_NEAR_RANGE, far_range=DEFAULT_FAR_RANGE,
                       write_mtr=True, validate=True, log_func=None):
    """Convert a single OBJ file to VDF + MTR.
    
    Returns: (vdf_path, stats_dict) or raises on error.
    """
    def log(msg):
        if log_func:
            log_func(msg)

    base_name = Path(obj_path).stem

    # Step 1: Parse OBJ + MTL
    log(f"Parsing {Path(obj_path).name}...")
    obj_data = parse_obj(obj_path, log_func)

    if not obj_data.groups:
        raise ValueError(f"No geometry found in {Path(obj_path).name}")

    # Step 2: Process each group
    log("Processing vertices and tangents...")
    meshes = []
    for group in obj_data.groups:
        mesh = process_group(obj_data, group, log_func)
        meshes.append(mesh)

    # Step 3: Build VDF binary
    log("Building VDF...")
    vdf_data = build_vdf(meshes, obj_data.materials, shader_name,
                         near_range, far_range)

    # Step 4: Write VDF
    os.makedirs(output_dir, exist_ok=True)
    vdf_path = os.path.join(output_dir, f"{base_name}.vdf")
    with open(vdf_path, 'wb') as f:
        f.write(vdf_data)
    log(f"Wrote {vdf_path} ({len(vdf_data)} bytes)")

    # Step 5: Write MTR (optional)
    mtr_path = None
    if write_mtr:
        log("Building MTR...")
        mtr_data = build_mtr(meshes, obj_data.materials, shader_name,
                             near_range, far_range)
        mtr_path = os.path.join(output_dir, f"{base_name}.mtr")
        with open(mtr_path, 'wb') as f:
            f.write(mtr_data)
        log(f"Wrote {mtr_path} ({len(mtr_data)} bytes)")

    # Step 6: Roundtrip validation (optional)
    valid = False
    valid_msg = "Skipped"
    if validate:
        log("Validating (roundtrip)...")
        valid, valid_msg = validate_vdf(vdf_data, meshes, log_func)
        if valid:
            log(f"  \u2713 {valid_msg}")
        else:
            log(f"  \u2717 VALIDATION FAILED: {valid_msg}")

    # Stats
    total_verts = sum(len(m.positions) for m in meshes)
    total_tris = sum(len(m.indices) // 3 for m in meshes)
    total_indices = sum(len(m.indices) for m in meshes)

    stats = {
        'groups': len(meshes),
        'total_verts': total_verts,
        'total_tris': total_tris,
        'total_indices': total_indices,
        'vdf_size': len(vdf_data),
        'mtr_path': mtr_path,
        'valid': valid,
        'valid_msg': valid_msg,
        'materials': list(obj_data.materials.keys()),
        'textures': [],
    }

    # Collect texture names
    for mat in obj_data.materials.values():
        for tex in (mat.map_kd, mat.map_bump, mat.map_ka):
            t = _ensure_dds(tex)
            if t and t not in stats['textures']:
                stats['textures'].append(t)

    return vdf_path, stats


# ═══════════════════════════════════════════════════════════════════════════════
# GUI (Tkinter Dark Theme)
# ═══════════════════════════════════════════════════════════════════════════════

class ObjToVdfApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TW1 OBJ-to-VDF Converter v1.0")
        self.root.geometry("800x620")
        self.root.minsize(650, 500)

        self.obj_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.shader_name = tk.StringVar(value=DEFAULT_SHADER)
        self.near_range = tk.StringVar(value=str(DEFAULT_NEAR_RANGE))
        self.far_range = tk.StringVar(value=str(DEFAULT_FAR_RANGE))
        self.write_mtr = tk.BooleanVar(value=True)
        self.validate = tk.BooleanVar(value=True)

        self._setup_theme()
        self._build_ui()

    def _setup_theme(self):
        """Dark theme matching the VDF-to-OBJ converter."""
        self.BG = "#1e1e1e"
        self.FG = "#d4d4d4"
        self.BG2 = "#252526"
        self.BG3 = "#2d2d30"
        self.ACCENT = "#0e639c"
        self.GREEN = "#4ec9b0"
        self.YELLOW = "#dcdcaa"
        self.RED = "#f44747"
        self.ORANGE = "#ce9178"

        self.root.configure(bg=self.BG)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background=self.BG, foreground=self.FG,
                        fieldbackground=self.BG2)
        style.configure('TFrame', background=self.BG)
        style.configure('TLabel', background=self.BG, foreground=self.FG,
                        font=('Segoe UI', 10))
        style.configure('TButton', background=self.BG3, foreground=self.FG,
                        font=('Segoe UI', 10), borderwidth=1, relief='flat',
                        padding=(12, 6))
        style.map('TButton', background=[('active', self.ACCENT)])
        style.configure('Accent.TButton', background=self.ACCENT,
                        foreground='#ffffff')
        style.map('Accent.TButton', background=[('active', '#1177bb')])
        style.configure('TCheckbutton', background=self.BG, foreground=self.FG,
                        font=('Segoe UI', 10))
        style.configure('TLabelframe', background=self.BG, foreground=self.FG,
                        font=('Segoe UI', 10))
        style.configure('TLabelframe.Label', background=self.BG,
                        foreground=self.YELLOW, font=('Segoe UI', 10, 'bold'))
        style.configure('TCombobox', fieldbackground=self.BG2,
                        foreground=self.FG, font=('Consolas', 10))
        style.configure('Green.TLabel', background=self.BG, foreground=self.GREEN,
                        font=('Segoe UI', 10))
        style.configure('Red.TLabel', background=self.BG, foreground=self.RED,
                        font=('Segoe UI', 10))
        style.configure('Title.TLabel', background=self.BG, foreground=self.ORANGE,
                        font=('Segoe UI', 14, 'bold'))

    def _build_ui(self):
        # ── Title ──
        title_frame = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        title_frame.pack(fill='x')
        ttk.Label(title_frame, text="OBJ \u2192 VDF Converter",
                  style='Title.TLabel').pack(side='left')
        ttk.Label(title_frame, text="Two Worlds 1",
                  font=('Segoe UI', 10)).pack(side='left', padx=(10, 0))

        # ── File Selection ──
        file_frame = ttk.LabelFrame(self.root, text=" Files ", padding=10)
        file_frame.pack(fill='x', padx=10, pady=(8, 4))

        ttk.Label(file_frame, text="OBJ File:").grid(
            row=0, column=0, sticky='w', pady=2)
        inp = ttk.Entry(file_frame, textvariable=self.obj_path,
                        font=('Consolas', 10))
        inp.grid(row=0, column=1, sticky='ew', padx=(8, 4), pady=2)
        ttk.Button(file_frame, text="Browse...",
                   command=self._browse_obj).grid(row=0, column=2, pady=2)

        ttk.Label(file_frame, text="Output Folder:").grid(
            row=1, column=0, sticky='w', pady=2)
        out = ttk.Entry(file_frame, textvariable=self.output_dir,
                        font=('Consolas', 10))
        out.grid(row=1, column=1, sticky='ew', padx=(8, 4), pady=2)
        ttk.Button(file_frame, text="Browse...",
                   command=self._browse_output).grid(row=1, column=2, pady=2)

        file_frame.columnconfigure(1, weight=1)

        # ── Shader Settings ──
        settings_frame = ttk.LabelFrame(self.root, text=" Shader Settings ",
                                         padding=10)
        settings_frame.pack(fill='x', padx=10, pady=4)

        ttk.Label(settings_frame, text="ShaderName:").grid(
            row=0, column=0, sticky='w', pady=2)
        shader_combo = ttk.Combobox(settings_frame,
                                     textvariable=self.shader_name,
                                     values=KNOWN_SHADERS,
                                     font=('Consolas', 10), width=25)
        shader_combo.grid(row=0, column=1, sticky='w', padx=(8, 20), pady=2)

        ttk.Label(settings_frame, text="NearRange:").grid(
            row=0, column=2, sticky='w', pady=2)
        nr = ttk.Entry(settings_frame, textvariable=self.near_range,
                       font=('Consolas', 10), width=10)
        nr.grid(row=0, column=3, sticky='w', padx=(8, 20), pady=2)

        ttk.Label(settings_frame, text="FarRange:").grid(
            row=0, column=4, sticky='w', pady=2)
        fr = ttk.Entry(settings_frame, textvariable=self.far_range,
                       font=('Consolas', 10), width=10)
        fr.grid(row=0, column=5, sticky='w', padx=(8, 0), pady=2)

        # ── Options ──
        opt_frame = ttk.Frame(self.root, padding=(10, 4))
        opt_frame.pack(fill='x')

        ttk.Checkbutton(opt_frame, text="Write .mtr file",
                        variable=self.write_mtr).pack(side='left', padx=(0, 20))
        ttk.Checkbutton(opt_frame, text="Roundtrip validation",
                        variable=self.validate).pack(side='left')

        # ── Buttons ──
        btn_frame = ttk.Frame(self.root, padding=(10, 8))
        btn_frame.pack(fill='x')

        self.btn_convert = ttk.Button(btn_frame, text="\u25B6  Convert",
                                       style='Accent.TButton',
                                       command=self._do_convert)
        self.btn_convert.pack(side='right')

        self.status_label = ttk.Label(btn_frame, text="Ready")
        self.status_label.pack(side='left')

        # ── Log ──
        log_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        log_frame.pack(fill='both', expand=True)

        self.log_text = tk.Text(log_frame, bg=self.BG2, fg=self.FG,
                                font=('Consolas', 9), relief='flat',
                                wrap='word', insertbackground=self.FG)
        self.log_text.pack(fill='both', expand=True)
        self.log_text.configure(state='disabled')

        # Log tag colors
        self.log_text.tag_configure('ok', foreground=self.GREEN)
        self.log_text.tag_configure('err', foreground=self.RED)
        self.log_text.tag_configure('warn', foreground=self.YELLOW)

    def _log(self, msg, tag=None):
        self.log_text.configure(state='normal')
        if tag:
            self.log_text.insert('end', msg + '\n', tag)
        else:
            self.log_text.insert('end', msg + '\n')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
        self.root.update_idletasks()

    def _browse_obj(self):
        path = filedialog.askopenfilename(
            title="Select OBJ file",
            filetypes=[("OBJ Files", "*.obj"), ("All Files", "*.*")]
        )
        if path:
            self.obj_path.set(path)
            if not self.output_dir.get():
                self.output_dir.set(os.path.dirname(path))

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_dir.set(folder)

    def _do_convert(self):
        obj = self.obj_path.get()
        if not obj or not os.path.isfile(obj):
            messagebox.showwarning("No File",
                                   "Please select a valid OBJ file.")
            return

        output = self.output_dir.get()
        if not output:
            output = os.path.dirname(obj)
            self.output_dir.set(output)

        # Parse settings
        shader = self.shader_name.get().strip()
        if not shader:
            shader = DEFAULT_SHADER

        try:
            nr = float(self.near_range.get())
        except ValueError:
            nr = DEFAULT_NEAR_RANGE

        try:
            fr = float(self.far_range.get())
        except ValueError:
            fr = DEFAULT_FAR_RANGE

        # Clear log
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

        self.btn_convert.configure(state='disabled')
        self.status_label.configure(text="Converting...", style='TLabel')

        self._log("=" * 50)
        self._log(f"OBJ-to-VDF Converter v1.0")
        self._log(f"Input:  {obj}")
        self._log(f"Output: {output}")
        self._log(f"Shader: {shader}")
        self._log(f"Range:  {nr} - {fr}")
        self._log("=" * 50)

        try:
            vdf_path, stats = convert_obj_to_vdf(
                obj, output,
                shader_name=shader,
                near_range=nr,
                far_range=fr,
                write_mtr=self.write_mtr.get(),
                validate=self.validate.get(),
                log_func=self._log
            )

            self._log("")
            self._log("=" * 50)
            self._log(f"Done!", 'ok')
            self._log(f"  VDF: {vdf_path}")
            self._log(f"  {stats['total_verts']} vertices, "
                      f"{stats['total_tris']} triangles, "
                      f"{stats['groups']} group(s)")
            self._log(f"  VDF size: {stats['vdf_size']} bytes")

            if stats['mtr_path']:
                self._log(f"  MTR: {stats['mtr_path']}")
            if stats['textures']:
                self._log(f"  Textures referenced: {', '.join(stats['textures'])}")
            if stats['valid']:
                self._log(f"  Validation: {stats['valid_msg']}", 'ok')
            elif stats['valid_msg'] != "Skipped":
                self._log(f"  Validation: {stats['valid_msg']}", 'err')

            self._log("=" * 50)

            self.status_label.configure(
                text=f"OK — {stats['total_verts']}v / {stats['total_tris']}t",
                style='Green.TLabel')

        except Exception as e:
            self._log(f"\nERROR: {e}", 'err')
            self._log("=" * 50)
            self.status_label.configure(text=f"Error: {e}",
                                        style='Red.TLabel')

        self.btn_convert.configure(state='normal')


# ═══════════════════════════════════════════════════════════════════════════════
# CLI MODE
# ═══════════════════════════════════════════════════════════════════════════════

def cli_convert(obj_path, output_dir=None, shader_name=DEFAULT_SHADER):
    """Command-line conversion of a single OBJ file."""
    obj_path = Path(obj_path)

    if not obj_path.is_file():
        print(f"Error: Not found: {obj_path}")
        sys.exit(1)

    if not output_dir:
        output_dir = str(obj_path.parent)

    print(f"TW1 OBJ-to-VDF Converter v1.0")
    print(f"Input:  {obj_path}")
    print(f"Output: {output_dir}")
    print(f"Shader: {shader_name}")
    print()

    try:
        vdf_path, stats = convert_obj_to_vdf(
            str(obj_path), output_dir,
            shader_name=shader_name,
            log_func=print
        )
        print(f"\nExported: {vdf_path}")
        print(f"  {stats['total_verts']} vertices, "
              f"{stats['total_tris']} triangles, "
              f"{stats['groups']} groups")
        print(f"  VDF size: {stats['vdf_size']} bytes")
        if stats['valid']:
            print(f"  Validation: {stats['valid_msg']}")
        else:
            print(f"  Validation FAILED: {stats['valid_msg']}")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) > 1:
        # CLI mode
        input_path = sys.argv[1]
        output_dir = sys.argv[2] if len(sys.argv) > 2 else None
        shader = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_SHADER
        cli_convert(input_path, output_dir, shader)
    else:
        # GUI mode
        if not HAS_TK:
            print("Usage: python tw1_obj_to_vdf.py <input.obj> [output_folder] [shader_name]")
            print("       or run without args for GUI (requires tkinter)")
            sys.exit(1)
        root = tk.Tk()
        app = ObjToVdfApp(root)
        root.mainloop()
