#!/usr/bin/env python3
"""TW1 VDF-to-OBJ Converter v1.1 — Converts Two Worlds 1 .vdf model files to .obj + .mtl"""

import struct
import os
import sys
import shutil
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    HAS_TK = True
except ImportError:
    HAS_TK = False

# ─── NTF Parser (BugLord Node Tree Format) ────────────────────────────────────

NTF_MAGIC = 0xF666999F

class NTFNode:
    __slots__ = ('type', 'data', 'children')
    def __init__(self, node_type=None):
        self.type = node_type
        self.data = {}
        self.children = []

def parse_ntf(data):
    """Parse NTF binary file (header 0x9F9966F6). Returns root NTFNode."""
    pos = [0]
    size = len(data)
    
    def read_fmt(fmt):
        s = struct.calcsize(fmt)
        if pos[0] + s > size:
            raise ValueError(f"Read past end: offset {pos[0]}, need {s}, have {size}")
        val = struct.unpack_from('<' + fmt, data, pos[0])
        pos[0] += s
        return val[0] if len(val) == 1 else val
    
    def read_dstr():
        length = read_fmt('I')
        if length > 10000:
            raise ValueError(f"Unreasonable string length {length} at offset {pos[0]}")
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
            
            if flag == 1:  # Chunk (data leaf)
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
                
            elif flag == 2:  # Child node list
                child_type = read_fmt('i')
                child = parse_node_list(node_end, child_type)
                node.children.append(child)
            else:
                pos[0] = node_end
        
        return node
    
    header = read_fmt('I')
    if header != NTF_MAGIC:
        raise ValueError(f"Not a valid NTF file (header: 0x{header:08X}, expected 0x{NTF_MAGIC:08X})")
    
    return parse_node_list(size)

# ─── Mesh Extraction ──────────────────────────────────────────────────────────

class MeshData:
    """Extracted mesh with vertices, normals, UVs, faces, and material info."""
    def __init__(self):
        self.name = ""
        self.positions = []   # [(x,y,z), ...]
        self.normals = []     # [(nx,ny,nz), ...]
        self.uvs = []         # [(u,v), ...]
        self.faces = []       # [(v0,v1,v2), ...] 0-indexed
        self.material = None  # ShaderInfo

class ShaderInfo:
    """Material/shader data from VDF shader node."""
    def __init__(self):
        self.name = ""
        self.shader_name = ""
        self.tex_diffuse = ""   # TexS0
        self.tex_bump = ""      # TexS1
        self.tex_lightmap = ""  # TexS2
        self.spec_color = [0.5, 0.5, 0.5, 16.0]
        self.dest_color = [0.5, 0.5, 0.5, 1.0]
        self.alpha = 1.0

def decode_vertex_format1(raw_verts, num_verts):
    """Decode VertexFormat=1: 36 bytes/vert = pos(3f) + normal(4B) + tangent(4B) + uv1(2f) + uv2(2f)"""
    positions = []
    normals = []
    uvs = []
    
    expected = num_verts * 36
    if len(raw_verts) < expected:
        raise ValueError(f"Vertex data too short: {len(raw_verts)} < {expected}")
    
    for i in range(num_verts):
        off = i * 36
        px, py, pz = struct.unpack_from('<3f', raw_verts, off)
        positions.append((px, py, pz))
        
        # Normal as UBYTE4N: (byte - 128) / 127
        nb = struct.unpack_from('<4B', raw_verts, off + 12)
        nx = (nb[0] - 128) / 127.0
        ny = (nb[1] - 128) / 127.0
        nz = (nb[2] - 128) / 127.0
        normals.append((nx, ny, nz))
        
        # UV1 (Diffuse/Bump texture coords)
        u, v = struct.unpack_from('<2f', raw_verts, off + 20)
        uvs.append((u, v))
    
    return positions, normals, uvs

