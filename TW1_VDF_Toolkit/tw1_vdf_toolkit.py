#!/usr/bin/env python3
"""
TW1 VDF Toolkit v1.0 — Unified Two Worlds 1 Model Tool
=======================================================
Tab 1: VDF Import  — VDF → OBJ + MTL + Metadata JSON (single & batch)
Tab 2: OBJ Export  — OBJ → VDF + MTR (with metadata template selection)
Tab 3: Edit Data   — NTF node tree editor for VDF/metadata files

Combines: tw1_vdf_converter.py + tw1_obj_to_vdf.py + ntf_editor.py
"""

import struct
import os
import sys
import math
import json
import base64
import shutil
import tempfile
import time
import threading
from io import BytesIO
from pathlib import Path
from collections import OrderedDict
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    HAS_TK = True
except ImportError:
    HAS_TK = False

# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  THEME                                                                       ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

BG       = "#1e1e2e"
BG2      = "#252536"
BG3      = "#2d2d44"
BG4      = "#363652"
FG       = "#e0e0e0"
FG_DIM   = "#888899"
ACCENT   = "#7c6ff5"
ACCENT2  = "#9d92f8"
GREEN    = "#50c878"
YELLOW   = "#e6c84c"
RED      = "#e05050"
CYAN     = "#4cc9f0"
ORANGE   = "#f0a040"

VERSION = "1.0"
CONFIG_FILE = "toolkit_config.json"
DEFAULT_METADATA_DIR = "vdf_metadata"

NTF_EXTENSIONS = {'.mtr', '.vdf', '.chm', '.chv', '.xfn', '.hor'}

KNOWN_SHADERS = [
    "buildings_lmap", "equipment_base", "vegetation_base", "vegetation_lmap",
    "character_base", "terrain_base", "decal_base", "water_base", "particle_base",
    "character_dx", "buildings_base",
]

DEFAULT_SHADER = "buildings_lmap"
DEFAULT_NEAR_RANGE = 0.0
DEFAULT_FAR_RANGE = 100.0

# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  NTF BINARY FORMAT — Entry-Order Preserving Parser & Writer                  ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

HEADER_MAGIC = bytes([0x9f, 0x99, 0x66, 0xf6])
NTF_MAGIC_INT = 0xF666999F

CHUNK_TYPES = {
    17: "int32", 18: "uint32", 19: "float32",
    20: "float32[4]", 21: "float32[16]", 22: "text", 23: "binary",
}

CHUNK_INT32  = 17
CHUNK_UINT32 = 18
CHUNK_FLOAT  = 19
CHUNK_VEC4   = 20
CHUNK_MAT4X4 = 21
CHUNK_STRING = 22
CHUNK_RAW    = 23

CHILD_SHADER  = -253
CHILD_MESH    = -254
CHILD_LOCATOR = 5

TEXTURE_FIELDS = {"TexS0", "TexS1", "TexS2"}

NODE_TYPE_NAMES = {
    -1: "Root / AnimRef", -253: "Shader", -254: "FrameData (A)",
    -255: "FrameData (B)", -65535: "FarLOD Billboard",
}

ENTRY_CHUNK = 'chunk'
ENTRY_CHILD = 'child'


class BinaryReader:
    __slots__ = ('data', 'offset')
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
    """A single data chunk in the NTF tree."""
    __slots__ = ('chunk_type', 'name', 'value')
    def __init__(self, chunk_type, name, value):
        self.chunk_type = chunk_type; self.name = name; self.value = value
    def type_name(self):
        return CHUNK_TYPES.get(self.chunk_type, f"?{self.chunk_type}")
    def display_value(self):
        if self.chunk_type == 23: return f"[{len(self.value)} bytes]"
        if self.chunk_type == 22: return f'"{self.value}"'
        if self.chunk_type in (20, 21):
            v = self.value
            if len(v) <= 4:
                return "[" + ", ".join(f"{x:.4f}" if isinstance(x, float) else str(x) for x in v) + "]"
            return f"[{len(v)} values]"
        if self.chunk_type == 19: return f"{self.value:.6f}"
        return str(self.value)
    def clone(self):
        val = self.value
        if isinstance(val, list): val = list(val)
        elif isinstance(val, (bytes, bytearray)): val = bytes(val)
        return ChunkData(self.chunk_type, self.name, val)


class NTFNode:
    """A node in the NTF tree, preserving entry order."""
    __slots__ = ('node_type', 'entries', '_id')
    def __init__(self, node_type=None):
        self.node_type = node_type; self.entries = []; self._id = id(self)
    @property
    def chunks(self): return [d for t,d in self.entries if t == ENTRY_CHUNK]
    @property
    def children(self): return [d for t,d in self.entries if t == ENTRY_CHILD]
    def add_chunk(self, c): self.entries.append((ENTRY_CHUNK, c))
    def add_child(self, c): self.entries.append((ENTRY_CHILD, c))
    @property
    def data(self): return {c.name: c.value for c in self.chunks}
    @property
    def name(self): return self.data.get("Name", self.data.get("FontName", ""))
    def get_chunk(self, name):
        for c in self.chunks:
            if c.name == name: return c
        return None
    def set_chunk_value(self, name, value):
        for c in self.chunks:
            if c.name == name: c.value = value; return True
        return False
    @property
    def type_label(self):
        if self.node_type in NODE_TYPE_NAMES: return NODE_TYPE_NAMES[self.node_type]
        t = self.data.get("Type")
        if t == 1: return "Model"
        if t == 5: return "Locator"
        return f"Node (type={self.node_type})"
    @property
    def icon(self):
        if self.node_type == -253: return "\U0001f3a8"
        if self.node_type in (-254, -255): return "\U0001f4ca"
        if self.node_type == -1: return "\U0001f4c1"
        if self.node_type == -65535: return "\U0001f5bc"
        t = self.data.get("Type")
        if t == 1: return "\U0001f4e6"
        if t == 5: return "\U0001f4cd"
        if self.data.get("IsLocator"): return "\U0001f4cd"
        return "\U0001f4c4"


# ── Parse / Write NTF ─────────────────────────────────────────────────────────

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


def parse_ntf_bytes(data):
    """Parse NTF from raw bytes. Returns root NTFNode."""
    if data[:4] != HEADER_MAGIC:
        raise ValueError(f"Invalid NTF header: {data[:4].hex()}")
    root = parse_node_list(BinaryReader(data[4:]))
    while len(root.children) == 1 and len(root.chunks) == 0:
        root = root.children[0]
    return root


def parse_ntf_file(filepath):
    """Parse NTF from file path. Returns root NTFNode."""
    with open(filepath, 'rb') as f:
        data = f.read()
    return parse_ntf_bytes(data)


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


def ntf_to_bytes(root):
    """Serialize NTF node tree to bytes."""
    content = write_node_list(root)
    buf = BytesIO()
    buf.write(HEADER_MAGIC)
    if root.node_type is not None:
        buf.write(struct.pack('<B', 2))
        buf.write(struct.pack('<I', 4+4+len(content)))
        buf.write(struct.pack('<i', root.node_type))
    buf.write(content)
    return buf.getvalue()


def save_ntf(filepath, root):
    with open(filepath, 'wb') as f:
        f.write(ntf_to_bytes(root))


def verify_roundtrip(filepath, root):
    with open(filepath, 'rb') as f:
        orig = f.read()
    saved = ntf_to_bytes(root)
    return orig == saved


# ── NTF Tree Helpers ──────────────────────────────────────────────────────────

def find_nodes(node, pred, res=None):
    if res is None: res = []
    if pred(node): res.append(node)
    for ch in node.children: find_nodes(ch, pred, res)
    return res

def find_shaders(root): return find_nodes(root, lambda n: n.node_type == -253)

def find_mesh_nodes(root):
    """Find nodes with Type=1 and Vertexes data (actual mesh geometry)."""
    def is_mesh(n):
        d = n.data
        return d.get("Type") == 1 and "Vertexes" in d
    return find_nodes(root, is_mesh)

def find_textures(root):
    texs = []
    for s in find_shaders(root):
        for ch in s.chunks:
            if ch.name in TEXTURE_FIELDS:
                texs.append({'shader': s.name, 'slot': ch.name, 'texture': ch.value, 'chunk': ch, 'node': s})
    return texs

def count_nodes(node):
    c = 1
    for ch in node.children: c += count_nodes(ch)
    return c


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  MESH EXTRACTION (VDF → geometry data)                                       ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

class MeshData:
    """Extracted mesh with vertices, normals, UVs, faces, and material info."""
    __slots__ = ('name', 'positions', 'normals', 'uvs', 'uvs2', 'faces', 'material')
    def __init__(self):
        self.name = ""
        self.positions = []; self.normals = []; self.uvs = []; self.uvs2 = []
        self.faces = []; self.material = None

class ShaderInfo:
    __slots__ = ('name', 'shader_name', 'tex_diffuse', 'tex_bump', 'tex_lightmap',
                 'spec_color', 'dest_color', 'alpha')
    def __init__(self):
        self.name = ""; self.shader_name = ""
        self.tex_diffuse = ""; self.tex_bump = ""; self.tex_lightmap = ""
        self.spec_color = [0.5,0.5,0.5,16.0]; self.dest_color = [0.5,0.5,0.5,1.0]
        self.alpha = 1.0


def decode_vertex_format1(raw_verts, num_verts):
    """Decode VertexFormat=1: 36 bytes/vert = pos(3f)+normal(4B)+tangent(4B)+uv1(2f)+uv2(2f)"""
    positions, normals, uvs, uvs2 = [], [], [], []
    expected = num_verts * 36
    if len(raw_verts) < expected:
        raise ValueError(f"Vertex data too short: {len(raw_verts)} < {expected}")
    for i in range(num_verts):
        off = i * 36
        px, py, pz = struct.unpack_from('<3f', raw_verts, off)
        positions.append((px, py, pz))
        nb = struct.unpack_from('<4B', raw_verts, off + 12)
        normals.append(((nb[0]-128)/127.0, (nb[1]-128)/127.0, (nb[2]-128)/127.0))
        u1, v1 = struct.unpack_from('<2f', raw_verts, off + 20)
        uvs.append((u1, v1))
        u2, v2 = struct.unpack_from('<2f', raw_verts, off + 28)
        uvs2.append((u2, v2))
    return positions, normals, uvs, uvs2


def decode_vertex_generic(raw_verts, num_verts, vfmt):
    if num_verts == 0: return [], [], [], []
    stride = len(raw_verts) // num_verts
    positions, normals, uvs, uvs2 = [], [], [], []
    for i in range(num_verts):
        off = i * stride
        if stride >= 12:
            px, py, pz = struct.unpack_from('<3f', raw_verts, off)
            positions.append((px, py, pz))
        if stride >= 20:
            nb = struct.unpack_from('<4B', raw_verts, off + 12)
            normals.append(((nb[0]-128)/127.0, (nb[1]-128)/127.0, (nb[2]-128)/127.0))
        else:
            normals.append((0.0, 1.0, 0.0))
        if stride >= 28:
            uv_off = 20 if stride >= 36 else 16
            u, v = struct.unpack_from('<2f', raw_verts, off + uv_off)
            uvs.append((u, v))
        else:
            uvs.append((0.0, 0.0))
        uvs2.append((0.0, 0.0))
    return positions, normals, uvs, uvs2


