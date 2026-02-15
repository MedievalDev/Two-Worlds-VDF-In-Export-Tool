#!/usr/bin/env python3
"""
NTF Editor v1.0 - Node Tree Format Editor
Two Worlds / Reality Pump File Editor
Supports: .mtr .vdf .chm .chv .xfn .hor

Features:
- Dark themed GUI with treeview
- Node tree browser with detail panel
- Texture reference editor (TexS0, TexS1, TexS2)
- Edit any chunk value
- Byte-identical round-trip save
- Drag & drop support
"""

import struct
import sys
import os
import tempfile
from io import BytesIO
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, Menu, simpledialog
except ImportError:
    print("tkinter not available!")
    sys.exit(1)

# ============================================================
# Theme
# ============================================================

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

NTF_EXTENSIONS = {'.mtr', '.vdf', '.chm', '.chv', '.xfn', '.hor'}

# ============================================================
# Binary Format
# ============================================================

HEADER_MAGIC = bytes([0x9f, 0x99, 0x66, 0xf6])

CHUNK_TYPES = {
    17: "int32", 18: "uint32", 19: "float32",
    20: "float32[4]", 21: "float32[16]", 22: "text", 23: "binary",
}

TEXTURE_FIELDS = {"TexS0", "TexS1", "TexS2"}

NODE_TYPE_NAMES = {
    -1: "Root / AnimRef / FrameRange", -253: "Shader",
    -254: "FrameData (type A)", -255: "FrameData (type B)",
    -65535: "FarLOD Billboard",
}

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


class NTFNode:
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


# ============================================================
# Parse / Write
# ============================================================

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

def verify_roundtrip(filepath, root):
    tmp = tempfile.NamedTemporaryFile(suffix='.ntf', delete=False); tmp.close()
    try:
        save_ntf(tmp.name, root)
        with open(filepath, 'rb') as f: orig = f.read()
        with open(tmp.name, 'rb') as f: saved = f.read()
        return orig == saved
    finally:
        os.unlink(tmp.name)


# ============================================================
# Helpers
# ============================================================

def find_nodes(node, pred, res=None):
    if res is None: res = []
    if pred(node): res.append(node)
    for ch in node.children: find_nodes(ch, pred, res)
    return res

def find_shaders(root): return find_nodes(root, lambda n: n.node_type == -253)

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


# ============================================================
# GUI
# ============================================================