def decode_vertex_generic(raw_verts, num_verts, vfmt):
    """Try to decode unknown vertex formats by stride detection."""
    if num_verts == 0:
        return [], [], []
    
    stride = len(raw_verts) // num_verts
    positions = []
    normals = []
    uvs = []
    
    for i in range(num_verts):
        off = i * stride
        # At minimum, first 12 bytes should be position
        if stride >= 12:
            px, py, pz = struct.unpack_from('<3f', raw_verts, off)
            positions.append((px, py, pz))
        
        # Try normal at offset 12 if stride >= 20
        if stride >= 20:
            nb = struct.unpack_from('<4B', raw_verts, off + 12)
            nx = (nb[0] - 128) / 127.0
            ny = (nb[1] - 128) / 127.0
            nz = (nb[2] - 128) / 127.0
            normals.append((nx, ny, nz))
        else:
            normals.append((0.0, 1.0, 0.0))
        
        # Try UV after normal+tangent (offset 20) or after normal (offset 16)
        if stride >= 28:
            uv_off = 20 if stride >= 36 else 16
            u, v = struct.unpack_from('<2f', raw_verts, off + uv_off)
            uvs.append((u, v))
        else:
            uvs.append((0.0, 0.0))
    
    return positions, normals, uvs

def decode_faces(raw_faces, num_indices):
    """Decode face indices as uint16 triangles."""
    faces = []
    if num_indices < 3:
        return faces
    
    actual_count = min(num_indices, len(raw_faces) // 2)
    indices = struct.unpack_from(f'<{actual_count}H', raw_faces)
    
    for i in range(0, actual_count - 2, 3):
        faces.append((indices[i], indices[i+1], indices[i+2]))
    
    return faces

def extract_shader(node):
    """Extract shader/material info from a shader child node (type -253)."""
    shader = ShaderInfo()
    shader.name = node.data.get('Name', 'default')
    shader.shader_name = node.data.get('ShaderName', '')
    shader.tex_diffuse = node.data.get('TexS0', '')
    shader.tex_bump = node.data.get('TexS1', '')
    shader.tex_lightmap = node.data.get('TexS2', '')
    
    spec = node.data.get('SpecColor', [0.5, 0.5, 0.5, 16.0])
    if isinstance(spec, list) and len(spec) >= 3:
        shader.spec_color = spec
    
    dest = node.data.get('DestColor', [0.5, 0.5, 0.5, 1.0])
    if isinstance(dest, list) and len(dest) >= 3:
        shader.dest_color = dest
    
    shader.alpha = node.data.get('AFactor', 1.0)
    return shader

def extract_meshes_from_vdf(root_node):
    """Recursively find all mesh nodes and extract geometry + materials."""
    meshes = []
    
    def walk(node):
        # Check if this node has mesh data (Type=1 with Vertexes)
        if node.data.get('Type') == 1 and 'Vertexes' in node.data:
            mesh = MeshData()
            
            raw_verts = node.data['Vertexes']
            raw_faces = node.data['Faces']
            num_verts = node.data.get('NumVertexes', 0)
            num_faces = node.data.get('NumFaces', 0)
            vfmt = node.data.get('VertexFormat', 1)
            
            if num_verts == 0 or num_faces == 0:
                return
            
            # Decode vertices
            if vfmt == 1 and len(raw_verts) == num_verts * 36:
                mesh.positions, mesh.normals, mesh.uvs = decode_vertex_format1(raw_verts, num_verts)
            else:
                mesh.positions, mesh.normals, mesh.uvs = decode_vertex_generic(raw_verts, num_verts, vfmt)
            
            # Decode faces
            mesh.faces = decode_faces(raw_faces, num_faces)
            
            # Find shader child (type -253)
            for child in node.children:
                if child.type == -253:
                    mesh.material = extract_shader(child)
                    mesh.name = mesh.material.name
                    break
            
            if not mesh.name:
                mesh.name = node.data.get('Name', f'mesh_{len(meshes)}')
            
            meshes.append(mesh)
        
        for child in node.children:
            walk(child)
    
    walk(root_node)
    return meshes

def get_ani_filename(root_node):
    """Get AniFileName reference from VDF root."""
    def walk(node):
        if 'AniFileName' in node.data:
            return node.data['AniFileName']
        for c in node.children:
            r = walk(c)
            if r: return r
        return None
    return walk(root_node)

# ─── Texture Resolver ─────────────────────────────────────────────────────────

def build_texture_index(textures_root):
    """Recursively scan a Textures folder, build filename -> full_path lookup.
    Case-insensitive keys. Returns dict.
    """
    index = {}
    if not textures_root or not os.path.isdir(textures_root):
        return index
    
    for dirpath, dirnames, filenames in os.walk(textures_root):
        for fname in filenames:
            if fname.upper().endswith('.DDS'):
                key = fname.upper()
                if key not in index:  # first match wins
                    index[key] = os.path.join(dirpath, fname)
    
    return index

def find_textures_folder(input_folder):
    """Auto-detect WDFiles Textures folder from a model folder path.
    Walks up looking for a sibling 'Textures' folder next to 'Models'.
    e.g. WDFiles/Graphics/Models/FURNITURE/BAR/BAR_02 -> WDFiles/Graphics/Textures
    """
    current = Path(input_folder).resolve()
    
    for _ in range(10):  # max 10 levels up
        # Check if sibling 'Textures' exists
        tex_dir = current / 'Textures'
        if tex_dir.is_dir():
            return str(tex_dir)
        
        # Check if parent has 'Textures' sibling
        parent = current.parent
        if parent == current:
            break
        
        tex_dir = parent / 'Textures'
        if tex_dir.is_dir():
            return str(tex_dir)
        
        current = parent
    
    return ""

def copy_textures(texture_names, tex_index, output_dir, log_func=None):
    """Copy referenced DDS textures to output folder. Returns (found, missing) counts."""
    found = 0
    missing = 0
    
    def log(msg):
        if log_func:
            log_func(msg)
    
    for tex_name in texture_names:
        if not tex_name:
            continue
        
        dest = os.path.join(output_dir, tex_name)
        if os.path.exists(dest):
            found += 1
            continue
        
        src = tex_index.get(tex_name.upper())
        if src and os.path.isfile(src):
            try:
                shutil.copy2(src, dest)
                found += 1
            except Exception as e:
                log(f"    WARN: Could not copy {tex_name}: {e}")
                missing += 1
        else:
            missing += 1
    
    return found, missing

# ─── OBJ/MTL Export ───────────────────────────────────────────────────────────

def write_obj(filepath, mesh_groups, mtl_filename):
    """Write .obj file with multiple mesh groups.
    mesh_groups: [(group_name, MeshData), ...]
    """
    with open(filepath, 'w') as f:
        f.write(f"# TW1 VDF-to-OBJ Converter v1.1\n")
        f.write(f"# Source: Two Worlds 1 (Reality Pump)\n")
        f.write(f"mtllib {mtl_filename}\n\n")
        
        vert_offset = 0
        
        for group_name, mesh in mesh_groups:
            f.write(f"g {group_name}\n")
            if mesh.material:
                f.write(f"usemtl {mesh.material.name}\n")
            
            # Vertices
            for px, py, pz in mesh.positions:
                f.write(f"v {px:.6f} {py:.6f} {pz:.6f}\n")
            
            # Texture coordinates
            for u, v in mesh.uvs:
                f.write(f"vt {u:.6f} {v:.6f}\n")
            
            # Normals
            for nx, ny, nz in mesh.normals:
                f.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")
            
            # Faces (OBJ is 1-indexed)
            for v0, v1, v2 in mesh.faces:
                i0 = v0 + 1 + vert_offset
                i1 = v1 + 1 + vert_offset
                i2 = v2 + 1 + vert_offset
                f.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")
            
            vert_offset += len(mesh.positions)
            f.write("\n")

def write_mtl(filepath, materials):
    """Write .mtl file. materials: dict of name -> ShaderInfo"""
    with open(filepath, 'w') as f:
        f.write(f"# TW1 VDF-to-OBJ Converter v1.1\n\n")
        
        for name, shader in materials.items():
            f.write(f"newmtl {name}\n")
            
            # Ambient
            f.write(f"Ka 0.2 0.2 0.2\n")
            
            # Diffuse from DestColor
            dc = shader.dest_color
            f.write(f"Kd {dc[0]:.4f} {dc[1]:.4f} {dc[2]:.4f}\n")
            
            # Specular
            sc = shader.spec_color
            f.write(f"Ks {sc[0]:.4f} {sc[1]:.4f} {sc[2]:.4f}\n")
            
            # Specular exponent (from SpecColor.w)
            if len(sc) > 3:
                f.write(f"Ns {sc[3]:.1f}\n")
            
            # Alpha
            f.write(f"d {shader.alpha:.4f}\n")
            
            # Illumination model
            f.write(f"illum 2\n")
            
            # Diffuse texture
            if shader.tex_diffuse:
                f.write(f"map_Kd {shader.tex_diffuse}\n")
            
            # Bump/Normal map
            if shader.tex_bump:
                f.write(f"map_bump {shader.tex_bump}\n")
            
            # Lightmap as ambient occlusion map
            if shader.tex_lightmap:
                f.write(f"map_Ka {shader.tex_lightmap}\n")
            
            f.write(f"\n")

# ─── Conversion Logic ─────────────────────────────────────────────────────────

def find_vdf_pairs(folder):
    """Scan folder for VDF files and pair them: base + LOD.
    Returns: [(base_path, lod_path_or_None, display_name), ...]
    """
    folder = Path(folder)
    all_vdf = sorted(folder.glob('*.vdf'), key=lambda p: p.name.upper())
    # Also check files without extension that are VDF
    for f in sorted(folder.iterdir()):
        if f.suffix == '' and f.is_file():
            try:
                with open(f, 'rb') as fh:
                    magic = struct.unpack('<I', fh.read(4))[0]
                if magic == NTF_MAGIC:
                    all_vdf.append(f)
            except:
                pass
    
    # Separate base and LOD files
    lod_files = {}
    base_files = []
    
    for vdf in all_vdf:
        name_upper = vdf.stem.upper()
        if name_upper.endswith('_LOD'):
            # This is a LOD file — map to base name
            base_name = vdf.stem[:-4]  # Remove _LOD
            lod_files[base_name.upper()] = vdf
        else:
            base_files.append(vdf)
    
    # Build pairs
    pairs = []
    for base in base_files:
        lod = lod_files.get(base.stem.upper())
        display = base.stem
        pairs.append((base, lod, display))
    
    return pairs

def find_vdf_pairs_recursive(root_folder):
    """Recursively scan all subfolders for VDF files, preserving folder structure.
    Returns: [(base_path, lod_path_or_None, display_name, rel_dir), ...]
    rel_dir is the relative path from root_folder to the VDF's parent folder.
    """
    root = Path(root_folder).resolve()
    all_results = []
    
    # Collect all directories that contain VDF files
    vdf_dirs = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if f.upper().endswith('.VDF'):
                vdf_dirs.add(dirpath)
                break
    
    # Process each directory
    for vdf_dir in sorted(vdf_dirs):
        pairs = find_vdf_pairs(vdf_dir)
        rel = os.path.relpath(vdf_dir, root)
        if rel == '.':
            rel = ''
        for base, lod, display in pairs:
            # Display shows relative path for clarity
            if rel:
                disp = f"{rel}/{display}".replace('\\', '/')
            else:
                disp = display
            all_results.append((base, lod, disp, rel))
    
    return all_results

def convert_vdf_to_obj(base_path, lod_path, output_dir, log_func=None, tex_index=None):
    """Convert a VDF (+ optional LOD) to OBJ + MTL.
    Returns: (obj_path, stats_dict) or raises on error.
    """
    def log(msg):
        if log_func:
            log_func(msg)
    
    base_name = Path(base_path).stem
    
    # Parse base VDF
    log(f"  Parsing {Path(base_path).name}...")
    with open(base_path, 'rb') as f:
        base_data = f.read()
    base_root = parse_ntf(base_data)
    base_meshes = extract_meshes_from_vdf(base_root)
    
    if not base_meshes:
        raise ValueError(f"No mesh data found in {Path(base_path).name}")
    
    # Parse LOD VDF if exists
    lod_meshes = []
    if lod_path and os.path.isfile(lod_path):
        log(f"  Parsing {Path(lod_path).name} (LOD)...")
        with open(lod_path, 'rb') as f:
            lod_data = f.read()
        lod_root = parse_ntf(lod_data)
        lod_meshes = extract_meshes_from_vdf(lod_root)
    
    # Build mesh groups
    mesh_groups = []
    materials = {}
    
    for mesh in base_meshes:
        group_name = f"{base_name}_{mesh.name}"
        mesh_groups.append((group_name, mesh))
        if mesh.material and mesh.material.name not in materials:
            materials[mesh.material.name] = mesh.material
    
    for mesh in lod_meshes:
        group_name = f"{base_name}_LOD_{mesh.name}"
        mesh_groups.append((group_name, mesh))
        if mesh.material and mesh.material.name not in materials:
            materials[mesh.material.name] = mesh.material
    
    # If no materials found, create a default
    if not materials:
        default = ShaderInfo()
        default.name = "default"
        materials["default"] = default
    
    # Write files
    obj_path = os.path.join(output_dir, f"{base_name}.obj")
    mtl_path = os.path.join(output_dir, f"{base_name}.mtl")
    mtl_filename = f"{base_name}.mtl"
    
    log(f"  Writing {base_name}.obj...")
    write_obj(obj_path, mesh_groups, mtl_filename)
    
    log(f"  Writing {base_name}.mtl...")
    write_mtl(mtl_path, materials)
    
    # Collect all referenced textures
    all_textures = set()
    for mat in materials.values():
        if mat.tex_diffuse: all_textures.add(mat.tex_diffuse)
        if mat.tex_bump: all_textures.add(mat.tex_bump)
        if mat.tex_lightmap: all_textures.add(mat.tex_lightmap)
    
    # Copy textures if index available
    tex_found = 0
    tex_missing = 0
    tex_missing_names = []
    if tex_index and all_textures:
        log(f"  Copying textures...")
        for tex_name in sorted(all_textures):
            dest = os.path.join(output_dir, tex_name)
            if os.path.exists(dest):
                tex_found += 1
                continue
            src = tex_index.get(tex_name.upper())
            if src and os.path.isfile(src):
                try:
                    shutil.copy2(src, dest)
                    tex_found += 1
                except Exception as e:
                    log(f"    WARN: {tex_name}: {e}")
                    tex_missing += 1
                    tex_missing_names.append(tex_name)
            else:
                tex_missing += 1
                tex_missing_names.append(tex_name)
    
    # Stats
    total_verts = sum(len(m.positions) for _, m in mesh_groups)
    total_tris = sum(len(m.faces) for _, m in mesh_groups)
    base_verts = sum(len(m.positions) for m in base_meshes)
    base_tris = sum(len(m.faces) for m in base_meshes)
    lod_verts = sum(len(m.positions) for m in lod_meshes)
    lod_tris = sum(len(m.faces) for m in lod_meshes)
    
    stats = {
        'groups': len(mesh_groups),
        'materials': len(materials),
        'total_verts': total_verts,
        'total_tris': total_tris,
        'base_verts': base_verts,
        'base_tris': base_tris,
        'lod_verts': lod_verts,
        'lod_tris': lod_tris,
        'has_lod': len(lod_meshes) > 0,
        'textures': all_textures,
        'tex_found': tex_found,
        'tex_missing': tex_missing,
        'tex_missing_names': tex_missing_names,
    }
    
    return obj_path, stats

# ─── GUI ──────────────────────────────────────────────────────────────────────

class VDFConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TW1 VDF-to-OBJ Converter v1.1")
        self.root.geometry("1050x720")
        self.root.minsize(700, 500)
        
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.tex_dir = tk.StringVar()
        self.vdf_pairs = []
        self.tex_index = {}
        
        self._setup_theme()
        self._build_ui()
        
        # Auto-detect VDF folder
        self._try_auto_detect()
    
    def _setup_theme(self):
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
        style.configure('.', background=self.BG, foreground=self.FG, fieldbackground=self.BG2)
        style.configure('TFrame', background=self.BG)
        style.configure('TLabel', background=self.BG, foreground=self.FG, font=('Segoe UI', 10))
        style.configure('TButton', background=self.BG3, foreground=self.FG, font=('Segoe UI', 10),
                        borderwidth=1, relief='flat', padding=(12, 6))
        style.map('TButton', background=[('active', self.ACCENT)])
        style.configure('Accent.TButton', background=self.ACCENT, foreground='#ffffff')
        style.map('Accent.TButton', background=[('active', '#1177bb')])
        style.configure('TCheckbutton', background=self.BG, foreground=self.FG, font=('Segoe UI', 10))
        style.configure('Treeview', background=self.BG2, foreground=self.FG, fieldbackground=self.BG2,
                        font=('Consolas', 10), rowheight=24)
        style.configure('Treeview.Heading', background=self.BG3, foreground=self.FG,
                        font=('Segoe UI', 10, 'bold'))
        style.map('Treeview', background=[('selected', self.ACCENT)])
    
    def _build_ui(self):
        # ── Top: Input/Output folders ──
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill='x')
        
        ttk.Label(top, text="Input Folder:").grid(row=0, column=0, sticky='w', pady=2)
        inp = ttk.Entry(top, textvariable=self.input_dir, font=('Consolas', 10))
        inp.grid(row=0, column=1, sticky='ew', padx=(8, 4), pady=2)
        ttk.Button(top, text="Browse...", command=self._browse_input).grid(row=0, column=2, pady=2)
        
        ttk.Label(top, text="Output Folder:").grid(row=1, column=0, sticky='w', pady=2)
        out = ttk.Entry(top, textvariable=self.output_dir, font=('Consolas', 10))
        out.grid(row=1, column=1, sticky='ew', padx=(8, 4), pady=2)
        ttk.Button(top, text="Browse...", command=self._browse_output).grid(row=1, column=2, pady=2)
        
        ttk.Label(top, text="Textures Folder:").grid(row=2, column=0, sticky='w', pady=2)
        tex = ttk.Entry(top, textvariable=self.tex_dir, font=('Consolas', 10))
        tex.grid(row=2, column=1, sticky='ew', padx=(8, 4), pady=2)
        ttk.Button(top, text="Browse...", command=self._browse_textures).grid(row=2, column=2, pady=2)
        
        top.columnconfigure(1, weight=1)
        
        # ── File list ──
        mid = ttk.Frame(self.root, padding=(10, 0, 10, 0))
        mid.pack(fill='both', expand=True)
        
        cols = ('file', 'lod', 'status')
        self.tree = ttk.Treeview(mid, columns=cols, show='headings', selectmode='extended')
        self.tree.heading('file', text='VDF File')
        self.tree.heading('lod', text='LOD')
        self.tree.heading('status', text='Status')
        self.tree.column('file', width=500, minwidth=300)
        self.tree.column('lod', width=80, minwidth=60, anchor='center')
        self.tree.column('status', width=350, minwidth=150)
        
        scrollbar = ttk.Scrollbar(mid, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # ── Buttons ──
        btn_frame = ttk.Frame(self.root, padding=10)
        btn_frame.pack(fill='x')
        
        self.select_all_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(btn_frame, text="Select All", variable=self.select_all_var,
                        command=self._toggle_select_all).pack(side='left')
        
        self.btn_convert = ttk.Button(btn_frame, text="Convert Selected", style='Accent.TButton',
                                       command=self._convert_selected)
        self.btn_convert.pack(side='right', padx=(4, 0))
        
        ttk.Button(btn_frame, text="Convert All", command=self._convert_all).pack(side='right', padx=(4, 0))
        
        self.status_label = ttk.Label(btn_frame, text="")
        self.status_label.pack(side='right', padx=20)
        
        # ── Log ──
        log_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        log_frame.pack(fill='x')
        
        self.log_text = tk.Text(log_frame, height=8, bg=self.BG2, fg=self.FG,
                                font=('Consolas', 9), relief='flat', wrap='word',
                                insertbackground=self.FG)
        self.log_text.pack(fill='x')
        self.log_text.configure(state='disabled')
    
    def _log(self, msg):
        self.log_text.configure(state='normal')
        self.log_text.insert('end', msg + '\n')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
        self.root.update_idletasks()
    
    def _browse_input(self):
        folder = filedialog.askdirectory(title="Select folder with VDF files")
        if folder:
            self.input_dir.set(folder)
            if not self.output_dir.get():
                self.output_dir.set(os.path.join(folder, "OBJ_Export"))
            # Auto-detect Textures folder
            if not self.tex_dir.get():
                tex = find_textures_folder(folder)
                if tex:
                    self.tex_dir.set(tex)
            self._scan_folder()
    
    def _browse_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_dir.set(folder)
    
    def _browse_textures(self):
        folder = filedialog.askdirectory(title="Select WDFiles Textures folder")
        if folder:
            self.tex_dir.set(folder)
    
    def _try_auto_detect(self):
        # Check if script is in a folder with VDFs
        script_dir = os.path.dirname(os.path.abspath(__file__))
        vdfs = list(Path(script_dir).glob('*.vdf'))
        if not vdfs:
            # Check extensionless files
            for f in Path(script_dir).iterdir():
                if f.is_file() and f.suffix == '':
                    try:
                        with open(f, 'rb') as fh:
                            if struct.unpack('<I', fh.read(4))[0] == NTF_MAGIC:
                                vdfs.append(f)
                                break
                    except:
                        pass
        
        if vdfs:
            self.input_dir.set(script_dir)
            self.output_dir.set(os.path.join(script_dir, "OBJ_Export"))
            tex = find_textures_folder(script_dir)
            if tex:
                self.tex_dir.set(tex)
            self._scan_folder()
    
    def _scan_folder(self):
        folder = self.input_dir.get()
        if not folder or not os.path.isdir(folder):
            return
        
        self.tree.delete(*self.tree.get_children())
        
        # Use recursive scan
        recursive_pairs = find_vdf_pairs_recursive(folder)
        # Convert to vdf_pairs format: (base, lod, display, rel_dir)
        self.vdf_pairs = recursive_pairs
        
        for base, lod, display, rel_dir in self.vdf_pairs:
            lod_str = "Yes" if lod else "—"
            self.tree.insert('', 'end', values=(display, lod_str, "Ready"))
        
        self._log(f"Found {len(self.vdf_pairs)} VDF model(s) in {Path(folder).name}/ (recursive)")
        self.status_label.configure(text=f"{len(self.vdf_pairs)} files")
    
    def _toggle_select_all(self):
        if self.select_all_var.get():
            for item in self.tree.get_children():
                self.tree.selection_add(item)
        else:
            self.tree.selection_remove(*self.tree.get_children())
    
    def _get_selected_indices(self):
        selected = self.tree.selection()
        all_items = self.tree.get_children()
        return [all_items.index(s) for s in selected if s in all_items]
    
    def _convert_all(self):
        indices = list(range(len(self.vdf_pairs)))
        self._do_convert(indices)
    
    def _convert_selected(self):
        indices = self._get_selected_indices()
        if not indices:
            # If nothing selected, convert all
            indices = list(range(len(self.vdf_pairs)))
        self._do_convert(indices)
    
    def _do_convert(self, indices):
        if not indices:
            return
        
        output = self.output_dir.get()
        if not output:
            messagebox.showwarning("No Output", "Please select an output folder.")
            return
        
        os.makedirs(output, exist_ok=True)
        
        # Build texture index
        tex_dir = self.tex_dir.get()
        tex_index = {}
        if tex_dir and os.path.isdir(tex_dir):
            self._log(f"Scanning textures in {Path(tex_dir).name}/...")
            tex_index = build_texture_index(tex_dir)
            self._log(f"  Found {len(tex_index)} DDS textures")
        
        self.btn_convert.configure(state='disabled')
        all_items = self.tree.get_children()
        
        success = 0
        errors = 0
        total_verts = 0
        total_tris = 0
        total_tex_found = 0
        total_tex_missing = 0
        all_missing_tex = []
        
        self._log(f"\n{'='*50}")
        self._log(f"Converting {len(indices)} file(s)...")
        self._log(f"Output: {output}")
        self._log(f"{'='*50}")
        
        for idx in indices:
            base, lod, name, rel_dir = self.vdf_pairs[idx]
            item = all_items[idx]
            
            self.tree.set(item, 'status', "Converting...")
            self.root.update_idletasks()
            
            # Create mirrored subfolder in output
            if rel_dir:
                sub_output = os.path.join(output, rel_dir)
            else:
                sub_output = output
            os.makedirs(sub_output, exist_ok=True)
            
            try:
                self._log(f"\n[{name}]")
                obj_path, stats = convert_vdf_to_obj(
                    base, lod, sub_output, self._log, tex_index=tex_index
                )
                
                lod_info = ""
                if stats['has_lod']:
                    lod_info = f" + LOD({stats['lod_verts']}v/{stats['lod_tris']}t)"
                
                tex_info = ""
                if stats['textures']:
                    tex_info = f" | tex:{stats['tex_found']}/{len(stats['textures'])}"
                
                status = f"OK — {stats['base_verts']}v / {stats['base_tris']}t{lod_info}{tex_info}"
                self.tree.set(item, 'status', status)
                
                if stats['tex_missing_names']:
                    for t in stats['tex_missing_names']:
                        self._log(f"    MISSING: {t}")
                        if t not in all_missing_tex:
                            all_missing_tex.append(t)
                
                self._log(f"  Done: {stats['total_verts']}v, {stats['total_tris']}t, {stats['groups']} groups, tex:{stats['tex_found']}/{len(stats['textures'])}")
                
                success += 1
                total_verts += stats['total_verts']
                total_tris += stats['total_tris']
                total_tex_found += stats['tex_found']
                total_tex_missing += stats['tex_missing']
                
            except Exception as e:
                self.tree.set(item, 'status', f"ERROR: {e}")
                self._log(f"  ERROR: {e}")
                errors += 1
        
        self._log(f"\n{'='*50}")
        self._log(f"Done! {success} converted, {errors} errors")
        self._log(f"Total: {total_verts} vertices, {total_tris} triangles")
        if total_tex_found or total_tex_missing:
            self._log(f"Textures: {total_tex_found} copied, {total_tex_missing} missing")
        if all_missing_tex:
            self._log(f"Missing textures: {', '.join(all_missing_tex[:20])}")
        self._log(f"{'='*50}")
        
        self.status_label.configure(text=f"{success} OK, {errors} errors")
        self.btn_convert.configure(state='normal')
        
        if success > 0:
            self._log(f"\nFiles saved to: {output}")

# ─── CLI Mode ─────────────────────────────────────────────────────────────────

def cli_convert(input_path, output_dir=None, tex_dir=None):
    """Command-line conversion: file or folder."""
    input_path = Path(input_path)
    
    # Auto-detect textures folder
    if not tex_dir:
        tex_dir = find_textures_folder(str(input_path))
    
    tex_index = {}
    if tex_dir and os.path.isdir(tex_dir):
        print(f"Scanning textures in {tex_dir}...")
        tex_index = build_texture_index(tex_dir)
        print(f"  Found {len(tex_index)} DDS textures")
    
    if input_path.is_file():
        # Single file
        if not output_dir:
            output_dir = str(input_path.parent)
        os.makedirs(output_dir, exist_ok=True)
        
        lod_path = None
        stem = input_path.stem
        if not stem.upper().endswith('_LOD'):
            lod_candidate = input_path.parent / f"{stem}_LOD{input_path.suffix}"
            if lod_candidate.exists():
                lod_path = str(lod_candidate)
        
        obj_path, stats = convert_vdf_to_obj(str(input_path), lod_path, output_dir, print, tex_index=tex_index)
        print(f"\nExported: {obj_path}")
        print(f"  {stats['total_verts']} vertices, {stats['total_tris']} triangles, {stats['groups']} groups")
        if stats['tex_found']:
            print(f"  Textures: {stats['tex_found']} copied, {stats['tex_missing']} missing")
        if stats['tex_missing_names']:
            print(f"  Missing: {', '.join(stats['tex_missing_names'])}")
        
    elif input_path.is_dir():
        # Folder — recursive scan with mirrored structure
        if not output_dir:
            output_dir = str(input_path / "OBJ_Export")
        
        pairs = find_vdf_pairs_recursive(str(input_path))
        if not pairs:
            print(f"No VDF files found in {input_path}")
            return
        
        print(f"Found {len(pairs)} VDF model(s) (recursive)")
        for base, lod, display, rel_dir in pairs:
            sub_output = os.path.join(output_dir, rel_dir) if rel_dir else output_dir
            os.makedirs(sub_output, exist_ok=True)
            try:
                print(f"\n[{display}]")
                obj_path, stats = convert_vdf_to_obj(
                    str(base), str(lod) if lod else None, sub_output, print, tex_index=tex_index
                )
                print(f"  -> {stats['total_verts']}v, {stats['total_tris']}t, tex:{stats['tex_found']}/{len(stats['textures'])}")
            except Exception as e:
                print(f"  ERROR: {e}")
        
        print(f"\nDone! Output: {output_dir}")
    else:
        print(f"Not found: {input_path}")

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) > 1:
        # CLI mode
        input_path = sys.argv[1]
        output_dir = sys.argv[2] if len(sys.argv) > 2 else None
        cli_convert(input_path, output_dir)
    else:
        # GUI mode
        if not HAS_TK:
            print("Usage: python tw1_vdf_converter.py <input_file_or_folder> [output_folder]")
            print("       or run without args for GUI (requires tkinter)")
            sys.exit(1)
        root = tk.Tk()
        app = VDFConverterApp(root)
        root.mainloop()