def decode_faces(raw_faces, num_indices):
    faces = []
    if num_indices < 3: return faces
    actual_count = min(num_indices, len(raw_faces) // 2)
    indices = struct.unpack_from(f'<{actual_count}H', raw_faces)
    for i in range(0, actual_count - 2, 3):
        faces.append((indices[i], indices[i+1], indices[i+2]))
    return faces


def extract_shader_info(node):
    shader = ShaderInfo()
    d = node.data
    shader.name = d.get('Name', 'default')
    shader.shader_name = d.get('ShaderName', '')
    shader.tex_diffuse = d.get('TexS0', '')
    shader.tex_bump = d.get('TexS1', '')
    shader.tex_lightmap = d.get('TexS2', '')
    spec = d.get('SpecColor', [0.5,0.5,0.5,16.0])
    if isinstance(spec, list) and len(spec) >= 3: shader.spec_color = spec
    dest = d.get('DestColor', [0.5,0.5,0.5,1.0])
    if isinstance(dest, list) and len(dest) >= 3: shader.dest_color = dest
    shader.alpha = d.get('AFactor', 1.0)
    return shader


def extract_meshes_from_ntf(root_node):
    """Extract all meshes from NTF tree. Works with entry-order preserving NTFNode."""
    meshes = []
    def walk(node):
        d = node.data
        if d.get('Type') == 1 and 'Vertexes' in d:
            mesh = MeshData()
            raw_verts = d['Vertexes']
            raw_faces = d['Faces']
            num_verts = d.get('NumVertexes', 0)
            num_faces = d.get('NumFaces', 0)
            vfmt = d.get('VertexFormat', 1)
            if num_verts == 0 or num_faces == 0: return
            if vfmt == 1 and len(raw_verts) == num_verts * 36:
                mesh.positions, mesh.normals, mesh.uvs, mesh.uvs2 = decode_vertex_format1(raw_verts, num_verts)
            else:
                mesh.positions, mesh.normals, mesh.uvs, mesh.uvs2 = decode_vertex_generic(raw_verts, num_verts, vfmt)
            mesh.faces = decode_faces(raw_faces, num_faces)
            for child in node.children:
                if child.node_type == -253:
                    mesh.material = extract_shader_info(child)
                    mesh.name = mesh.material.name
                    break
            if not mesh.name:
                mesh.name = d.get('Name', f'mesh_{len(meshes)}')
            meshes.append(mesh)
        for child in node.children:
            walk(child)
    walk(root_node)
    return meshes


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  OBJ / MTL PARSER (for OBJ → VDF)                                           ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

class ObjMaterial:
    __slots__ = ('name','kd','ks','ns','alpha','map_kd','map_bump','map_ka')
    def __init__(self, name):
        self.name = name; self.kd = [0.5,0.5,0.5]; self.ks = [0.5,0.5,0.5]
        self.ns = 16.0; self.alpha = 1.0
        self.map_kd = ""; self.map_bump = ""; self.map_ka = ""

class ObjGroup:
    __slots__ = ('name', 'material_name', 'faces')
    def __init__(self, name, material_name=""):
        self.name = name; self.material_name = material_name; self.faces = []

class ObjData:
    def __init__(self):
        self.positions = []; self.normals = []; self.uvs = []
        self.groups = []; self.materials = {}


def _parse_floats(text, count):
    try:
        vals = [float(x) for x in text.split()[:count]]
        return vals if len(vals) == count else None
    except ValueError: return None

def _extract_filename(val):
    parts = val.strip().split()
    i = 0
    while i < len(parts):
        if parts[i].startswith('-'): i += 2
        else: break
    if i < len(parts):
        return os.path.basename(" ".join(parts[i:]))
    return ""

def parse_mtl(mtl_path):
    materials = {}; current = None
    if not os.path.isfile(mtl_path): return materials
    with open(mtl_path, 'r', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split(None, 1)
            if len(parts) < 1: continue
            key = parts[0].lower(); val = parts[1] if len(parts) > 1 else ""
            if key == 'newmtl': current = ObjMaterial(val.strip()); materials[current.name] = current
            elif current is None: continue
            elif key == 'kd':
                rgb = _parse_floats(val, 3)
                if rgb: current.kd = rgb
            elif key == 'ks':
                rgb = _parse_floats(val, 3)
                if rgb: current.ks = rgb
            elif key == 'ns':
                try: current.ns = float(val.strip())
                except ValueError: pass
            elif key == 'd':
                try: current.alpha = float(val.strip())
                except ValueError: pass
            elif key == 'tr':
                try: current.alpha = 1.0 - float(val.strip())
                except ValueError: pass
            elif key == 'map_kd': current.map_kd = _extract_filename(val)
            elif key in ('map_bump','bump'): current.map_bump = _extract_filename(val)
            elif key == 'map_ka': current.map_ka = _extract_filename(val)
    return materials


def _parse_face(val):
    verts = []
    for token in val.split():
        parts = token.split('/')
        try: vi = int(parts[0]) - 1
        except (ValueError, IndexError): continue
        vti = vni = -1
        if len(parts) > 1 and parts[1]:
            try: vti = int(parts[1]) - 1
            except ValueError: pass
        if len(parts) > 2 and parts[2]:
            try: vni = int(parts[2]) - 1
            except ValueError: pass
        verts.append((vi, vti, vni))
    return verts


def _merge_groups_by_material(groups):
    merged = OrderedDict()
    for g in groups:
        key = g.material_name if g.material_name else g.name
        if key in merged: merged[key].faces.extend(g.faces)
        else:
            new_g = ObjGroup(g.name, g.material_name)
            new_g.faces = list(g.faces); merged[key] = new_g
    return list(merged.values())


def parse_obj(obj_path, log_func=None):
    def log(msg):
        if log_func: log_func(msg)
    data = ObjData(); current_group = None; current_material = ""
    obj_dir = os.path.dirname(obj_path); mtl_libs = []
    with open(obj_path, 'r', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split(None, 1)
            key = parts[0]; val = parts[1] if len(parts) > 1 else ""
            if key == 'v':
                c = _parse_floats(val, 3)
                if c: data.positions.append(tuple(c))
            elif key == 'vn':
                c = _parse_floats(val, 3)
                if c: data.normals.append(tuple(c))
            elif key == 'vt':
                c = _parse_floats(val, 2)
                if c: data.uvs.append(tuple(c))
                else:
                    c = _parse_floats(val, 3)
                    if c: data.uvs.append((c[0], c[1]))
            elif key == 'mtllib':
                mp = os.path.join(obj_dir, val.strip())
                if os.path.isfile(mp): mtl_libs.append(mp)
            elif key == 'usemtl':
                current_material = val.strip()
                gn = current_group.name if current_group else "default"
                current_group = ObjGroup(gn, current_material)
                data.groups.append(current_group)
            elif key in ('g', 'o'):
                gn = val.strip() if val.strip() else "default"
                current_group = ObjGroup(gn, current_material)
                data.groups.append(current_group)
            elif key == 'f':
                if current_group is None:
                    current_group = ObjGroup("default", current_material)
                    data.groups.append(current_group)
                face_verts = _parse_face(val)
                if len(face_verts) < 3: continue
                for i in range(1, len(face_verts) - 1):
                    current_group.faces.append((face_verts[0], face_verts[i], face_verts[i+1]))
    for mp in mtl_libs:
        log(f"  Parsing {os.path.basename(mp)}...")
        data.materials.update(parse_mtl(mp))
    data.groups = [g for g in data.groups if g.faces]
    data.groups = _merge_groups_by_material(data.groups)
    log(f"  OBJ: {len(data.positions)} pos, {len(data.normals)} nrm, {len(data.uvs)} uv, {len(data.groups)} groups")
    return data


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  VERTEX PROCESSING & ENCODING (OBJ → VDF)                                   ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

class ProcessedMesh:
    __slots__ = ('name','material_name','positions','normals','tangents','uvs1','uvs2','indices')
    def __init__(self):
        self.name = ""; self.material_name = ""
        self.positions = []; self.normals = []; self.tangents = []
        self.uvs1 = []; self.uvs2 = []; self.indices = []


def process_group(obj_data, group, log_func=None):
    def log(msg):
        if log_func: log_func(msg)
    mesh = ProcessedMesh()
    mesh.name = group.name; mesh.material_name = group.material_name
    vertex_map = {}; unique_pos = []; unique_nrm = []; unique_uv = []; new_idx = []
    for tri in group.faces:
        tri_idx = []
        for vi, vti, vni in tri:
            key = (vi, vti, vni)
            if key in vertex_map:
                tri_idx.append(vertex_map[key])
            else:
                idx = len(unique_pos); vertex_map[key] = idx; tri_idx.append(idx)
                unique_pos.append(obj_data.positions[vi] if 0<=vi<len(obj_data.positions) else (0,0,0))
                unique_nrm.append(obj_data.normals[vni] if 0<=vni<len(obj_data.normals) else (0,1,0))
                unique_uv.append(obj_data.uvs[vti] if 0<=vti<len(obj_data.uvs) else (0,0))
        new_idx.extend(tri_idx)
    nv = len(unique_pos)
    if nv > 65535:
        log(f"    WARNING: '{group.name}' has {nv} verts (>65535)!")
    mesh.positions = unique_pos; mesh.normals = unique_nrm
    mesh.uvs1 = unique_uv; mesh.uvs2 = [(0,0)]*nv
    mesh.indices = new_idx
    mesh.tangents = _calculate_tangents(unique_pos, unique_nrm, unique_uv, new_idx)
    log(f"    Group '{mesh.name}': {nv} verts, {len(new_idx)//3} tris")
    return mesh


def _calculate_tangents(positions, normals, uvs, indices):
    nv = len(positions)
    tan_acc = [[0.0,0.0,0.0] for _ in range(nv)]
    for t in range(len(indices)//3):
        i0,i1,i2 = indices[t*3], indices[t*3+1], indices[t*3+2]
        p0,p1,p2 = positions[i0], positions[i1], positions[i2]
        uv0,uv1,uv2 = uvs[i0], uvs[i1], uvs[i2]
        dx1,dy1,dz1 = p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]
        dx2,dy2,dz2 = p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]
        du1,dv1 = uv1[0]-uv0[0], uv1[1]-uv0[1]
        du2,dv2 = uv2[0]-uv0[0], uv2[1]-uv0[1]
        denom = du1*dv2 - du2*dv1
        if abs(denom) < 1e-10: continue
        r = 1.0/denom
        tx = (dv2*dx1 - dv1*dx2)*r
        ty = (dv2*dy1 - dv1*dy2)*r
        tz = (dv2*dz1 - dv1*dz2)*r
        for idx in (i0,i1,i2):
            tan_acc[idx][0] += tx; tan_acc[idx][1] += ty; tan_acc[idx][2] += tz
    tangents = []
    for i in range(nv):
        n = normals[i]; t = tan_acc[i]
        dot_nt = n[0]*t[0]+n[1]*t[1]+n[2]*t[2]
        tx,ty,tz = t[0]-n[0]*dot_nt, t[1]-n[1]*dot_nt, t[2]-n[2]*dot_nt
        length = math.sqrt(tx*tx+ty*ty+tz*tz)
        if length > 1e-10: tangents.append((tx/length, ty/length, tz/length))
        else: tangents.append(_arbitrary_tangent(n))
    return tangents


def _arbitrary_tangent(normal):
    nx,ny,nz = normal
    if abs(nx)<abs(ny) and abs(nx)<abs(nz): up=(1,0,0)
    elif abs(ny)<abs(nz): up=(0,1,0)
    else: up=(0,0,1)
    tx = up[1]*nz - up[2]*ny; ty = up[2]*nx - up[0]*nz; tz = up[0]*ny - up[1]*nx
    length = math.sqrt(tx*tx+ty*ty+tz*tz)
    if length > 1e-10: return (tx/length, ty/length, tz/length)
    return (1.0, 0.0, 0.0)


def encode_ubyte4n(x,y,z,w=1.0):
    def f2b(f): return max(0, min(255, int(round(f*127.0+128.0))))
    return struct.pack('<4B', f2b(x), f2b(y), f2b(z), f2b(w))

def encode_vertex_buffer(mesh):
    buf = bytearray()
    for i in range(len(mesh.positions)):
        px,py,pz = mesh.positions[i]; nx,ny,nz = mesh.normals[i]
        tx,ty,tz = mesh.tangents[i]; u1,v1 = mesh.uvs1[i]; u2,v2 = mesh.uvs2[i]
        buf += struct.pack('<3f', px,py,pz)
        buf += encode_ubyte4n(nx,ny,nz,1.0)
        buf += encode_ubyte4n(tx,ty,tz,1.0)
        buf += struct.pack('<2f', u1,v1)
        buf += struct.pack('<2f', u2,v2)
    return bytes(buf)

def encode_face_buffer(indices):
    return struct.pack(f'<{len(indices)}H', *indices)


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  OBJ / MTL WRITER (VDF → OBJ)                                               ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

def write_obj(filepath, mesh_groups, mtl_filename):
    with open(filepath, 'w') as f:
        f.write(f"# TW1 VDF Toolkit v{VERSION}\nmtllib {mtl_filename}\n\n")
        vert_offset = 0
        for group_name, mesh in mesh_groups:
            f.write(f"g {group_name}\n")
            if mesh.material: f.write(f"usemtl {mesh.material.name}\n")
            for px,py,pz in mesh.positions: f.write(f"v {px:.6f} {py:.6f} {pz:.6f}\n")
            for u,v in mesh.uvs: f.write(f"vt {u:.6f} {v:.6f}\n")
            for nx,ny,nz in mesh.normals: f.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")
            for v0,v1,v2 in mesh.faces:
                i0,i1,i2 = v0+1+vert_offset, v1+1+vert_offset, v2+1+vert_offset
                f.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")
            vert_offset += len(mesh.positions)
            f.write("\n")

def write_mtl(filepath, materials):
    with open(filepath, 'w') as f:
        f.write(f"# TW1 VDF Toolkit v{VERSION}\n\n")
        for name, shader in materials.items():
            f.write(f"newmtl {name}\nKa 0.2 0.2 0.2\n")
            dc = shader.dest_color; f.write(f"Kd {dc[0]:.4f} {dc[1]:.4f} {dc[2]:.4f}\n")
            sc = shader.spec_color; f.write(f"Ks {sc[0]:.4f} {sc[1]:.4f} {sc[2]:.4f}\n")
            if len(sc)>3: f.write(f"Ns {sc[3]:.1f}\n")
            f.write(f"d {shader.alpha:.4f}\nillum 2\n")
            if shader.tex_diffuse: f.write(f"map_Kd {shader.tex_diffuse}\n")
            if shader.tex_bump: f.write(f"map_bump {shader.tex_bump}\n")
            if shader.tex_lightmap: f.write(f"map_Ka {shader.tex_lightmap}\n")
            f.write("\n")


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  METADATA JSON — NTF skeleton serialization                                  ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

def create_ntf_skeleton(root):
    """Create a copy of the NTF tree with Vertexes/Faces binary data stripped.
    Returns the skeleton as base64-encoded NTF bytes."""
    def clone_node(node):
        new = NTFNode(node.node_type)
        for et, data in node.entries:
            if et == ENTRY_CHUNK:
                if data.name in ('Vertexes', 'Faces'):
                    # Replace with empty bytes marker
                    new.add_chunk(ChunkData(data.chunk_type, data.name, b''))
                else:
                    new.add_chunk(data.clone())
            elif et == ENTRY_CHILD:
                new.add_child(clone_node(data))
        return new
    skeleton = clone_node(root)
    raw = ntf_to_bytes(skeleton)
    return base64.b64encode(raw).decode('ascii')


def extract_shader_details(shader_node):
    """Extract all shader properties as a JSON-friendly dict."""
    d = shader_node.data
    result = {
        "ShaderName": d.get("ShaderName", ""),
        "TexS0": d.get("TexS0", ""),
        "TexS1": d.get("TexS1", ""),
        "TexS2": d.get("TexS2", ""),
    }
    for c in shader_node.chunks:
        if c.name in result: continue
        if c.chunk_type == 22: result[c.name] = c.value
        elif c.chunk_type == 19: result[c.name] = round(c.value, 6)
        elif c.chunk_type in (17, 18): result[c.name] = c.value
        elif c.chunk_type == 20:
            result[c.name] = [round(v,6) if isinstance(v,float) else v for v in c.value]
    return result


def build_metadata_json(root, source_vdf, source_path=""):
    """Build the complete metadata JSON dict from an NTF tree."""
    meshes_info = []
    mesh_nodes = find_mesh_nodes(root)
    total_v = total_t = 0
    for mn in mesh_nodes:
        d = mn.data
        nv = d.get('NumVertexes', 0)
        nf = d.get('NumFaces', 0)
        nt = nf // 3 if nf > 0 else 0
        total_v += nv; total_t += nt
        mesh_entry = {
            "name": d.get("Name", ""),
            "vertex_count": nv,
            "face_count": nf,
            "triangle_count": nt,
            "vertex_format": d.get("VertexFormat", 1),
            "shader": {},
            "extra_properties": {}
        }
        for child in mn.children:
            if child.node_type == -253:
                mesh_entry["shader"] = extract_shader_details(child)
                mesh_entry["name"] = child.data.get("Name", mesh_entry["name"])
                break
        meshes_info.append(mesh_entry)

    # Locator info
    locator = {"IsLocator": 1, "LPos": [0,0,0,0]}
    for n in find_nodes(root, lambda n: n.data.get("IsLocator")):
        d = n.data
        locator["IsLocator"] = d.get("IsLocator", 1)
        if "LPos" in d: locator["LPos"] = d["LPos"]
        break

    ani = ""
    for n in find_nodes(root, lambda n: "AniFileName" in n.data):
        ani = n.data["AniFileName"]; break

    metadata = {
        "toolkit_version": VERSION,
        "source_vdf": source_vdf,
        "source_path": source_path,
        "created": datetime.now().isoformat(timespec='seconds'),
        "mesh_count": len(meshes_info),
        "total_vertices": total_v,
        "total_triangles": total_t,
        "meshes": meshes_info,
        "locator": locator,
        "ani_file_name": ani,
        "raw_ntf_skeleton": create_ntf_skeleton(root),
    }
    return metadata


def restore_ntf_from_metadata(metadata):
    """Restore NTF tree skeleton from metadata JSON (base64 field)."""
    raw = base64.b64decode(metadata["raw_ntf_skeleton"])
    return parse_ntf_bytes(raw)


def save_metadata(filepath, metadata):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

def load_metadata(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  VDF BUILDER (OBJ → VDF, with optional metadata template)                   ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

def _ensure_dds(filename):
    if not filename: return ""
    name = filename.strip()
    base, ext = os.path.splitext(name)
    if ext.lower() in ('.png','.jpg','.jpeg','.tga','.bmp','.tif','.tiff'):
        return base + ".dds"
    if not ext: return name + ".dds"
    return name


def build_vdf_from_scratch(meshes, materials, shader_name=DEFAULT_SHADER,
                           near_range=DEFAULT_NEAR_RANGE, far_range=DEFAULT_FAR_RANGE,
                           texture_overrides=None):
    """Build VDF binary from scratch (no metadata template)."""
    w = BytesIO()
    w.write(struct.pack('<I', NTF_MAGIC_INT))

    def write_chunk(ct, name, payload):
        name_b = name.encode('ascii', errors='replace')
        content = struct.pack('<B', ct) + struct.pack('<I', len(name_b)) + name_b + payload
        w.write(b'\x01')
        w.write(struct.pack('<I', len(content)+4))
        w.write(content)

    def begin_child(child_type):
        w.write(b'\x02')
        sp = w.tell(); w.write(struct.pack('<I', 0))
        w.write(struct.pack('<i', child_type))
        return sp

    def end_child(sp):
        end = w.tell()
        w.seek(sp); w.write(struct.pack('<I', end - sp)); w.seek(end)

    write_chunk(CHUNK_STRING, "AniFileName", b"")

    # Locator
    lp = begin_child(CHILD_LOCATOR)
    write_chunk(CHUNK_INT32, "IsLocator", struct.pack('<i', 1))
    write_chunk(CHUNK_VEC4, "LPos", struct.pack('<4i', 0,0,0,0))
    write_chunk(CHUNK_VEC4, "LDir", struct.pack('<4f', 0,0,0,0))
    end_child(lp)

    for mi, mesh in enumerate(meshes):
        mp = begin_child(CHILD_MESH)
        write_chunk(CHUNK_INT32, "Type", struct.pack('<i', 1))
        write_chunk(CHUNK_STRING, "Name", mesh.name.encode('ascii', errors='replace'))
        write_chunk(CHUNK_INT32, "VertexFormat", struct.pack('<i', 1))
        write_chunk(CHUNK_UINT32, "NumVertexes", struct.pack('<I', len(mesh.positions)))
        write_chunk(CHUNK_UINT32, "NumFaces", struct.pack('<I', len(mesh.indices)))
        write_chunk(CHUNK_RAW, "Vertexes", encode_vertex_buffer(mesh))
        write_chunk(CHUNK_RAW, "Faces", encode_face_buffer(mesh.indices))

        sp = begin_child(CHILD_SHADER)
        mat = materials.get(mesh.material_name)
        mat_name = mesh.material_name or mesh.name

        # Check for texture overrides
        ovr = texture_overrides.get(mi, {}) if texture_overrides else {}

        tex_s0 = ovr.get('TexS0', _ensure_dds(mat.map_kd) if mat else "")
        tex_s1 = ovr.get('TexS1', _ensure_dds(mat.map_bump) if mat else "")
        tex_s2 = ovr.get('TexS2', _ensure_dds(mat.map_ka) if mat else "")
        sn = ovr.get('ShaderName', shader_name)

        dest_color = [mat.kd[0],mat.kd[1],mat.kd[2],mat.alpha] if mat else [0.5,0.5,0.5,1.0]
        spec_color = [mat.ks[0],mat.ks[1],mat.ks[2],mat.ns] if mat else [0.5,0.5,0.5,16.0]
        alpha = mat.alpha if mat else 1.0

        write_chunk(CHUNK_STRING, "Name", mat_name.encode('ascii', errors='replace'))
        write_chunk(CHUNK_STRING, "ShaderName", sn.encode('ascii', errors='replace'))
        write_chunk(CHUNK_STRING, "TexS0", tex_s0.encode('ascii', errors='replace'))
        write_chunk(CHUNK_STRING, "TexS1", tex_s1.encode('ascii', errors='replace'))
        write_chunk(CHUNK_STRING, "TexS2", tex_s2.encode('ascii', errors='replace'))
        write_chunk(CHUNK_VEC4, "SpecColor", struct.pack('<4f', *spec_color))
        write_chunk(CHUNK_VEC4, "DestColor", struct.pack('<4f', *dest_color))
        write_chunk(CHUNK_FLOAT, "Alpha", struct.pack('<f', alpha))
        write_chunk(CHUNK_FLOAT, "NearRange", struct.pack('<f', near_range))
        write_chunk(CHUNK_FLOAT, "FarRange", struct.pack('<f', far_range))

        end_child(sp)
        end_child(mp)

    return w.getvalue()


def build_vdf_from_metadata(meshes, metadata, texture_overrides=None):
    """Build VDF using metadata NTF skeleton as template.
    Replaces mesh data in the skeleton with new geometry from OBJ."""
    skeleton_root = restore_ntf_from_metadata(metadata)
    mesh_nodes = find_mesh_nodes(skeleton_root)

    # Match meshes to skeleton mesh nodes (by position, or as many as we have)
    for i, pmesh in enumerate(meshes):
        if i >= len(mesh_nodes):
            break  # More OBJ groups than skeleton meshes — extras are dropped
        mn = mesh_nodes[i]

        # Update vertex/face data
        mn.set_chunk_value("NumVertexes", len(pmesh.positions))
        mn.set_chunk_value("NumFaces", len(pmesh.indices))
        mn.set_chunk_value("Vertexes", encode_vertex_buffer(pmesh))
        mn.set_chunk_value("Faces", encode_face_buffer(pmesh.indices))

        # Apply texture overrides if provided
        if texture_overrides and i in texture_overrides:
            ovr = texture_overrides[i]
            for child in mn.children:
                if child.node_type == -253:
                    for key in ('TexS0','TexS1','TexS2','ShaderName'):
                        if key in ovr and ovr[key]:
                            child.set_chunk_value(key, ovr[key])
                    break

    return ntf_to_bytes(skeleton_root)


def build_mtr(meshes, materials, shader_name=DEFAULT_SHADER,
              near_range=DEFAULT_NEAR_RANGE, far_range=DEFAULT_FAR_RANGE):
    w = BytesIO()
    w.write(struct.pack('<I', NTF_MAGIC_INT))
    def write_chunk(ct, name, payload):
        name_b = name.encode('ascii', errors='replace')
        content = struct.pack('<B', ct) + struct.pack('<I', len(name_b)) + name_b + payload
        w.write(b'\x01'); w.write(struct.pack('<I', len(content)+4)); w.write(content)
    def begin_child(child_type):
        w.write(b'\x02'); sp = w.tell(); w.write(struct.pack('<I', 0))
        w.write(struct.pack('<i', child_type)); return sp
    def end_child(sp):
        end = w.tell(); w.seek(sp); w.write(struct.pack('<I', end-sp)); w.seek(end)
    for mesh in meshes:
        mat = materials.get(mesh.material_name)
        mn = mesh.material_name or mesh.name
        sp = begin_child(CHILD_SHADER)
        write_chunk(CHUNK_STRING, "Name", mn.encode('ascii','replace'))
        write_chunk(CHUNK_STRING, "ShaderName", shader_name.encode('ascii','replace'))
        write_chunk(CHUNK_STRING, "TexS0", _ensure_dds(mat.map_kd if mat else "").encode('ascii','replace'))
        write_chunk(CHUNK_STRING, "TexS1", _ensure_dds(mat.map_bump if mat else "").encode('ascii','replace'))
        write_chunk(CHUNK_STRING, "TexS2", _ensure_dds(mat.map_ka if mat else "").encode('ascii','replace'))
        dc = [mat.kd[0],mat.kd[1],mat.kd[2],mat.alpha] if mat else [0.5,0.5,0.5,1.0]
        sc = [mat.ks[0],mat.ks[1],mat.ks[2],mat.ns] if mat else [0.5,0.5,0.5,16.0]
        write_chunk(CHUNK_VEC4, "SpecColor", struct.pack('<4f', *sc))
        write_chunk(CHUNK_VEC4, "DestColor", struct.pack('<4f', *dc))
        write_chunk(CHUNK_FLOAT, "Alpha", struct.pack('<f', mat.alpha if mat else 1.0))
        write_chunk(CHUNK_FLOAT, "NearRange", struct.pack('<f', DEFAULT_NEAR_RANGE))
        write_chunk(CHUNK_FLOAT, "FarRange", struct.pack('<f', DEFAULT_FAR_RANGE))
        end_child(sp)
    return w.getvalue()


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  TEXTURE RESOLVER                                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

def build_texture_index(textures_root):
    index = {}
    if not textures_root or not os.path.isdir(textures_root): return index
    for dirpath, _, filenames in os.walk(textures_root):
        for fname in filenames:
            if fname.upper().endswith('.DDS'):
                key = fname.upper()
                if key not in index: index[key] = os.path.join(dirpath, fname)
    return index

def find_textures_folder(input_folder):
    current = Path(input_folder).resolve()
    for _ in range(10):
        tex = current / 'Textures'
        if tex.is_dir(): return str(tex)
        parent = current.parent
        if parent == current: break
        tex = parent / 'Textures'
        if tex.is_dir(): return str(tex)
        current = parent
    return ""


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  VDF FILE SCANNER                                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

def find_vdf_pairs(folder):
    folder = Path(folder)
    all_vdf = sorted(folder.glob('*.vdf'), key=lambda p: p.name.upper())
    lod_files = {}; base_files = []
    for vdf in all_vdf:
        if vdf.stem.upper().endswith('_LOD'):
            lod_files[vdf.stem[:-4].upper()] = vdf
        else:
            base_files.append(vdf)
    pairs = []
    for base in base_files:
        lod = lod_files.get(base.stem.upper())
        pairs.append((base, lod, base.stem))
    return pairs

def find_vdf_pairs_recursive(root_folder):
    root = Path(root_folder).resolve(); all_results = []
    vdf_dirs = set()
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.upper().endswith('.VDF'):
                vdf_dirs.add(dirpath); break
    for vdf_dir in sorted(vdf_dirs):
        pairs = find_vdf_pairs(vdf_dir)
        rel = os.path.relpath(vdf_dir, root)
        if rel == '.': rel = ''
        for base, lod, display in pairs:
            disp = f"{rel}/{display}".replace('\\', '/') if rel else display
            all_results.append((base, lod, disp, rel))
    return all_results


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  CONVERSION PIPELINES                                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

def convert_vdf_to_obj(base_path, lod_path, output_dir, log_func=None,
                       tex_index=None, metadata_dir=None):
    """Convert VDF → OBJ + MTL + metadata JSON. Returns (obj_path, stats)."""
    def log(msg):
        if log_func: log_func(msg)
    base_name = Path(base_path).stem
    log(f"  Parsing {Path(base_path).name}...")
    with open(base_path, 'rb') as f:
        base_data = f.read()
    root = parse_ntf_bytes(base_data)
    base_meshes = extract_meshes_from_ntf(root)
    if not base_meshes:
        raise ValueError(f"No mesh data in {Path(base_path).name}")

    lod_meshes = []
    if lod_path and os.path.isfile(str(lod_path)):
        log(f"  Parsing {Path(str(lod_path)).name} (LOD)...")
        with open(str(lod_path), 'rb') as f:
            lod_root = parse_ntf_bytes(f.read())
        lod_meshes = extract_meshes_from_ntf(lod_root)

    mesh_groups = []; materials = {}
    for mesh in base_meshes:
        mesh_groups.append((f"{base_name}_{mesh.name}", mesh))
        if mesh.material and mesh.material.name not in materials:
            materials[mesh.material.name] = mesh.material
    for mesh in lod_meshes:
        mesh_groups.append((f"{base_name}_LOD_{mesh.name}", mesh))
        if mesh.material and mesh.material.name not in materials:
            materials[mesh.material.name] = mesh.material
    if not materials:
        default = ShaderInfo(); default.name = "default"; materials["default"] = default

    obj_path = os.path.join(output_dir, f"{base_name}.obj")
    mtl_path = os.path.join(output_dir, f"{base_name}.mtl")
    log(f"  Writing {base_name}.obj..."); write_obj(obj_path, mesh_groups, f"{base_name}.mtl")
    log(f"  Writing {base_name}.mtl..."); write_mtl(mtl_path, materials)

    # Write metadata JSON
    if metadata_dir:
        os.makedirs(metadata_dir, exist_ok=True)
        meta = build_metadata_json(root, f"{base_name}.vdf", str(base_path))
        meta_path = os.path.join(metadata_dir, f"{base_name}_vdf_metadata.json")
        save_metadata(meta_path, meta)
        log(f"  Metadata: {base_name}_vdf_metadata.json")

    # Copy textures
    all_textures = set()
    for mat in materials.values():
        for t in (mat.tex_diffuse, mat.tex_bump, mat.tex_lightmap):
            if t: all_textures.add(t)
    tex_found = tex_missing = 0; tex_missing_names = []
    if tex_index and all_textures:
        for tn in sorted(all_textures):
            dest = os.path.join(output_dir, tn)
            if os.path.exists(dest): tex_found += 1; continue
            src = tex_index.get(tn.upper())
            if src and os.path.isfile(src):
                try: shutil.copy2(src, dest); tex_found += 1
                except: tex_missing += 1; tex_missing_names.append(tn)
            else: tex_missing += 1; tex_missing_names.append(tn)

    total_verts = sum(len(m.positions) for _,m in mesh_groups)
    total_tris = sum(len(m.faces) for _,m in mesh_groups)
    stats = {
        'groups': len(mesh_groups), 'materials': len(materials),
        'total_verts': total_verts, 'total_tris': total_tris,
        'base_verts': sum(len(m.positions) for m in base_meshes),
        'base_tris': sum(len(m.faces) for m in base_meshes),
        'lod_verts': sum(len(m.positions) for m in lod_meshes),
        'lod_tris': sum(len(m.faces) for m in lod_meshes),
        'has_lod': len(lod_meshes) > 0,
        'textures': all_textures, 'tex_found': tex_found,
        'tex_missing': tex_missing, 'tex_missing_names': tex_missing_names,
    }
    return obj_path, stats


def convert_obj_to_vdf(obj_path, output_dir, shader_name=DEFAULT_SHADER,
                       near_range=DEFAULT_NEAR_RANGE, far_range=DEFAULT_FAR_RANGE,
                       write_mtr_file=True, metadata=None, texture_overrides=None,
                       log_func=None):
    """Convert OBJ → VDF + MTR. Returns (vdf_path, stats)."""
    def log(msg):
        if log_func: log_func(msg)
    base_name = Path(obj_path).stem
    log(f"Parsing {Path(obj_path).name}...")
    obj_data = parse_obj(obj_path, log_func)
    if not obj_data.groups:
        raise ValueError(f"No geometry in {Path(obj_path).name}")
    log("Processing vertices and tangents...")
    meshes = [process_group(obj_data, g, log_func) for g in obj_data.groups]

    if metadata:
        log("Building VDF from metadata template...")
        vdf_data = build_vdf_from_metadata(meshes, metadata, texture_overrides)
    else:
        log("Building VDF from scratch...")
        vdf_data = build_vdf_from_scratch(meshes, obj_data.materials, shader_name,
                                          near_range, far_range, texture_overrides)

    os.makedirs(output_dir, exist_ok=True)
    vdf_path = os.path.join(output_dir, f"{base_name}.vdf")
    with open(vdf_path, 'wb') as f:
        f.write(vdf_data)
    log(f"Wrote {vdf_path} ({len(vdf_data)} bytes)")

    mtr_path = None
    if write_mtr_file:
        mtr_data = build_mtr(meshes, obj_data.materials, shader_name, near_range, far_range)
        mtr_path = os.path.join(output_dir, f"{base_name}.mtr")
        with open(mtr_path, 'wb') as f:
            f.write(mtr_data)
        log(f"Wrote {mtr_path}")

    total_verts = sum(len(m.positions) for m in meshes)
    total_tris = sum(len(m.indices)//3 for m in meshes)
    stats = {
        'groups': len(meshes), 'total_verts': total_verts, 'total_tris': total_tris,
        'vdf_size': len(vdf_data), 'mtr_path': mtr_path,
        'textures': [], 'used_metadata': metadata is not None,
    }
    for mat in obj_data.materials.values():
        for t in (mat.map_kd, mat.map_bump, mat.map_ka):
            dt = _ensure_dds(t)
            if dt and dt not in stats['textures']: stats['textures'].append(dt)
    return vdf_path, stats


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  SETTINGS / CONFIG                                                           ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

def get_script_dir():
    return os.path.dirname(os.path.abspath(__file__))

def load_config():
    cfg_path = os.path.join(get_script_dir(), CONFIG_FILE)
    defaults = {
        "metadata_dir": os.path.join(get_script_dir(), DEFAULT_METADATA_DIR),
        "default_output_dir": "",
        "default_shader": DEFAULT_SHADER,
        "default_textures_dir": "",
        "last_import_dir": "",
        "last_export_dir": "",
    }
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, 'r') as f:
                saved = json.load(f)
            defaults.update(saved)
        except: pass
    return defaults

def save_config(cfg):
    cfg_path = os.path.join(get_script_dir(), CONFIG_FILE)
    try:
        with open(cfg_path, 'w') as f:
            json.dump(cfg, f, indent=2)
    except: pass


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  METADATA LIBRARY                                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

def scan_metadata_library(metadata_dir):
    """Scan metadata directory for all JSON files. Returns list of (filename, display_info)."""
    results = []
    if not metadata_dir or not os.path.isdir(metadata_dir):
        return results
    for f in sorted(os.listdir(metadata_dir)):
        if f.endswith('_vdf_metadata.json'):
            display_name = f.replace('_vdf_metadata.json', '')
            filepath = os.path.join(metadata_dir, f)
            # Quick peek at mesh count
            info = display_name
            try:
                with open(filepath, 'r') as fh:
                    # Read only first few lines for speed
                    data = json.load(fh)
                    mc = data.get('mesh_count', '?')
                    tv = data.get('total_vertices', '?')
                    tt = data.get('total_triangles', '?')
                    info = f"{display_name}  ({mc} meshes, {tv}v, {tt}t)"
            except:
                pass
            results.append((f, filepath, display_name, info))
    return results


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║  GUI — MAIN APPLICATION                                                      ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

if not HAS_TK:
    def main():
        print("TW1 VDF Toolkit requires tkinter for GUI mode.")
        print("Install tkinter or use CLI mode.")
        sys.exit(1)
else:
    class VDFToolkitApp:
        def __init__(self, root_tk):
            self.root = root_tk
            self.root.title(f"TW1 VDF Toolkit v{VERSION}")
            self.root.geometry("1150x780")
            self.root.minsize(950, 650)
            self.root.configure(bg=BG)

            self.config = load_config()
            self.cancel_flag = False
            self.is_running = False

            # Ensure metadata dir exists
            os.makedirs(self.config['metadata_dir'], exist_ok=True)

            self._configure_styles()
            self._create_menu()
            self._create_tabs()
            self._create_statusbar()

        # ── Styles ────────────────────────────────────────────────────────────
        def _configure_styles(self):
            style = ttk.Style(); style.theme_use('clam')
            style.configure(".", background=BG, foreground=FG, fieldbackground=BG2)
            style.configure("TFrame", background=BG)
            style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
            style.configure("TButton", background=BG3, foreground=FG, borderwidth=0,
                            padding=6, font=("Segoe UI", 10))
            style.map("TButton", background=[('active', BG4)])
            style.configure("Accent.TButton", background=ACCENT, foreground="#fff",
                            font=("Segoe UI", 10, "bold"))
            style.map("Accent.TButton", background=[('active', ACCENT2)])
            style.configure("TCheckbutton", background=BG, foreground=FG, font=("Segoe UI", 10))
            style.configure("TLabelframe", background=BG, foreground=FG)
            style.configure("TLabelframe.Label", background=BG, foreground=YELLOW,
                            font=("Segoe UI", 10, "bold"))
            style.configure("TCombobox", fieldbackground=BG2, foreground=FG,
                            font=("Consolas", 10))
            style.configure("TNotebook", background=BG, borderwidth=0)
            style.configure("TNotebook.Tab", background=BG3, foreground=FG,
                            padding=[14, 6], font=("Segoe UI", 10, "bold"))
            style.map("TNotebook.Tab",
                       background=[('selected', ACCENT)],
                       foreground=[('selected', '#fff')])
            style.configure("Treeview", background=BG2, foreground=FG,
                            fieldbackground=BG2, borderwidth=0, rowheight=24,
                            font=("Segoe UI", 10))
            style.configure("Treeview.Heading", background=BG3, foreground=FG_DIM,
                            font=("Segoe UI", 9, "bold"))
            style.map("Treeview", background=[('selected', ACCENT)],
                       foreground=[('selected', '#fff')])
            style.configure("Green.TLabel", foreground=GREEN)
            style.configure("Red.TLabel", foreground=RED)
            style.configure("TProgressbar", background=ACCENT, troughcolor=BG3)

        # ── Menu ──────────────────────────────────────────────────────────────
        def _create_menu(self):
            mb = tk.Menu(self.root, bg=BG3, fg=FG, activebackground=ACCENT,
                         activeforeground="#fff", borderwidth=0)
            mc = dict(tearoff=0, bg=BG3, fg=FG, activebackground=ACCENT, activeforeground="#fff")
            fm = tk.Menu(mb, **mc)
            fm.add_command(label="Settings...", command=self._show_settings)
            fm.add_separator()
            fm.add_command(label="Exit", command=self.root.quit)
            mb.add_cascade(label="File", menu=fm)

            hm = tk.Menu(mb, **mc)
            hm.add_command(label="About", command=self._about)
            mb.add_cascade(label="Help", menu=hm)
            self.root.config(menu=mb)

        # ── Tabs ──────────────────────────────────────────────────────────────
        def _create_tabs(self):
            self.notebook = ttk.Notebook(self.root)
            self.notebook.pack(fill="both", expand=True, padx=4, pady=(4,0))

            self.tab_import = ttk.Frame(self.notebook)
            self.tab_export = ttk.Frame(self.notebook)
            self.tab_editor = ttk.Frame(self.notebook)

            self.notebook.add(self.tab_import, text="  \U0001f4e5  VDF Import  ")
            self.notebook.add(self.tab_export, text="  \U0001f4e4  OBJ Export  ")
            self.notebook.add(self.tab_editor, text="  \u270E  Edit VDF Data  ")

            self._build_import_tab()
            self._build_export_tab()
            self._build_editor_tab()

        # ── Statusbar ─────────────────────────────────────────────────────────
        def _create_statusbar(self):
            sb = tk.Frame(self.root, bg=BG3, height=26); sb.pack(fill="x", side="bottom")
            self.status_l = tk.Label(sb, text="  Ready", bg=BG3, fg=FG_DIM,
                                     font=("Segoe UI", 9), anchor="w")
            self.status_l.pack(side="left", fill="x", expand=True)
            self.status_r = tk.Label(sb, text=f"Metadata: {os.path.basename(self.config['metadata_dir'])}",
                                     bg=BG3, fg=FG_DIM, font=("Segoe UI", 9), anchor="e")
            self.status_r.pack(side="right", padx=8)

        def _status(self, text, color=FG_DIM):
            self.status_l.configure(text=f"  {text}", fg=color)

        # ══════════════════════════════════════════════════════════════════════
        # TAB 1 — VDF IMPORT
        # ══════════════════════════════════════════════════════════════════════

        def _build_import_tab(self):
            tab = self.tab_import

            # Input/Output
            top = ttk.Frame(tab); top.pack(fill="x", padx=10, pady=(10,4))

            ttk.Label(top, text="Input (File/Folder):").grid(row=0, column=0, sticky='w', pady=2)
            self.imp_input = tk.StringVar(value=self.config.get('last_import_dir', ''))
            inp = ttk.Entry(top, textvariable=self.imp_input, font=("Consolas", 10))
            inp.grid(row=0, column=1, sticky='ew', padx=(8,4), pady=2)
            bf = tk.Frame(top, bg=BG); bf.grid(row=0, column=2, pady=2)
            ttk.Button(bf, text="File", command=self._imp_browse_file).pack(side="left", padx=1)
            ttk.Button(bf, text="Folder", command=self._imp_browse_folder).pack(side="left", padx=1)

            ttk.Label(top, text="Output Folder:").grid(row=1, column=0, sticky='w', pady=2)
            self.imp_output = tk.StringVar()
            ttk.Entry(top, textvariable=self.imp_output, font=("Consolas", 10)).grid(
                row=1, column=1, sticky='ew', padx=(8,4), pady=2)
            ttk.Button(top, text="Browse", command=self._imp_browse_output).grid(row=1, column=2, pady=2)

            ttk.Label(top, text="Textures Folder:").grid(row=2, column=0, sticky='w', pady=2)
            self.imp_texdir = tk.StringVar(value=self.config.get('default_textures_dir', ''))
            ttk.Entry(top, textvariable=self.imp_texdir, font=("Consolas", 10)).grid(
                row=2, column=1, sticky='ew', padx=(8,4), pady=2)
            ttk.Button(top, text="Browse", command=self._imp_browse_tex).grid(row=2, column=2, pady=2)
            top.columnconfigure(1, weight=1)

            # File list
            mid = ttk.Frame(tab); mid.pack(fill="both", expand=True, padx=10, pady=4)
            cols = ('file', 'lod', 'status')
            self.imp_tree = ttk.Treeview(mid, columns=cols, show='headings', selectmode='extended')
            self.imp_tree.heading('file', text='VDF File')
            self.imp_tree.heading('lod', text='LOD')
            self.imp_tree.heading('status', text='Status')
            self.imp_tree.column('file', width=450, minwidth=250)
            self.imp_tree.column('lod', width=60, anchor='center')
            self.imp_tree.column('status', width=400, minwidth=150)
            vsb = ttk.Scrollbar(mid, orient='vertical', command=self.imp_tree.yview)
            self.imp_tree.configure(yscrollcommand=vsb.set)
            self.imp_tree.pack(side='left', fill='both', expand=True)
            vsb.pack(side='right', fill='y')

            # Buttons + Progress
            btn = ttk.Frame(tab); btn.pack(fill="x", padx=10, pady=4)
            self.imp_progress = ttk.Progressbar(btn, mode='determinate', style="TProgressbar")
            self.imp_progress.pack(fill="x", pady=(0,4))
            self.imp_progress_label = ttk.Label(btn, text="")
            self.imp_progress_label.pack(side="left")

            self.imp_btn_cancel = ttk.Button(btn, text="Cancel", command=self._imp_cancel,
                                              state='disabled')
            self.imp_btn_cancel.pack(side="right", padx=4)
            self.imp_btn_convert = ttk.Button(btn, text="\u25B6  Import All",
                                               style="Accent.TButton", command=self._imp_start)
            self.imp_btn_convert.pack(side="right", padx=4)

            # Log
            log_f = ttk.Frame(tab); log_f.pack(fill="x", padx=10, pady=(0,10))
            self.imp_log = tk.Text(log_f, height=6, bg=BG2, fg=FG, font=("Consolas", 9),
                                    relief="flat", wrap="word", insertbackground=FG)
            self.imp_log.pack(fill="x"); self.imp_log.configure(state='disabled')

            self.imp_pairs = []

        def _imp_log(self, msg):
            self.imp_log.configure(state='normal')
            self.imp_log.insert('end', msg + '\n')
            self.imp_log.see('end')
            self.imp_log.configure(state='disabled')

        def _imp_browse_file(self):
            p = filedialog.askopenfilename(title="Select VDF File",
                filetypes=[("VDF Files", "*.vdf"), ("All", "*.*")])
            if p:
                self.imp_input.set(p)
                if not self.imp_output.get():
                    self.imp_output.set(os.path.join(os.path.dirname(p), "OBJ_Export"))
                if not self.imp_texdir.get():
                    tex = find_textures_folder(os.path.dirname(p))
                    if tex: self.imp_texdir.set(tex)
                self._imp_scan()

        def _imp_browse_folder(self):
            p = filedialog.askdirectory(title="Select folder with VDF files")
            if p:
                self.imp_input.set(p)
                if not self.imp_output.get():
                    self.imp_output.set(os.path.join(p, "OBJ_Export"))
                if not self.imp_texdir.get():
                    tex = find_textures_folder(p)
                    if tex: self.imp_texdir.set(tex)
                self._imp_scan()

        def _imp_browse_output(self):
            p = filedialog.askdirectory(title="Select output folder")
            if p: self.imp_output.set(p)

        def _imp_browse_tex(self):
            p = filedialog.askdirectory(title="Select Textures folder")
            if p: self.imp_texdir.set(p)

        def _imp_scan(self):
            self.imp_tree.delete(*self.imp_tree.get_children())
            self.imp_pairs = []
            inp = self.imp_input.get()
            if not inp: return

            if os.path.isfile(inp):
                base = Path(inp)
                lod = base.parent / f"{base.stem}_LOD{base.suffix}"
                lod = lod if lod.exists() else None
                self.imp_pairs = [(base, lod, base.stem, '')]
            elif os.path.isdir(inp):
                self.imp_pairs = find_vdf_pairs_recursive(inp)

            for base, lod, display, rel in self.imp_pairs:
                self.imp_tree.insert('', 'end', values=(display, "Yes" if lod else "\u2014", "Ready"))
            self._imp_log(f"Found {len(self.imp_pairs)} VDF model(s)")
            self._status(f"{len(self.imp_pairs)} files found", GREEN)

        def _imp_cancel(self):
            self.cancel_flag = True

        def _imp_start(self):
            if not self.imp_pairs:
                self._imp_scan()
                if not self.imp_pairs:
                    messagebox.showwarning("No Files", "No VDF files found."); return
            output = self.imp_output.get()
            if not output:
                messagebox.showwarning("No Output", "Select an output folder."); return

            self.cancel_flag = False
            self.imp_btn_convert.configure(state='disabled')
            self.imp_btn_cancel.configure(state='normal')
            self.imp_progress['value'] = 0
            self.imp_progress['maximum'] = len(self.imp_pairs)

            # Clear log
            self.imp_log.configure(state='normal')
            self.imp_log.delete('1.0', 'end')
            self.imp_log.configure(state='disabled')

            # Build texture index
            tex_dir = self.imp_texdir.get()
            tex_index = {}
            if tex_dir and os.path.isdir(tex_dir):
                self._imp_log(f"Scanning textures in {tex_dir}...")
                tex_index = build_texture_index(tex_dir)
                self._imp_log(f"  Found {len(tex_index)} DDS textures")

            metadata_dir = self.config['metadata_dir']
            self.config['last_import_dir'] = self.imp_input.get()
            save_config(self.config)

            # Start batch in after() loop for GUI responsiveness
            self._imp_batch(0, tex_index, metadata_dir, output, 0, 0)

        def _imp_batch(self, idx, tex_index, metadata_dir, output, success, errors):
            if self.cancel_flag or idx >= len(self.imp_pairs):
                # Done
                self.imp_btn_convert.configure(state='normal')
                self.imp_btn_cancel.configure(state='disabled')
                self._imp_log(f"\n{'='*50}")
                if self.cancel_flag:
                    self._imp_log(f"Cancelled at {idx}/{len(self.imp_pairs)}")
                    self._status(f"Cancelled: {success} OK, {errors} errors", YELLOW)
                else:
                    self._imp_log(f"Done! {success} converted, {errors} errors")
                    self._status(f"Done: {success} OK, {errors} errors", GREEN)
                self._imp_log(f"{'='*50}")
                return

            base, lod, name, rel_dir = self.imp_pairs[idx]
            items = self.imp_tree.get_children()
            item = items[idx] if idx < len(items) else None
            if item: self.imp_tree.set(item, 'status', "Converting...")

            self.imp_progress['value'] = idx + 1
            self.imp_progress_label.configure(
                text=f"{name} — {idx+1}/{len(self.imp_pairs)} ({(idx+1)*100//len(self.imp_pairs)}%)")
            self.root.update_idletasks()

            sub_output = os.path.join(output, rel_dir) if rel_dir else output
            os.makedirs(sub_output, exist_ok=True)

            try:
                self._imp_log(f"\n[{name}]")
                _, stats = convert_vdf_to_obj(
                    str(base), str(lod) if lod else None, sub_output,
                    self._imp_log, tex_index=tex_index, metadata_dir=metadata_dir)

                lod_info = f" +LOD({stats['lod_verts']}v)" if stats['has_lod'] else ""
                status = f"OK — {stats['base_verts']}v / {stats['base_tris']}t{lod_info}"
                if item: self.imp_tree.set(item, 'status', status)
                success += 1
            except Exception as e:
                if item: self.imp_tree.set(item, 'status', f"ERROR: {e}")
                self._imp_log(f"  ERROR: {e}")
                errors += 1

            # Schedule next file
            self.root.after(1, self._imp_batch, idx+1, tex_index, metadata_dir, output, success, errors)

        # ══════════════════════════════════════════════════════════════════════
        # TAB 2 — OBJ EXPORT (OBJ → VDF)
        # ══════════════════════════════════════════════════════════════════════

        def _build_export_tab(self):
            tab = self.tab_export

            # File selection
            top = ttk.LabelFrame(tab, text=" Files ", padding=10)
            top.pack(fill="x", padx=10, pady=(10,4))

            ttk.Label(top, text="OBJ File:").grid(row=0, column=0, sticky='w', pady=2)
            self.exp_obj = tk.StringVar()
            ttk.Entry(top, textvariable=self.exp_obj, font=("Consolas", 10)).grid(
                row=0, column=1, sticky='ew', padx=(8,4), pady=2)
            ttk.Button(top, text="Browse", command=self._exp_browse_obj).grid(row=0, column=2, pady=2)

            ttk.Label(top, text="Output Folder:").grid(row=1, column=0, sticky='w', pady=2)
            self.exp_output = tk.StringVar()
            ttk.Entry(top, textvariable=self.exp_output, font=("Consolas", 10)).grid(
                row=1, column=1, sticky='ew', padx=(8,4), pady=2)
            ttk.Button(top, text="Browse", command=self._exp_browse_output).grid(row=1, column=2, pady=2)
            top.columnconfigure(1, weight=1)

            # Metadata selection with search
            meta_frame = ttk.LabelFrame(tab, text=" VDF Metadata Template ", padding=10)
            meta_frame.pack(fill="x", padx=10, pady=4)

            ttk.Label(meta_frame, text="Template:").grid(row=0, column=0, sticky='w', pady=2)

            # Searchable combobox
            self.exp_meta_var = tk.StringVar()
            self.exp_meta_combo = ttk.Combobox(meta_frame, textvariable=self.exp_meta_var,
                                                font=("Consolas", 10), width=60)
            self.exp_meta_combo.grid(row=0, column=1, sticky='ew', padx=(8,4), pady=2)
            self.exp_meta_combo.bind('<KeyRelease>', self._exp_filter_metadata)
            self.exp_meta_combo.bind('<<ComboboxSelected>>', self._exp_metadata_selected)
            ttk.Button(meta_frame, text="Refresh", command=self._exp_refresh_metadata).grid(
                row=0, column=2, pady=2)
            ttk.Label(meta_frame, text="(Type to search. Leave empty for defaults.)",
                      foreground=FG_DIM, font=("Segoe UI", 9)).grid(row=1, column=1, sticky='w', padx=8)
            meta_frame.columnconfigure(1, weight=1)

            self.exp_metadata_lib = []
            self.exp_metadata_full = []
            self._exp_refresh_metadata()

            # Shader settings + Texture fields (scrollable)
            self.exp_mesh_frame_outer = ttk.LabelFrame(tab, text=" Shader & Textures ", padding=4)
            self.exp_mesh_frame_outer.pack(fill="both", expand=True, padx=10, pady=4)

            # Canvas for scrollable mesh panels
            self.exp_canvas = tk.Canvas(self.exp_mesh_frame_outer, bg=BG, highlightthickness=0)
            self.exp_vsb = ttk.Scrollbar(self.exp_mesh_frame_outer, orient="vertical",
                                          command=self.exp_canvas.yview)
            self.exp_mesh_frame = tk.Frame(self.exp_canvas, bg=BG)
            self.exp_mesh_frame.bind("<Configure>",
                lambda e: self.exp_canvas.configure(scrollregion=self.exp_canvas.bbox("all")))
            self.exp_canvas.create_window((0,0), window=self.exp_mesh_frame, anchor="nw", tags="inn")
            self.exp_canvas.bind("<Configure>",
                lambda e: self.exp_canvas.itemconfig("inn", width=e.width-20))
            self.exp_canvas.configure(yscrollcommand=self.exp_vsb.set)
            self.exp_vsb.pack(side="right", fill="y")
            self.exp_canvas.pack(fill="both", expand=True)
            self.exp_canvas.bind_all("<MouseWheel>",
                lambda e: self.exp_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

            self.exp_mesh_panels = []  # List of dicts with StringVars for each mesh

            # Default: show one generic panel
            self._exp_show_default_panels()

            # Options + Convert
            opt = ttk.Frame(tab); opt.pack(fill="x", padx=10, pady=4)
            self.exp_write_mtr = tk.BooleanVar(value=True)
            ttk.Checkbutton(opt, text="Write .mtr file", variable=self.exp_write_mtr).pack(side="left")

            self.exp_btn_convert = ttk.Button(opt, text="\u25B6  Convert to VDF",
                                               style="Accent.TButton", command=self._exp_convert)
            self.exp_btn_convert.pack(side="right")

            # Log
            log_f = ttk.Frame(tab); log_f.pack(fill="x", padx=10, pady=(0,10))
            self.exp_log = tk.Text(log_f, height=5, bg=BG2, fg=FG, font=("Consolas", 9),
                                    relief="flat", wrap="word", insertbackground=FG)
            self.exp_log.pack(fill="x"); self.exp_log.configure(state='disabled')

        def _exp_log(self, msg):
            self.exp_log.configure(state='normal')
            self.exp_log.insert('end', msg + '\n'); self.exp_log.see('end')
            self.exp_log.configure(state='disabled')

        def _exp_browse_obj(self):
            p = filedialog.askopenfilename(title="Select OBJ File",
                filetypes=[("OBJ Files", "*.obj"), ("All", "*.*")])
            if p:
                self.exp_obj.set(p)
                if not self.exp_output.get():
                    self.exp_output.set(os.path.dirname(p))

        def _exp_browse_output(self):
            p = filedialog.askdirectory(title="Select output folder")
            if p: self.exp_output.set(p)

        def _exp_refresh_metadata(self):
            """Refresh the metadata library dropdown."""
            lib = scan_metadata_library(self.config['metadata_dir'])
            self.exp_metadata_lib = lib
            self.exp_metadata_full = [item[3] for item in lib]  # display info strings
            self.exp_meta_combo['values'] = self.exp_metadata_full

        def _exp_filter_metadata(self, event=None):
            """Live filter the metadata dropdown as user types."""
            query = self.exp_meta_var.get().lower()
            if not query:
                self.exp_meta_combo['values'] = self.exp_metadata_full
                return
            filtered = [s for s in self.exp_metadata_full if query in s.lower()]
            self.exp_meta_combo['values'] = filtered

        def _exp_metadata_selected(self, event=None):
            """When user selects a metadata from dropdown, load and show mesh panels."""
            sel = self.exp_meta_var.get()
            if not sel: return
            # Find matching metadata
            meta = None
            for fname, fpath, dname, info in self.exp_metadata_lib:
                if info == sel or dname == sel.split('  ')[0]:
                    try:
                        meta = load_metadata(fpath)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to load metadata:\n{e}")
                        return
                    break
            if meta:
                self._exp_show_metadata_panels(meta)
            else:
                self._exp_show_default_panels()

        def _exp_show_default_panels(self):
            """Show a single default shader panel."""
            for w in self.exp_mesh_frame.winfo_children(): w.destroy()
            self.exp_mesh_panels = []

            panel = self._create_mesh_panel(self.exp_mesh_frame, 0, "Default Mesh",
                                             DEFAULT_SHADER, "", "", "")
            self.exp_mesh_panels.append(panel)

        def _exp_show_metadata_panels(self, meta):
            """Show mesh panels from loaded metadata, pre-filled with shader info."""
            for w in self.exp_mesh_frame.winfo_children(): w.destroy()
            self.exp_mesh_panels = []

            meshes = meta.get('meshes', [])
            if not meshes:
                self._exp_show_default_panels()
                return

            for i, mesh_info in enumerate(meshes):
                shader = mesh_info.get('shader', {})
                name = mesh_info.get('name', f'Mesh {i}')
                sn = shader.get('ShaderName', DEFAULT_SHADER)
                t0 = shader.get('TexS0', '')
                t1 = shader.get('TexS1', '')
                t2 = shader.get('TexS2', '')
                panel = self._create_mesh_panel(self.exp_mesh_frame, i, name, sn, t0, t1, t2)
                self.exp_mesh_panels.append(panel)

        def _create_mesh_panel(self, parent, index, name, shader, tex0, tex1, tex2):
            """Create a single mesh shader/texture panel. Returns dict of StringVars."""
            frame = tk.Frame(parent, bg=BG2, padx=10, pady=8)
            frame.pack(fill="x", pady=3, padx=2)

            tk.Label(frame, text=f"Mesh {index}: {name}", font=("Segoe UI", 10, "bold"),
                     bg=BG2, fg=CYAN).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0,4))

            vars_dict = {}
            row = 1
            for label, key, default in [
                ("Shader:", "ShaderName", shader),
                ("TexS0 (Diffuse):", "TexS0", tex0),
                ("TexS1 (Normal):", "TexS1", tex1),
                ("TexS2 (Lightmap):", "TexS2", tex2),
            ]:
                tk.Label(frame, text=label, font=("Segoe UI", 9), bg=BG2, fg=FG_DIM,
                         width=16, anchor='w').grid(row=row, column=0, sticky='w', pady=1)
                sv = tk.StringVar(value=default)
                vars_dict[key] = sv

                if key == "ShaderName":
                    cb = ttk.Combobox(frame, textvariable=sv, values=KNOWN_SHADERS,
                                       font=("Consolas", 9), width=25)
                    cb.grid(row=row, column=1, columnspan=2, sticky='ew', padx=4, pady=1)
                else:
                    e = tk.Entry(frame, textvariable=sv, font=("Consolas", 9),
                                 bg=BG3, fg=FG, insertbackground=FG, bd=0, relief="flat")
                    e.grid(row=row, column=1, sticky='ew', padx=4, pady=1)
                    btn = tk.Button(frame, text="...",
                                    command=lambda sv=sv: self._exp_browse_texture(sv),
                                    bg=BG3, fg=FG, bd=0, padx=6, cursor="hand2",
                                    font=("Segoe UI", 8))
                    btn.grid(row=row, column=2, pady=1)
                row += 1

            frame.columnconfigure(1, weight=1)
            return vars_dict

        def _exp_browse_texture(self, string_var):
            p = filedialog.askopenfilename(title="Select DDS Texture",
                filetypes=[("DDS Textures", "*.dds"), ("All", "*.*")])
            if p: string_var.set(os.path.basename(p))

        def _exp_convert(self):
            obj = self.exp_obj.get()
            if not obj or not os.path.isfile(obj):
                messagebox.showwarning("No File", "Select a valid OBJ file."); return
            output = self.exp_output.get()
            if not output: output = os.path.dirname(obj); self.exp_output.set(output)

            # Clear log
            self.exp_log.configure(state='normal')
            self.exp_log.delete('1.0', 'end')
            self.exp_log.configure(state='disabled')

            # Collect texture overrides from panels
            texture_overrides = {}
            for i, panel in enumerate(self.exp_mesh_panels):
                ovr = {}
                for key in ('ShaderName', 'TexS0', 'TexS1', 'TexS2'):
                    val = panel[key].get().strip()
                    if val: ovr[key] = val
                if ovr: texture_overrides[i] = ovr

            # Load metadata if selected
            metadata = None
            sel = self.exp_meta_var.get()
            if sel:
                for fname, fpath, dname, info in self.exp_metadata_lib:
                    if info == sel or dname == sel.split('  ')[0]:
                        try:
                            metadata = load_metadata(fpath)
                        except: pass
                        break

            # Get shader from first panel
            shader_name = DEFAULT_SHADER
            if self.exp_mesh_panels:
                sn = self.exp_mesh_panels[0].get('ShaderName', tk.StringVar()).get()
                if sn: shader_name = sn

            self.exp_btn_convert.configure(state='disabled')

            try:
                vdf_path, stats = convert_obj_to_vdf(
                    obj, output, shader_name=shader_name,
                    write_mtr_file=self.exp_write_mtr.get(),
                    metadata=metadata, texture_overrides=texture_overrides,
                    log_func=self._exp_log)

                self._exp_log(f"\n{'='*50}")
                self._exp_log(f"Done! {vdf_path}")
                self._exp_log(f"  {stats['total_verts']}v, {stats['total_tris']}t, {stats['groups']} groups")
                self._exp_log(f"  VDF: {stats['vdf_size']} bytes")
                if stats['used_metadata']:
                    self._exp_log(f"  Used metadata template")
                self._exp_log(f"{'='*50}")
                self._status(f"OK — {stats['total_verts']}v / {stats['total_tris']}t", GREEN)

            except Exception as e:
                self._exp_log(f"\nERROR: {e}")
                self._status(f"Error: {e}", RED)

            self.exp_btn_convert.configure(state='normal')

        # ══════════════════════════════════════════════════════════════════════
        # TAB 3 — EDIT VDF DATA (NTF Editor)
        # ══════════════════════════════════════════════════════════════════════

        def _build_editor_tab(self):
            tab = self.tab_editor

            # Toolbar
            tb = tk.Frame(tab, bg=BG3, pady=4, padx=8); tb.pack(fill="x")
            for label, cmd in [
                ("\U0001f4c2 Open", self._ed_open),
                ("\U0001f4be Save", self._ed_save),
                ("\U0001f4be Save As", self._ed_save_as),
                (None, None),
                ("\U0001f3a8 Textures", self._ed_show_textures),
                ("\U0001f4ca Stats", self._ed_show_stats),
                (None, None),
                ("\U0001fa78 Transplant", self._ed_transplant),
                ("\u2714 Verify", self._ed_verify),
            ]:
                if label is None:
                    tk.Frame(tb, bg=FG_DIM, width=1, height=24).pack(side="left", padx=6, fill="y")
                    continue
                b = tk.Button(tb, text=label, command=cmd, bg=BG3, fg=FG,
                              activebackground=BG4, activeforeground=FG, bd=0, padx=10, pady=3,
                              font=("Segoe UI", 9), cursor="hand2", relief="flat")
                b.pack(side="left", padx=2)
                b.bind("<Enter>", lambda e, b=b: b.configure(bg=BG4))
                b.bind("<Leave>", lambda e, b=b: b.configure(bg=BG3))

            # Paned: Tree | Detail
            self.ed_paned = tk.PanedWindow(tab, orient="horizontal", bg=BG,
                                            sashwidth=3, sashrelief="flat")
            self.ed_paned.pack(fill="both", expand=True, padx=4, pady=4)

            # Left: tree
            left = tk.Frame(self.ed_paned, bg=BG2)
            self.ed_paned.add(left, width=400, minsize=250)

            sf = tk.Frame(left, bg=BG2, pady=4, padx=4); sf.pack(fill="x")
            tk.Label(sf, text="\U0001f50d", bg=BG2, fg=FG_DIM, font=("Segoe UI", 10)).pack(side="left", padx=(4,2))
            self.ed_search_var = tk.StringVar()
            self.ed_search_var.trace_add("write", self._ed_on_search)
            tk.Entry(sf, textvariable=self.ed_search_var, bg=BG3, fg=FG, insertbackground=FG,
                     bd=0, font=("Segoe UI", 10), relief="flat").pack(
                     side="left", fill="x", expand=True, padx=4, ipady=3)

            tf = tk.Frame(left, bg=BG2); tf.pack(fill="both", expand=True)
            self.ed_tree = ttk.Treeview(tf, show="tree", selectmode="browse")
            ed_vsb = ttk.Scrollbar(tf, orient="vertical", command=self.ed_tree.yview)
            self.ed_tree.configure(yscrollcommand=ed_vsb.set)
            ed_vsb.pack(side="right", fill="y")
            self.ed_tree.pack(fill="both", expand=True)
            self.ed_tree.bind("<<TreeviewSelect>>", self._ed_on_select)
            self.ed_tree.bind("<Double-1>", self._ed_on_dblclick)

            # Right: detail
            self.ed_detail = tk.Frame(self.ed_paned, bg=BG)
            self.ed_paned.add(self.ed_detail, minsize=350)

            self.ed_filepath = None
            self.ed_ntf_root = None
            self.ed_modified = False
            self.ed_node_map = {}
            self._ed_show_welcome()

        def _ed_show_welcome(self):
            for w in self.ed_detail.winfo_children(): w.destroy()
            f = tk.Frame(self.ed_detail, bg=BG); f.place(relx=0.5, rely=0.5, anchor="center")
            tk.Label(f, text="\U0001f4c4", font=("Segoe UI", 48), bg=BG, fg=ACCENT).pack()
            tk.Label(f, text="NTF Editor", font=("Segoe UI", 20, "bold"), bg=BG, fg=FG).pack(pady=(8,2))
            tk.Label(f, text="Open a .vdf, .mtr, or _vdf_metadata.json",
                     font=("Segoe UI", 11), bg=BG, fg=FG_DIM).pack()
            btn = tk.Button(f, text="\U0001f4c2  Open File", command=self._ed_open,
                            bg=ACCENT, fg="#fff", activebackground=ACCENT2, bd=0,
                            padx=24, pady=8, font=("Segoe UI", 11, "bold"), cursor="hand2")
            btn.pack(pady=16)

        def _ed_open(self):
            exts = ' '.join(f'*{e}' for e in NTF_EXTENSIONS)
            p = filedialog.askopenfilename(title="Open NTF / Metadata File", filetypes=[
                ("NTF + Metadata", f"{exts} *_vdf_metadata.json"),
                ("VDF Models", "*.vdf"), ("Metadata JSON", "*_vdf_metadata.json"),
                ("All NTF", exts), ("All", "*.*")])
            if p: self._ed_load(p)

        def _ed_load(self, path):
            try:
                if path.endswith('.json'):
                    meta = load_metadata(path)
                    self.ed_ntf_root = restore_ntf_from_metadata(meta)
                else:
                    self.ed_ntf_root = parse_ntf_file(path)
                self.ed_filepath = path; self.ed_modified = False
                self._ed_populate_tree()
                nn = count_nodes(self.ed_ntf_root); ns = len(find_shaders(self.ed_ntf_root))
                self._status(f"Editor: {nn} nodes, {ns} shaders", GREEN)
                self._ed_show_loaded()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load:\n{e}")

        def _ed_show_loaded(self):
            for w in self.ed_detail.winfo_children(): w.destroy()
            f = tk.Frame(self.ed_detail, bg=BG, padx=20, pady=20); f.pack(fill="both", expand=True)
            tk.Label(f, text="\u2714  File Loaded", font=("Segoe UI", 16, "bold"),
                     bg=BG, fg=GREEN).pack(anchor="w", pady=(0,12))
            info = tk.Frame(f, bg=BG2, padx=16, pady=12); info.pack(fill="x")
            for label, val in [
                ("File:", os.path.basename(self.ed_filepath)),
                ("Nodes:", str(count_nodes(self.ed_ntf_root))),
                ("Shaders:", str(len(find_shaders(self.ed_ntf_root)))),
                ("Textures:", str(len(find_textures(self.ed_ntf_root)))),
            ]:
                r = tk.Frame(info, bg=BG2); r.pack(fill="x", pady=2)
                tk.Label(r, text=label, font=("Segoe UI", 10, "bold"), bg=BG2, fg=FG_DIM,
                         width=10, anchor="w").pack(side="left")
                tk.Label(r, text=val, font=("Segoe UI", 10), bg=BG2, fg=FG).pack(side="left")
            tk.Label(f, text="\nSelect a node in the tree to view details.",
                     font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack(anchor="w")

        def _ed_save(self):
            if not self.ed_ntf_root or not self.ed_filepath: return self._ed_save_as()
            try:
                if self.ed_filepath.endswith('.json'):
                    # Re-serialize to JSON by rebuilding metadata
                    raw = ntf_to_bytes(self.ed_ntf_root)
                    b64 = base64.b64encode(raw).decode('ascii')
                    meta = load_metadata(self.ed_filepath)
                    meta['raw_ntf_skeleton'] = b64
                    save_metadata(self.ed_filepath, meta)
                else:
                    save_ntf(self.ed_filepath, self.ed_ntf_root)
                self.ed_modified = False
                self._status(f"Saved: {os.path.basename(self.ed_filepath)}", GREEN)
            except Exception as e:
                messagebox.showerror("Error", f"Save failed:\n{e}")

        def _ed_save_as(self):
            if not self.ed_ntf_root: return
            ext = os.path.splitext(self.ed_filepath)[1] if self.ed_filepath else ".vdf"
            p = filedialog.asksaveasfilename(title="Save As", defaultextension=ext,
                filetypes=[("VDF", "*.vdf"), ("MTR", "*.mtr"), ("All NTF", "*.vdf *.mtr *.chm"), ("All", "*.*")])
            if p:
                self.ed_filepath = p; self._ed_save()

        def _ed_populate_tree(self):
            self.ed_tree.delete(*self.ed_tree.get_children()); self.ed_node_map.clear()
            if self.ed_ntf_root:
                self._ed_add_node("", self.ed_ntf_root)
                for item in self.ed_tree.get_children():
                    self.ed_tree.item(item, open=True)
                    for child in self.ed_tree.get_children(item):
                        self.ed_tree.item(child, open=True)

        def _ed_add_node(self, parent, node):
            label = f"{node.icon}  {node.type_label}"
            if node.name: label += f'  "{node.name}"'
            tags = ()
            if node.node_type == -253: tags = ("shader",)
            elif node.data.get("IsLocator"): tags = ("locator",)
            iid = self.ed_tree.insert(parent, "end", text=label, tags=tags)
            self.ed_node_map[iid] = node
            for child in node.children: self._ed_add_node(iid, child)
            self.ed_tree.tag_configure("shader", foreground=YELLOW)
            self.ed_tree.tag_configure("locator", foreground=CYAN)

        def _ed_on_select(self, e=None):
            sel = self.ed_tree.selection()
            if sel:
                node = self.ed_node_map.get(sel[0])
                if node: self._ed_show_detail(node)

        def _ed_on_dblclick(self, e=None):
            sel = self.ed_tree.selection()
            if sel:
                node = self.ed_node_map.get(sel[0])
                if node:
                    for ch in node.chunks:
                        if ch.chunk_type in (17,18,19,22):
                            self._ed_edit_chunk(ch, node); return

        def _ed_on_search(self, *args):
            q = self.ed_search_var.get().lower().strip()
            if not q or not self.ed_ntf_root: return
            for iid, node in self.ed_node_map.items():
                if q in node.name.lower() or q in node.type_label.lower():
                    self.ed_tree.see(iid); self.ed_tree.selection_set(iid); return
                for ch in node.chunks:
                    if ch.chunk_type == 22 and q in str(ch.value).lower():
                        self.ed_tree.see(iid); self.ed_tree.selection_set(iid); return

        def _ed_show_detail(self, node):
            for w in self.ed_detail.winfo_children(): w.destroy()
            hdr = tk.Frame(self.ed_detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
            tk.Label(hdr, text=f"{node.icon}  {node.type_label}",
                     font=("Segoe UI", 13, "bold"), bg=BG3, fg=FG).pack(anchor="w")
            if node.name:
                tk.Label(hdr, text=f'"{node.name}"', font=("Segoe UI", 11),
                         bg=BG3, fg=ACCENT2).pack(anchor="w")
            tk.Label(hdr, text=f"Type: {node.node_type}  |  Chunks: {len(node.chunks)}  |  Children: {len(node.children)}",
                     font=("Segoe UI", 9), bg=BG3, fg=FG_DIM).pack(anchor="w", pady=(4,0))

            if not node.chunks:
                tk.Label(self.ed_detail, text="No chunks.", font=("Segoe UI", 10),
                         bg=BG, fg=FG_DIM).pack(pady=20)
                return

            tf = tk.Frame(self.ed_detail, bg=BG); tf.pack(fill="both", expand=True, padx=8, pady=8)
            # Header row
            ch = tk.Frame(tf, bg=BG3, padx=8, pady=4); ch.pack(fill="x")
            tk.Label(ch, text="Field", font=("Segoe UI", 9, "bold"), bg=BG3, fg=FG_DIM,
                     width=18, anchor="w").pack(side="left")
            tk.Label(ch, text="Type", font=("Segoe UI", 9, "bold"), bg=BG3, fg=FG_DIM,
                     width=12, anchor="w").pack(side="left")
            tk.Label(ch, text="Value", font=("Segoe UI", 9, "bold"), bg=BG3, fg=FG_DIM,
                     anchor="w").pack(side="left", fill="x", expand=True)

            # Scrollable chunk list
            canvas = tk.Canvas(tf, bg=BG, highlightthickness=0)
            vsb = ttk.Scrollbar(tf, orient="vertical", command=canvas.yview)
            cf = tk.Frame(canvas, bg=BG)
            cf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0,0), window=cf, anchor="nw", tags="inn")
            canvas.bind("<Configure>", lambda e: canvas.itemconfig("inn", width=e.width-20))
            canvas.configure(yscrollcommand=vsb.set)
            vsb.pack(side="right", fill="y"); canvas.pack(fill="both", expand=True)

            for i, chunk in enumerate(node.chunks):
                bgc = BG2 if i%2==0 else BG
                row = tk.Frame(cf, bg=bgc, padx=8, pady=4); row.pack(fill="x")
                nc = GREEN if chunk.name in TEXTURE_FIELDS else (YELLOW if chunk.chunk_type==22 else FG)
                tk.Label(row, text=chunk.name, font=("Consolas", 10), bg=bgc, fg=nc,
                         width=18, anchor="w").pack(side="left")
                tk.Label(row, text=chunk.type_name(), font=("Consolas", 9), bg=bgc, fg=FG_DIM,
                         width=12, anchor="w").pack(side="left")
                tk.Label(row, text=chunk.display_value(), font=("Consolas", 10), bg=bgc, fg=nc,
                         anchor="w").pack(side="left", fill="x", expand=True)
                if chunk.chunk_type in (17,18,19,22):
                    eb = tk.Button(row, text="\u270E",
                                   command=lambda c=chunk, n=node: self._ed_edit_chunk(c, n),
                                   bg=bgc, fg=ACCENT, activebackground=BG4, bd=0, padx=4,
                                   cursor="hand2", relief="flat", font=("Segoe UI", 10))
                    eb.pack(side="right", padx=4)

        def _ed_edit_chunk(self, chunk, node):
            dlg = tk.Toplevel(self.root); dlg.title(f"Edit: {chunk.name}")
            dlg.geometry("450x200"); dlg.configure(bg=BG)
            dlg.transient(self.root); dlg.grab_set()
            tk.Label(dlg, text=f"Edit: {chunk.name}", font=("Segoe UI", 13, "bold"),
                     bg=BG, fg=FG).pack(pady=(16,4))
            tk.Label(dlg, text=f"Type: {chunk.type_name()}", font=("Segoe UI", 9),
                     bg=BG, fg=FG_DIM).pack()
            ef = tk.Frame(dlg, bg=BG, padx=20, pady=12); ef.pack(fill="x")
            tk.Label(ef, text="Value:", font=("Segoe UI", 10), bg=BG, fg=FG).pack(anchor="w")
            dv = chunk.value if chunk.chunk_type == 22 else str(chunk.value)
            entry = tk.Entry(ef, font=("Consolas", 11), bg=BG3, fg=FG, insertbackground=FG,
                              bd=0, relief="flat")
            entry.pack(fill="x", ipady=4, pady=4)
            entry.insert(0, dv); entry.select_range(0, "end"); entry.focus_set()
            def apply():
                nv = entry.get()
                try:
                    if chunk.chunk_type == 17: nv = int(nv)
                    elif chunk.chunk_type == 18: nv = int(nv)
                    elif chunk.chunk_type == 19: nv = float(nv)
                except ValueError as e:
                    messagebox.showerror("Error", f"Invalid: {e}", parent=dlg); return
                chunk.value = nv; self.ed_modified = True; dlg.destroy()
                self._ed_show_detail(node)
                self._status(f"Changed {chunk.name} = {repr(nv)}", YELLOW)
            bf = tk.Frame(dlg, bg=BG); bf.pack(pady=8)
            tk.Button(bf, text="Cancel", command=dlg.destroy, bg=BG3, fg=FG, bd=0,
                      padx=16, pady=4, font=("Segoe UI", 10), cursor="hand2").pack(side="left", padx=4)
            tk.Button(bf, text="Apply", command=apply, bg=ACCENT, fg="#fff", bd=0,
                      padx=16, pady=4, font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="left", padx=4)
            entry.bind("<Return>", lambda e: apply())
            entry.bind("<Escape>", lambda e: dlg.destroy())

        def _ed_show_textures(self):
            if not self.ed_ntf_root: return
            texs = find_textures(self.ed_ntf_root)
            for w in self.ed_detail.winfo_children(): w.destroy()
            hdr = tk.Frame(self.ed_detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
            tk.Label(hdr, text="\U0001f3a8  Texture References", font=("Segoe UI", 14, "bold"),
                     bg=BG3, fg=FG).pack(anchor="w")
            tk.Label(hdr, text=f"{len(texs)} texture(s)", font=("Segoe UI", 10),
                     bg=BG3, fg=GREEN if texs else YELLOW).pack(anchor="w")
            ct = tk.Frame(self.ed_detail, bg=BG, padx=12, pady=8); ct.pack(fill="both", expand=True)
            for tex in texs:
                card = tk.Frame(ct, bg=BG2, padx=12, pady=8); card.pack(fill="x", pady=3)
                tk.Label(card, text=f"\U0001f3a8  \"{tex['shader']}\"",
                         font=("Segoe UI", 11, "bold"), bg=BG2, fg=FG).pack(anchor="w")
                row = tk.Frame(card, bg=BG2); row.pack(fill="x")
                tk.Label(row, text=f"  {tex['slot']}:", font=("Consolas", 10),
                         bg=BG2, fg=CYAN, width=8, anchor="w").pack(side="left")
                tk.Label(row, text=f"\"{tex['texture']}\"", font=("Consolas", 10),
                         bg=BG2, fg=GREEN).pack(side="left")
                tk.Button(row, text="\u270E",
                          command=lambda t=tex: self._ed_edit_chunk(t['chunk'], t['node']),
                          bg=BG4, fg=ACCENT, bd=0, padx=8, cursor="hand2",
                          font=("Segoe UI", 9)).pack(side="right")

        def _ed_show_stats(self):
            if not self.ed_ntf_root: return
            for w in self.ed_detail.winfo_children(): w.destroy()
            nodes = find_nodes(self.ed_ntf_root, lambda n: True)
            types = {}; fields = set(); bsz = 0
            for n in nodes:
                types[n.node_type] = types.get(n.node_type, 0)+1
                for ch in n.chunks:
                    fields.add(ch.name)
                    if ch.chunk_type == 23: bsz += len(ch.value)
            hdr = tk.Frame(self.ed_detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
            tk.Label(hdr, text="\U0001f4ca  Statistics", font=("Segoe UI", 14, "bold"),
                     bg=BG3, fg=FG).pack(anchor="w")
            ct = tk.Frame(self.ed_detail, bg=BG, padx=16, pady=12); ct.pack(fill="both", expand=True)
            cards = tk.Frame(ct, bg=BG); cards.pack(fill="x", pady=(0,12))
            for label, val, color in [
                ("Nodes", str(len(nodes)), CYAN), ("Binary", f"{bsz:,}b", YELLOW),
                ("Fields", str(len(fields)), GREEN), ("Shaders", str(len(find_shaders(self.ed_ntf_root))), ORANGE),
            ]:
                c = tk.Frame(cards, bg=BG2, padx=12, pady=8); c.pack(side="left", padx=4, fill="x", expand=True)
                tk.Label(c, text=val, font=("Segoe UI", 16, "bold"), bg=BG2, fg=color).pack()
                tk.Label(c, text=label, font=("Segoe UI", 9), bg=BG2, fg=FG_DIM).pack()

        def _ed_transplant(self):
            if not self.ed_ntf_root:
                messagebox.showinfo("Transplant", "Load a file first."); return
            orig_path = filedialog.askopenfilename(title="Select ORIGINAL VDF (shader source)",
                filetypes=[("VDF", "*.vdf"), ("All NTF", "*.vdf *.mtr"), ("All", "*.*")])
            if not orig_path: return
            try:
                orig_root = parse_ntf_file(orig_path)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load original:\n{e}"); return

            orig_shaders = find_shaders(orig_root)
            edit_shaders = find_shaders(self.ed_ntf_root)
            if not orig_shaders or not edit_shaders:
                messagebox.showinfo("Transplant", "No shaders found in one of the files."); return

            # Match and transplant
            used = set(); count = 0
            for es in edit_shaders:
                for oi, os_ in enumerate(orig_shaders):
                    if oi not in used and es.name == os_.name:
                        es.entries = [(ENTRY_CHUNK, c.clone()) for c in os_.chunks]
                        used.add(oi); count += 1; break
            if count:
                self.ed_modified = True; self._ed_populate_tree()
                self._status(f"Transplanted {count} shader(s)", GREEN)
                messagebox.showinfo("Done", f"Transplanted {count} shader(s).\nDon't forget to save!")
            else:
                self._status("No shaders matched", YELLOW)

        def _ed_verify(self):
            if not self.ed_ntf_root or not self.ed_filepath: return
            if self.ed_filepath.endswith('.json'):
                messagebox.showinfo("Verify", "Verify is only available for NTF binary files."); return
            if verify_roundtrip(self.ed_filepath, self.ed_ntf_root):
                self._status("Verify: PASS — Byte-identical!", GREEN)
                messagebox.showinfo("Verify", "\u2714 Byte-identical round-trip!")
            else:
                self._status("Verify: FAIL", RED)
                messagebox.showwarning("Verify", "\u2718 Round-trip mismatch!")

        # ── Settings ──────────────────────────────────────────────────────────
        def _show_settings(self):
            dlg = tk.Toplevel(self.root); dlg.title("Settings")
            dlg.geometry("550x250"); dlg.configure(bg=BG)
            dlg.transient(self.root); dlg.grab_set()

            tk.Label(dlg, text="Settings", font=("Segoe UI", 14, "bold"),
                     bg=BG, fg=FG).pack(pady=(16,8))

            f = tk.Frame(dlg, bg=BG, padx=20); f.pack(fill="x")

            tk.Label(f, text="Metadata Folder:", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
                row=0, column=0, sticky='w', pady=4)
            meta_var = tk.StringVar(value=self.config['metadata_dir'])
            tk.Entry(f, textvariable=meta_var, font=("Consolas", 10), bg=BG3, fg=FG,
                     insertbackground=FG, bd=0).grid(row=0, column=1, sticky='ew', padx=4, pady=4)
            tk.Button(f, text="...", command=lambda: meta_var.set(
                filedialog.askdirectory(title="Select Metadata Folder") or meta_var.get()),
                bg=BG3, fg=FG, bd=0, padx=8).grid(row=0, column=2, pady=4)

            tk.Label(f, text="Default Shader:", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
                row=1, column=0, sticky='w', pady=4)
            shader_var = tk.StringVar(value=self.config.get('default_shader', DEFAULT_SHADER))
            ttk.Combobox(f, textvariable=shader_var, values=KNOWN_SHADERS,
                         font=("Consolas", 10)).grid(row=1, column=1, sticky='ew', padx=4, pady=4)

            tk.Label(f, text="Textures Folder:", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
                row=2, column=0, sticky='w', pady=4)
            tex_var = tk.StringVar(value=self.config.get('default_textures_dir', ''))
            tk.Entry(f, textvariable=tex_var, font=("Consolas", 10), bg=BG3, fg=FG,
                     insertbackground=FG, bd=0).grid(row=2, column=1, sticky='ew', padx=4, pady=4)
            tk.Button(f, text="...", command=lambda: tex_var.set(
                filedialog.askdirectory(title="Select Textures Folder") or tex_var.get()),
                bg=BG3, fg=FG, bd=0, padx=8).grid(row=2, column=2, pady=4)

            f.columnconfigure(1, weight=1)

            def save():
                self.config['metadata_dir'] = meta_var.get()
                self.config['default_shader'] = shader_var.get()
                self.config['default_textures_dir'] = tex_var.get()
                os.makedirs(self.config['metadata_dir'], exist_ok=True)
                save_config(self.config)
                self.status_r.configure(text=f"Metadata: {os.path.basename(self.config['metadata_dir'])}")
                self._exp_refresh_metadata()
                dlg.destroy()
                self._status("Settings saved", GREEN)

            bf = tk.Frame(dlg, bg=BG); bf.pack(pady=16)
            tk.Button(bf, text="Cancel", command=dlg.destroy, bg=BG3, fg=FG, bd=0,
                      padx=16, pady=6, font=("Segoe UI", 10)).pack(side="left", padx=4)
            tk.Button(bf, text="Save", command=save, bg=ACCENT, fg="#fff", bd=0,
                      padx=16, pady=6, font=("Segoe UI", 10, "bold")).pack(side="left", padx=4)

        def _about(self):
            messagebox.showinfo("About",
                f"TW1 VDF Toolkit v{VERSION}\n\n"
                "Unified Two Worlds 1 Model Tool\n\n"
                "Tab 1: VDF \u2192 OBJ + Metadata\n"
                "Tab 2: OBJ \u2192 VDF (with templates)\n"
                "Tab 3: NTF Node Editor\n\n"
                "Formats: .vdf .mtr .chm .chv .xfn .hor")


    def main():
        root = tk.Tk()
        app = VDFToolkitApp(root)
        root.mainloop()


if __name__ == '__main__':
    main()