class NTFEditorApp:
    def __init__(self, root_tk, filepath=None):
        self.root_tk = root_tk
        self.root_tk.title("NTF Editor v1.0 - Two Worlds File Editor")
        self.root_tk.geometry("1100x700")
        self.root_tk.minsize(900, 550)
        self.root_tk.configure(bg=BG)

        self.filepath = None
        self.ntf_root = None
        self.modified = False
        self.node_map = {}
        self.font_size = 10

        self._configure_styles()
        self._create_menu()
        self._create_toolbar()
        self._create_main_ui()
        self._create_statusbar()

        self.root_tk.bind("<Control-o>", lambda e: self.open_file())
        self.root_tk.bind("<Control-s>", lambda e: self.save_file())
        self.root_tk.bind("<Control-Shift-S>", lambda e: self.save_file_as())
        self.root_tk.bind("<Control-plus>", lambda e: self._zoom(1))
        self.root_tk.bind("<Control-minus>", lambda e: self._zoom(-1))
        self.root_tk.bind("<F5>", lambda e: self.verify())

        if filepath:
            self._load_file(filepath)

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(".", background=BG, foreground=FG, fieldbackground=BG2)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TButton", background=BG3, foreground=FG, borderwidth=0, padding=6)
        style.map("TButton", background=[('active', BG4)])
        style.configure("Treeview", background=BG2, foreground=FG, fieldbackground=BG2,
                         borderwidth=0, rowheight=26, font=("Segoe UI", self.font_size))
        style.configure("Treeview.Heading", background=BG3, foreground=FG_DIM,
                         font=("Segoe UI", self.font_size - 1, "bold"))
        style.map("Treeview", background=[('selected', ACCENT)], foreground=[('selected', '#fff')])

    def _create_menu(self):
        mb = Menu(self.root_tk, bg=BG3, fg=FG, activebackground=ACCENT,
                  activeforeground="#fff", borderwidth=0)
        mc = dict(tearoff=0, bg=BG3, fg=FG, activebackground=ACCENT, activeforeground="#fff")

        fm = Menu(mb, **mc)
        fm.add_command(label="Open...        Ctrl+O", command=self.open_file)
        fm.add_separator()
        fm.add_command(label="Save           Ctrl+S", command=self.save_file)
        fm.add_command(label="Save As...     Ctrl+Shift+S", command=self.save_file_as)
        fm.add_separator()
        fm.add_command(label="Exit", command=self._on_close)
        mb.add_cascade(label="File", menu=fm)

        em = Menu(mb, **mc)
        em.add_command(label="Edit Selected Chunk", command=self._edit_selected_chunk)
        em.add_separator()
        em.add_command(label="Find Chunk...", command=self._find_chunk_dialog)
        mb.add_cascade(label="Edit", menu=em)

        vm = Menu(mb, **mc)
        vm.add_command(label="Expand All", command=self._expand_all)
        vm.add_command(label="Collapse All", command=self._collapse_all)
        vm.add_separator()
        vm.add_command(label="Zoom In    Ctrl++", command=lambda: self._zoom(1))
        vm.add_command(label="Zoom Out   Ctrl+-", command=lambda: self._zoom(-1))
        mb.add_cascade(label="View", menu=vm)

        tm = Menu(mb, **mc)
        tm.add_command(label="Show Textures", command=self._show_textures)
        tm.add_command(label="Show Shaders", command=self._show_shaders)
        tm.add_command(label="Statistics", command=self._show_stats)
        tm.add_separator()
        tm.add_command(label="Shader Transplant...", command=self._shader_transplant)
        tm.add_separator()
        tm.add_command(label="Verify Integrity    F5", command=self.verify)
        mb.add_cascade(label="Tools", menu=tm)

        hm = Menu(mb, **mc)
        hm.add_command(label="About", command=self._about)
        hm.add_command(label="Format Info", command=self._format_info)
        mb.add_cascade(label="Help", menu=hm)

        self.root_tk.config(menu=mb)

    def _create_toolbar(self):
        tb = tk.Frame(self.root_tk, bg=BG3, pady=4, padx=8)
        tb.pack(fill="x")
        btns = [
            ("\U0001f4c2 Open", self.open_file),
            ("\U0001f4be Save", self.save_file),
            None,
            ("\U0001f3a8 Textures", self._show_textures),
            ("\U0001f50d Find", self._find_chunk_dialog),
            ("\U0001f4ca Stats", self._show_stats),
            None,
            ("\U0001fa78 Transplant", self._shader_transplant),
            None,
            ("\u2714 Verify", self.verify),
        ]
        for item in btns:
            if item is None:
                tk.Frame(tb, bg=FG_DIM, width=1, height=24).pack(side="left", padx=6, fill="y")
                continue
            label, cmd = item
            b = tk.Button(tb, text=label, command=cmd, bg=BG3, fg=FG,
                          activebackground=BG4, activeforeground=FG, bd=0, padx=10, pady=3,
                          font=("Segoe UI", 9), cursor="hand2", relief="flat")
            b.pack(side="left", padx=2)
            b.bind("<Enter>", lambda e, b=b: b.configure(bg=BG4))
            b.bind("<Leave>", lambda e, b=b: b.configure(bg=BG3))

    def _create_main_ui(self):
        self.paned = tk.PanedWindow(self.root_tk, orient="horizontal", bg=BG,
                                     sashwidth=3, sashrelief="flat", opaqueresize=True)
        self.paned.pack(fill="both", expand=True, padx=4, pady=4)

        left = tk.Frame(self.paned, bg=BG2)
        self.paned.add(left, width=420, minsize=250)

        sf = tk.Frame(left, bg=BG2, pady=4, padx=4)
        sf.pack(fill="x")
        tk.Label(sf, text="\U0001f50d", bg=BG2, fg=FG_DIM, font=("Segoe UI", 10)).pack(side="left", padx=(4,2))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        tk.Entry(sf, textvariable=self.search_var, bg=BG3, fg=FG, insertbackground=FG,
                 bd=0, font=("Segoe UI", self.font_size), relief="flat").pack(
                 side="left", fill="x", expand=True, padx=4, ipady=3)

        tf = tk.Frame(left, bg=BG2)
        tf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tf, show="tree", selectmode="browse")
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)

        self.detail = tk.Frame(self.paned, bg=BG)
        self.paned.add(self.detail, minsize=350)
        self._show_welcome()

    def _create_statusbar(self):
        sb = tk.Frame(self.root_tk, bg=BG3, height=26)
        sb.pack(fill="x", side="bottom")
        self.status_l = tk.Label(sb, text="  Ready", bg=BG3, fg=FG_DIM,
                                  font=("Segoe UI", 9), anchor="w")
        self.status_l.pack(side="left", fill="x", expand=True)
        self.status_r = tk.Label(sb, text="", bg=BG3, fg=FG_DIM,
                                  font=("Segoe UI", 9), anchor="e")
        self.status_r.pack(side="right", padx=8)

    def _status(self, text, color=FG_DIM):
        self.status_l.configure(text=f"  {text}", fg=color)

    # ---- Scrollable frame helper ----
    def _scrollable(self, parent=None):
        if parent is None: parent = self.detail
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        cf = tk.Frame(canvas, bg=BG)
        cf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=cf, anchor="nw", tags="inn")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig("inn", width=e.width-20))
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        def _scroll(e): canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _scroll)
        return canvas, cf

    # ---- Welcome ----
    def _show_welcome(self):
        for w in self.detail.winfo_children(): w.destroy()
        f = tk.Frame(self.detail, bg=BG)
        f.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(f, text="\U0001f4c4", font=("Segoe UI", 48), bg=BG, fg=ACCENT).pack()
        tk.Label(f, text="NTF Editor", font=("Segoe UI", 20, "bold"), bg=BG, fg=FG).pack(pady=(8,2))
        tk.Label(f, text="Two Worlds / Reality Pump File Editor",
                 font=("Segoe UI", 11), bg=BG, fg=FG_DIM).pack()
        tk.Label(f, text=".mtr  .vdf  .chm  .chv  .xfn  .hor",
                 font=("Consolas", 10), bg=BG, fg=ACCENT).pack(pady=(4,16))
        btn = tk.Button(f, text="\U0001f4c2  Open File", command=self.open_file,
                        bg=ACCENT, fg="#fff", activebackground=ACCENT2, activeforeground="#fff",
                        bd=0, padx=24, pady=8, font=("Segoe UI", 11, "bold"), cursor="hand2")
        btn.pack(pady=8)
        tk.Label(f, text="or drag & drop a file onto this script",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(pady=(4,0))
        tk.Label(f, text="Ctrl+O  open  |  Ctrl+S  save  |  F5  verify",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(pady=(8,0))

    # ---- File Ops ----
    def open_file(self):
        exts = ' '.join(f'*{e}' for e in NTF_EXTENSIONS)
        p = filedialog.askopenfilename(title="Open NTF File", filetypes=[
            ("NTF Files", exts), ("Model", "*.vdf"), ("Animation", "*.mtr *.chm"), ("All", "*.*")])
        if p: self._load_file(p)

    def _load_file(self, path):
        try:
            self.ntf_root = parse_ntf(path)
            self.filepath = path; self.modified = False; self._update_title()
            self._populate_tree()
            nn = count_nodes(self.ntf_root); ns = len(find_shaders(self.ntf_root))
            nt = len(find_textures(self.ntf_root)); sz = os.path.getsize(path)
            self._status(f"Loaded: {nn} nodes, {ns} shaders, {nt} textures", GREEN)
            self.status_r.configure(text=f"{os.path.basename(path)}  ({sz:,} bytes)")
            self._show_loaded()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load:\n{e}")
            self._status(f"Error: {e}", RED)

    def _show_loaded(self):
        for w in self.detail.winfo_children(): w.destroy()
        f = tk.Frame(self.detail, bg=BG, padx=20, pady=20)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="\u2714  File Loaded", font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=GREEN).pack(anchor="w", pady=(0,12))

        info = tk.Frame(f, bg=BG2, padx=16, pady=12); info.pack(fill="x")
        for label, val in [
            ("File:", os.path.basename(self.filepath)), ("Path:", self.filepath),
            ("Size:", f"{os.path.getsize(self.filepath):,} bytes"),
            ("Nodes:", str(count_nodes(self.ntf_root))),
            ("Shaders:", str(len(find_shaders(self.ntf_root)))),
            ("Textures:", str(len(find_textures(self.ntf_root)))),
        ]:
            r = tk.Frame(info, bg=BG2); r.pack(fill="x", pady=2)
            tk.Label(r, text=label, font=("Segoe UI", 10, "bold"), bg=BG2, fg=FG_DIM,
                     width=10, anchor="w").pack(side="left")
            tk.Label(r, text=val, font=("Segoe UI", 10), bg=BG2, fg=FG, anchor="w").pack(side="left")

        tk.Label(f, text="\nSelect a node in the tree to view details.",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack(anchor="w", pady=(12,0))

        qa = tk.Frame(f, bg=BG, pady=12); qa.pack(fill="x")
        tk.Label(qa, text="Quick Actions:", font=("Segoe UI", 10, "bold"),
                 bg=BG, fg=FG).pack(anchor="w", pady=(0,8))
        for label, cmd in [
            ("\U0001f3a8  Show Textures", self._show_textures),
            ("\U0001f4ca  Statistics", self._show_stats),
            ("\u2714  Verify Integrity", self.verify),
        ]:
            b = tk.Button(qa, text=label, command=cmd, bg=BG3, fg=FG, activebackground=BG4,
                          bd=0, padx=12, pady=6, font=("Segoe UI", 10), cursor="hand2",
                          relief="flat", anchor="w")
            b.pack(fill="x", pady=2)
            b.bind("<Enter>", lambda e, b=b: b.configure(bg=BG4))
            b.bind("<Leave>", lambda e, b=b: b.configure(bg=BG3))

    def save_file(self):
        if not self.ntf_root or not self.filepath: return self.save_file_as()
        try:
            save_ntf(self.filepath, self.ntf_root)
            self.modified = False; self._update_title()
            self._status(f"Saved to {os.path.basename(self.filepath)}", GREEN)
        except Exception as e:
            messagebox.showerror("Error", f"Save failed:\n{e}")

    def save_file_as(self):
        if not self.ntf_root: return
        ext = os.path.splitext(self.filepath)[1] if self.filepath else ".vdf"
        p = filedialog.asksaveasfilename(title="Save As", defaultextension=ext,
            initialfile=os.path.basename(self.filepath) if self.filepath else "output"+ext,
            filetypes=[("NTF Files", "*.mtr *.vdf *.chm *.chv *.xfn *.hor"), ("All", "*.*")])
        if p: self.filepath = p; self.save_file()

    def _update_title(self):
        t = "NTF Editor v1.0"
        if self.filepath: t += f" - {os.path.basename(self.filepath)}"
        if self.modified: t += " *"
        self.root_tk.title(t)

    def _mark_modified(self):
        self.modified = True; self._update_title()

    # ---- Tree ----
    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children()); self.node_map.clear()
        if self.ntf_root:
            self._add_tree_node("", self.ntf_root)
            for item in self.tree.get_children():
                self.tree.item(item, open=True)
                for child in self.tree.get_children(item):
                    self.tree.item(child, open=True)

    def _add_tree_node(self, parent, node):
        label = f"{node.icon}  {node.type_label}"
        if node.name: label += f'  "{node.name}"'
        tags = ()
        if node.node_type == -253: tags = ("shader",)
        elif node.data.get("IsLocator"): tags = ("locator",)
        iid = self.tree.insert(parent, "end", text=label, tags=tags)
        self.node_map[iid] = node
        for child in node.children: self._add_tree_node(iid, child)
        self.tree.tag_configure("shader", foreground=YELLOW)
        self.tree.tag_configure("locator", foreground=CYAN)

    def _on_select(self, e=None):
        sel = self.tree.selection()
        if sel:
            node = self.node_map.get(sel[0])
            if node: self._show_detail(node)

    def _on_double_click(self, e=None): self._edit_selected_chunk()

    def _on_search(self, *args):
        q = self.search_var.get().lower().strip()
        if not q or not self.ntf_root: return
        for iid, node in self.node_map.items():
            if q in node.name.lower() or q in node.type_label.lower():
                self.tree.see(iid); self.tree.selection_set(iid); self.tree.focus(iid); return
            for ch in node.chunks:
                if ch.chunk_type == 22 and q in str(ch.value).lower():
                    self.tree.see(iid); self.tree.selection_set(iid); self.tree.focus(iid); return

    # ---- Detail Panel ----
    def _show_detail(self, node):
        for w in self.detail.winfo_children(): w.destroy()
        fs = self.font_size

        hdr = tk.Frame(self.detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
        tk.Label(hdr, text=f"{node.icon}  {node.type_label}",
                 font=("Segoe UI", fs+3, "bold"), bg=BG3, fg=FG).pack(anchor="w")
        if node.name:
            tk.Label(hdr, text=f'"{node.name}"', font=("Segoe UI", fs+1),
                     bg=BG3, fg=ACCENT2).pack(anchor="w")
        tk.Label(hdr, text=f"Type: {node.node_type}  |  Chunks: {len(node.chunks)}  |  Children: {len(node.children)}",
                 font=("Segoe UI", fs-1), bg=BG3, fg=FG_DIM).pack(anchor="w", pady=(4,0))

        if not node.chunks:
            tk.Label(self.detail, text="No chunks.", font=("Segoe UI", fs), bg=BG, fg=FG_DIM).pack(pady=20)
            return

        tf = tk.Frame(self.detail, bg=BG); tf.pack(fill="both", expand=True, padx=8, pady=8)

        ch = tk.Frame(tf, bg=BG3, padx=8, pady=4); ch.pack(fill="x")
        tk.Label(ch, text="Field", font=("Segoe UI", 9, "bold"), bg=BG3, fg=FG_DIM,
                 width=18, anchor="w").pack(side="left")
        tk.Label(ch, text="Type", font=("Segoe UI", 9, "bold"), bg=BG3, fg=FG_DIM,
                 width=12, anchor="w").pack(side="left")
        tk.Label(ch, text="Value", font=("Segoe UI", 9, "bold"), bg=BG3, fg=FG_DIM,
                 anchor="w").pack(side="left", fill="x", expand=True)

        canvas, cf = self._scrollable(tf)

        for i, chunk in enumerate(node.chunks):
            bgc = BG2 if i % 2 == 0 else BG
            row = tk.Frame(cf, bg=bgc, padx=8, pady=4); row.pack(fill="x")

            nc = GREEN if chunk.name in TEXTURE_FIELDS else (YELLOW if chunk.chunk_type == 22 else FG)
            tk.Label(row, text=chunk.name, font=("Consolas", fs), bg=bgc, fg=nc,
                     width=18, anchor="w").pack(side="left")
            tk.Label(row, text=chunk.type_name(), font=("Consolas", fs-1), bg=bgc, fg=FG_DIM,
                     width=12, anchor="w").pack(side="left")

            vc = GREEN if chunk.name in TEXTURE_FIELDS else (YELLOW if chunk.chunk_type == 22 else FG)
            tk.Label(row, text=chunk.display_value(), font=("Consolas", fs), bg=bgc, fg=vc,
                     anchor="w").pack(side="left", fill="x", expand=True)

            if chunk.chunk_type in (17, 18, 19, 22):
                eb = tk.Button(row, text="\u270E", command=lambda c=chunk, n=node: self._edit_chunk(c, n),
                               bg=bgc, fg=ACCENT, activebackground=BG4, bd=0, padx=4,
                               cursor="hand2", relief="flat", font=("Segoe UI", 10))
                eb.pack(side="right", padx=4)

    # ---- Edit Chunk ----
    def _edit_chunk(self, chunk, node):
        dlg = tk.Toplevel(self.root_tk); dlg.title(f"Edit: {chunk.name}")
        dlg.geometry("450x200"); dlg.configure(bg=BG)
        dlg.transient(self.root_tk); dlg.grab_set()

        tk.Label(dlg, text=f"Edit: {chunk.name}", font=("Segoe UI", 13, "bold"),
                 bg=BG, fg=FG).pack(pady=(16,4))
        tk.Label(dlg, text=f"Type: {chunk.type_name()}  |  Node: \"{node.name}\"",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack()

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
            chunk.value = nv; self._mark_modified(); dlg.destroy()
            self._show_detail(node); self._status(f"Changed {chunk.name} = {repr(nv)}", YELLOW)

        bf = tk.Frame(dlg, bg=BG); bf.pack(pady=8)
        tk.Button(bf, text="Cancel", command=dlg.destroy, bg=BG3, fg=FG, bd=0,
                  padx=16, pady=4, font=("Segoe UI", 10), cursor="hand2").pack(side="left", padx=4)
        tk.Button(bf, text="Apply", command=apply, bg=ACCENT, fg="#fff", bd=0,
                  padx=16, pady=4, font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="left", padx=4)
        entry.bind("<Return>", lambda e: apply())
        entry.bind("<Escape>", lambda e: dlg.destroy())

    def _edit_selected_chunk(self):
        sel = self.tree.selection()
        if not sel: return
        node = self.node_map.get(sel[0])
        if node:
            for ch in node.chunks:
                if ch.chunk_type in (17,18,19,22): self._edit_chunk(ch, node); return

    # ---- Find ----
    def _find_chunk_dialog(self):
        if not self.ntf_root: return
        q = simpledialog.askstring("Find Chunk", "Chunk name:", parent=self.root_tk)
        if not q: return
        results = []
        def _s(n):
            for ch in n.chunks:
                if q.lower() in ch.name.lower(): results.append((n, ch))
            for c in n.children: _s(c)
        _s(self.ntf_root)

        if not results:
            messagebox.showinfo("Find", f'Nothing found for "{q}".'); return

        for w in self.detail.winfo_children(): w.destroy()
        hdr = tk.Frame(self.detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
        tk.Label(hdr, text=f"\U0001f50d  Search: \"{q}\"", font=("Segoe UI", 14, "bold"),
                 bg=BG3, fg=FG).pack(anchor="w")
        tk.Label(hdr, text=f"{len(results)} results", font=("Segoe UI", 10),
                 bg=BG3, fg=GREEN).pack(anchor="w")

        _, cf = self._scrollable()
        for i, (node, ch) in enumerate(results):
            bgc = BG2 if i%2==0 else BG
            row = tk.Frame(cf, bg=bgc, padx=12, pady=6); row.pack(fill="x")
            nname = node.name or "(unnamed)"
            tk.Label(row, text=f'In "{nname}":', font=("Segoe UI", 9),
                     bg=bgc, fg=FG_DIM).pack(anchor="w")
            tk.Label(row, text=f"{ch.name} = {ch.display_value()}", font=("Consolas", self.font_size),
                     bg=bgc, fg=FG).pack(anchor="w")

    # ---- Textures / Shaders / Stats ----
    def _show_textures(self):
        if not self.ntf_root: return
        texs = find_textures(self.ntf_root)
        for w in self.detail.winfo_children(): w.destroy()
        hdr = tk.Frame(self.detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
        tk.Label(hdr, text="\U0001f3a8  Texture References", font=("Segoe UI", 14, "bold"),
                 bg=BG3, fg=FG).pack(anchor="w")
        if not texs:
            tk.Label(hdr, text="No textures found. (Textures are in .vdf Shader nodes)",
                     font=("Segoe UI", 10), bg=BG3, fg=YELLOW).pack(anchor="w"); return
        tk.Label(hdr, text=f"{len(texs)} texture(s)", font=("Segoe UI", 10),
                 bg=BG3, fg=GREEN).pack(anchor="w")
        ct = tk.Frame(self.detail, bg=BG, padx=12, pady=8); ct.pack(fill="both", expand=True)
        for tex in texs:
            card = tk.Frame(ct, bg=BG2, padx=12, pady=10); card.pack(fill="x", pady=4)
            tk.Label(card, text=f"\U0001f3a8  Shader: \"{tex['shader']}\"",
                     font=("Segoe UI", 11, "bold"), bg=BG2, fg=FG).pack(anchor="w")
            row = tk.Frame(card, bg=BG2, pady=4); row.pack(fill="x")
            tk.Label(row, text=f"  {tex['slot']}:", font=("Consolas", self.font_size),
                     bg=BG2, fg=CYAN, width=8, anchor="w").pack(side="left")
            tk.Label(row, text=f"\"{tex['texture']}\"", font=("Consolas", self.font_size),
                     bg=BG2, fg=GREEN).pack(side="left")
            tk.Button(row, text="\u270E Edit",
                      command=lambda t=tex: self._edit_chunk(t['chunk'], t['node']),
                      bg=BG4, fg=ACCENT, activebackground=ACCENT, activeforeground="#fff",
                      bd=0, padx=8, pady=2, font=("Segoe UI", 9), cursor="hand2").pack(side="right")

    def _show_shaders(self):
        if not self.ntf_root: return
        shaders = find_shaders(self.ntf_root)
        for w in self.detail.winfo_children(): w.destroy()
        hdr = tk.Frame(self.detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
        tk.Label(hdr, text="\U0001f3a8  Shader Nodes", font=("Segoe UI", 14, "bold"),
                 bg=BG3, fg=FG).pack(anchor="w")
        tk.Label(hdr, text=f"{len(shaders)} shader(s)", font=("Segoe UI", 10),
                 bg=BG3, fg=GREEN if shaders else YELLOW).pack(anchor="w")
        if not shaders: return
        ct = tk.Frame(self.detail, bg=BG, padx=8, pady=8); ct.pack(fill="both", expand=True)
        for s in shaders:
            card = tk.Frame(ct, bg=BG2, padx=12, pady=8); card.pack(fill="x", pady=4)
            tk.Label(card, text=f"\U0001f3a8  \"{s.name}\"", font=("Segoe UI", 11, "bold"),
                     bg=BG2, fg=FG).pack(anchor="w")
            for ch in s.chunks:
                c = GREEN if ch.name in TEXTURE_FIELDS else FG
                tk.Label(card, text=f"  {ch.name}: {ch.display_value()}",
                         font=("Consolas", self.font_size-1), bg=BG2, fg=c).pack(anchor="w")

    def _show_stats(self):
        if not self.ntf_root: return
        for w in self.detail.winfo_children(): w.destroy()
        nodes = find_nodes(self.ntf_root, lambda n: True)
        types = {}; fields = set(); bsz = 0
        for n in nodes:
            types[n.node_type] = types.get(n.node_type, 0)+1
            for ch in n.chunks:
                fields.add(ch.name)
                if ch.chunk_type == 23: bsz += len(ch.value)

        hdr = tk.Frame(self.detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
        tk.Label(hdr, text="\U0001f4ca  File Statistics", font=("Segoe UI", 14, "bold"),
                 bg=BG3, fg=FG).pack(anchor="w")

        ct = tk.Frame(self.detail, bg=BG, padx=16, pady=12); ct.pack(fill="both", expand=True)

        cards = tk.Frame(ct, bg=BG); cards.pack(fill="x", pady=(0,12))
        for label, val, color in [
            ("Nodes", str(len(nodes)), CYAN), ("Binary", f"{bsz:,}b", YELLOW),
            ("Fields", str(len(fields)), GREEN), ("Shaders", str(len(find_shaders(self.ntf_root))), ORANGE),
            ("Textures", str(len(find_textures(self.ntf_root))), ACCENT),
        ]:
            c = tk.Frame(cards, bg=BG2, padx=12, pady=8); c.pack(side="left", padx=4, fill="x", expand=True)
            tk.Label(c, text=val, font=("Segoe UI", 16, "bold"), bg=BG2, fg=color).pack()
            tk.Label(c, text=label, font=("Segoe UI", 9), bg=BG2, fg=FG_DIM).pack()

        tk.Label(ct, text="Node Types:", font=("Segoe UI", 11, "bold"), bg=BG, fg=FG).pack(anchor="w", pady=(8,4))
        for t, cnt in sorted(types.items(), key=lambda x: (x[0] is None, x[0] or 0)):
            r = tk.Frame(ct, bg=BG); r.pack(fill="x")
            tk.Label(r, text=f"  {NODE_TYPE_NAMES.get(t, f'type {t}')}:", font=("Segoe UI", 10),
                     bg=BG, fg=FG_DIM).pack(side="left")
            tk.Label(r, text=str(cnt), font=("Segoe UI", 10, "bold"), bg=BG, fg=FG).pack(side="left", padx=4)

        tk.Label(ct, text="\nAll Fields:", font=("Segoe UI", 11, "bold"),
                 bg=BG, fg=FG).pack(anchor="w", pady=(8,4))
        tk.Label(ct, text=", ".join(sorted(fields)), font=("Consolas", 9),
                 bg=BG, fg=FG_DIM, wraplength=500, justify="left").pack(anchor="w")

    # ---- Shader Transplant ----
    def _shader_transplant(self):
        if not self.ntf_root:
            messagebox.showinfo("Shader Transplant", "Load the EDITED VDF first (File > Open),\nthen use Shader Transplant to pick the ORIGINAL.")
            return

        # Ask user to select the ORIGINAL VDF
        exts = ' '.join(f'*{e}' for e in NTF_EXTENSIONS)
        orig_path = filedialog.askopenfilename(
            title="Select ORIGINAL VDF (source of shader data)",
            filetypes=[("VDF Files", "*.vdf"), ("NTF Files", exts), ("All", "*.*")])
        if not orig_path:
            return

        try:
            orig_root = parse_ntf(orig_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load original:\n{e}"); return

        orig_shaders = find_shaders(orig_root)
        edit_shaders = find_shaders(self.ntf_root)

        if not orig_shaders:
            messagebox.showinfo("Shader Transplant", "No shaders found in the original file.")
            return
        if not edit_shaders:
            messagebox.showinfo("Shader Transplant", "No shaders found in the current (edited) file.")
            return

        # Show transplant preview dialog
        self._show_transplant_dialog(orig_path, orig_root, orig_shaders, edit_shaders)

    def _show_transplant_dialog(self, orig_path, orig_root, orig_shaders, edit_shaders):
        for w in self.detail.winfo_children(): w.destroy()
        fs = self.font_size

        # Header
        hdr = tk.Frame(self.detail, bg=BG3, padx=12, pady=10); hdr.pack(fill="x")
        tk.Label(hdr, text="\U0001fa78  Shader Transplant",
                 font=("Segoe UI", 14, "bold"), bg=BG3, fg=FG).pack(anchor="w")
        tk.Label(hdr, text="Restore shader data from original VDF to edited VDF",
                 font=("Segoe UI", 10), bg=BG3, fg=FG_DIM).pack(anchor="w")

        # File info
        info = tk.Frame(self.detail, bg=BG, padx=12, pady=8); info.pack(fill="x")

        src_f = tk.Frame(info, bg=BG2, padx=12, pady=8); src_f.pack(fill="x", pady=2)
        tk.Label(src_f, text="ORIGINAL (source):", font=("Segoe UI", 9, "bold"),
                 bg=BG2, fg=CYAN).pack(anchor="w")
        tk.Label(src_f, text=os.path.basename(orig_path), font=("Consolas", fs),
                 bg=BG2, fg=FG).pack(anchor="w")
        tk.Label(src_f, text=f"{len(orig_shaders)} shader(s) found", font=("Segoe UI", 9),
                 bg=BG2, fg=GREEN).pack(anchor="w")

        dst_f = tk.Frame(info, bg=BG2, padx=12, pady=8); dst_f.pack(fill="x", pady=2)
        tk.Label(dst_f, text="EDITED (target - keeps mesh/UVs):", font=("Segoe UI", 9, "bold"),
                 bg=BG2, fg=YELLOW).pack(anchor="w")
        tk.Label(dst_f, text=os.path.basename(self.filepath), font=("Consolas", fs),
                 bg=BG2, fg=FG).pack(anchor="w")
        tk.Label(dst_f, text=f"{len(edit_shaders)} shader(s) found", font=("Segoe UI", 9),
                 bg=BG2, fg=GREEN).pack(anchor="w")

        # Build match table
        # Strategy: match by shader Name, then by position
        matches = []
        used_orig = set()

        # First pass: exact name match
        for ei, es in enumerate(edit_shaders):
            matched = False
            for oi, os_ in enumerate(orig_shaders):
                if oi not in used_orig and es.name == os_.name:
                    matches.append((ei, es, oi, os_, "name"))
                    used_orig.add(oi)
                    matched = True
                    break
            if not matched:
                matches.append((ei, es, None, None, "no match"))

        # Second pass: unmatched by position
        unmatched_orig = [i for i in range(len(orig_shaders)) if i not in used_orig]
        for m_idx, (ei, es, oi, os_, method) in enumerate(matches):
            if method == "no match" and unmatched_orig:
                oi = unmatched_orig.pop(0)
                matches[m_idx] = (ei, es, oi, orig_shaders[oi], "position")

        # Leftover originals not in edited
        for oi in unmatched_orig:
            matches.append((None, None, oi, orig_shaders[oi], "extra"))

        # Preview
        tk.Label(self.detail, text="  Match Preview:", font=("Segoe UI", 11, "bold"),
                 bg=BG, fg=FG).pack(anchor="w", padx=12, pady=(8,4))

        canvas, cf = self._scrollable()

        # Checkboxes for each match
        self._transplant_vars = []

        for i, (ei, es, oi, os_, method) in enumerate(matches):
            bgc = BG2 if i % 2 == 0 else BG
            row = tk.Frame(cf, bg=bgc, padx=12, pady=8); row.pack(fill="x")

            if method == "extra":
                # Original shader has no counterpart in edited
                tk.Label(row, text=f"\u26a0  Original shader \"{os_.name}\" has no match in edited file",
                         font=("Segoe UI", fs), bg=bgc, fg=ORANGE).pack(anchor="w")
                self._transplant_vars.append(None)
                continue

            var = tk.BooleanVar(value=True)
            self._transplant_vars.append(var)

            top = tk.Frame(row, bg=bgc); top.pack(fill="x")
            cb = tk.Checkbutton(top, variable=var, bg=bgc, activebackground=bgc,
                                 selectcolor=BG3, fg=FG)
            cb.pack(side="left")

            match_color = GREEN if method == "name" else YELLOW
            match_text = f"matched by {method}"
            tk.Label(top, text=f"Shader \"{es.name}\"", font=("Segoe UI", fs, "bold"),
                     bg=bgc, fg=FG).pack(side="left")
            tk.Label(top, text=f"  ({match_text})", font=("Segoe UI", fs-1),
                     bg=bgc, fg=match_color).pack(side="left")

            if os_ is not None:
                # Show what will change
                orig_chunks = {c.name: c for c in os_.chunks}
                edit_chunks = {c.name: c for c in es.chunks}

                changes = []
                # Chunks in original but not in edited (will be added)
                for cn, cc in orig_chunks.items():
                    if cn not in edit_chunks:
                        changes.append(("+", cn, cc.display_value()))
                    elif cn in edit_chunks:
                        ec = edit_chunks[cn]
                        ov = cc.display_value()
                        ev = ec.display_value()
                        if ov != ev:
                            changes.append(("~", cn, f"{ev}  \u2192  {ov}"))

                # Chunks in edited but not in original (will be removed)
                for cn in edit_chunks:
                    if cn not in orig_chunks:
                        changes.append(("-", cn, edit_chunks[cn].display_value()))

                if changes:
                    for op, cn, val in changes:
                        det = tk.Frame(row, bg=bgc); det.pack(fill="x", padx=28)
                        if op == "+":
                            tk.Label(det, text=f"  + ADD  {cn}: {val}",
                                     font=("Consolas", fs-1), bg=bgc, fg=GREEN).pack(anchor="w")
                        elif op == "-":
                            tk.Label(det, text=f"  - DEL  {cn}: {val}",
                                     font=("Consolas", fs-1), bg=bgc, fg=RED).pack(anchor="w")
                        elif op == "~":
                            tc = GREEN if cn in TEXTURE_FIELDS else YELLOW
                            tk.Label(det, text=f"  ~ CHG  {cn}: {val}",
                                     font=("Consolas", fs-1), bg=bgc, fg=tc).pack(anchor="w")
                else:
                    tk.Label(row, text="    No changes needed (identical)",
                             font=("Segoe UI", fs-1), bg=bgc, fg=FG_DIM).pack(anchor="w", padx=28)

        # Buttons
        btn_frame = tk.Frame(self.detail, bg=BG, padx=12, pady=12); btn_frame.pack(fill="x")

        def do_transplant():
            count = 0
            for m_idx, (ei, es, oi, os_, method) in enumerate(matches):
                if method == "extra" or self._transplant_vars[m_idx] is None:
                    continue
                if not self._transplant_vars[m_idx].get():
                    continue
                if os_ is None or es is None:
                    continue

                # Replace all entries in edit shader with original shader entries
                # Keep the order from the original
                new_entries = []
                for etype, data in os_.entries:
                    if etype == ENTRY_CHUNK:
                        # Deep copy the chunk
                        new_chunk = ChunkData(data.chunk_type, data.name, data.value)
                        new_entries.append((ENTRY_CHUNK, new_chunk))
                    else:
                        new_entries.append((etype, data))

                es.entries = new_entries
                count += 1

            if count:
                self._mark_modified()
                self._populate_tree()
                self._status(f"Transplanted {count} shader(s) from original", GREEN)
                self._show_transplant_result(count, orig_path)
            else:
                self._status("No shaders transplanted", YELLOW)

        tk.Button(btn_frame, text="Cancel", command=self._show_loaded,
                  bg=BG3, fg=FG, bd=0, padx=16, pady=6,
                  font=("Segoe UI", 10), cursor="hand2").pack(side="left", padx=4)
        tk.Button(btn_frame, text="\U0001fa78  Apply Transplant", command=do_transplant,
                  bg=ACCENT, fg="#fff", bd=0, padx=16, pady=6,
                  font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="left", padx=4)

    def _show_transplant_result(self, count, orig_path):
        for w in self.detail.winfo_children(): w.destroy()

        f = tk.Frame(self.detail, bg=BG, padx=20, pady=30)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="\u2714", font=("Segoe UI", 48), bg=BG, fg=GREEN).pack()
        tk.Label(f, text="Shader Transplant Complete!",
                 font=("Segoe UI", 16, "bold"), bg=BG, fg=GREEN).pack(pady=(8,4))
        tk.Label(f, text=f"{count} shader(s) restored from original",
                 font=("Segoe UI", 11), bg=BG, fg=FG).pack()
        tk.Label(f, text=f"Source: {os.path.basename(orig_path)}",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack(pady=(8,0))

        tk.Label(f, text="\nMesh and UV data remain from the edited file.\nShader properties are now from the original.",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack(pady=(8,0))

        tk.Label(f, text="\nDon't forget to save! (Ctrl+S)",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=YELLOW).pack(pady=(12,0))

        bf = tk.Frame(f, bg=BG, pady=12); bf.pack()
        tk.Button(bf, text="\U0001f4be  Save Now", command=self.save_file_as,
                  bg=ACCENT, fg="#fff", bd=0, padx=20, pady=8,
                  font=("Segoe UI", 11, "bold"), cursor="hand2").pack(side="left", padx=4)
        tk.Button(bf, text="\U0001f3a8  View Shaders", command=self._show_shaders,
                  bg=BG3, fg=FG, bd=0, padx=16, pady=8,
                  font=("Segoe UI", 10), cursor="hand2").pack(side="left", padx=4)

    # ---- Verify ----
    def verify(self):
        if not self.ntf_root or not self.filepath:
            messagebox.showinfo("Verify", "No file loaded."); return
        if verify_roundtrip(self.filepath, self.ntf_root):
            self._status("Verify: PASS - Byte-identical!", GREEN)
            messagebox.showinfo("Verify", "\u2714 Byte-identical round-trip!\nFile can be saved without data loss.")
        else:
            self._status("Verify: FAIL!", RED)
            messagebox.showwarning("Verify", "\u2718 Round-trip mismatch!\nSaving may alter the file.")

    # ---- View Controls ----
    def _expand_all(self):
        def ex(i):
            self.tree.item(i, open=True)
            for c in self.tree.get_children(i): ex(c)
        for i in self.tree.get_children(): ex(i)

    def _collapse_all(self):
        def co(i):
            self.tree.item(i, open=False)
            for c in self.tree.get_children(i): co(c)
        for i in self.tree.get_children(): co(i)

    def _zoom(self, d):
        self.font_size = max(8, min(16, self.font_size + d))
        ttk.Style().configure("Treeview", font=("Segoe UI", self.font_size),
                               rowheight=int(self.font_size*2.4))
        self._status(f"Font size: {self.font_size}", FG_DIM)

    # ---- Help ----
    def _about(self):
        messagebox.showinfo("About", "NTF Editor v1.0\n\nNode Tree Format Editor\n"
            "Two Worlds / Reality Pump\n\n.mtr .vdf .chm .chv .xfn .hor\n\n"
            "Byte-identical round-trip save\nTexture & chunk editing")

    def _format_info(self):
        messagebox.showinfo("Format Info",
            "Node Tree Format (NTF)\nBy Reality Pump\nHeader: 0x9F9966F6 (LE)\n\n"
            ".vdf = 3D Model\n.mtr = Animation\n.chm = Character Anim\n"
            ".chv = Model + Bones\n.xfn = Font Cache\n.hor = Horizon\n\n"
            "Texture Slots (in .vdf Shader):\n"
            "  TexS0 = Diffuse (UV1)\n  TexS1 = Normal (UV1)\n  TexS2 = Lightmap (UV2)")

    def _on_close(self):
        if self.modified:
            a = messagebox.askyesnocancel("Unsaved", "Save before closing?")
            if a is True: self.save_file()
            elif a is None: return
        self.root_tk.destroy()


def main():
    fp = None
    if len(sys.argv) > 1:
        c = sys.argv[1].strip('"').strip("'")
        if os.path.isfile(c): fp = c
    root = tk.Tk()
    app = NTFEditorApp(root, fp)
    root.protocol("WM_DELETE_WINDOW", app._on_close)
    root.mainloop()

if __name__ == '__main__':
    main()
