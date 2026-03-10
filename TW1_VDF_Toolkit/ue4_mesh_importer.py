"""
UE4 Mesh Importer Script (4.27)
===============================
Importiert OBJ-Meshes, erstellt ein Master Material mit Diffuse + BumpOffset,
und erzeugt Material Instances gruppiert nach Textur-Kombination.

Ausfuehrung: Im UE4 Editor ueber Output Log > Python oder
             Edit > Project Settings > Python > Startup Scripts

WICHTIG: Vor dem Ausfuehren muessen die PNG-Texturen bereits im Projekt sein,
         oder das Script importiert sie automatisch.

Anpassungen:
  - SOURCE_ROOT: Pfad zu deinem Meshes-Ordner auf der Festplatte
  - DEST_ROOT: Ziel-Pfad im UE4 Content Browser
"""

import unreal
import os
import re
from collections import defaultdict

# ============================================================
# KONFIGURATION - HIER ANPASSEN
# ============================================================

# Pfad zum Meshes-Ordner auf deiner Festplatte (mit OBJ, MTL, PNG Dateien)
SOURCE_ROOT = r"C:\Users\marco\Desktop\TWObjectPosPerTile\Mesh_Export\Meshes"

# Ziel-Pfad im UE4 Content Browser
DEST_ROOT = "/Game/Meshes"

# Unterordner die importiert werden sollen
SUBFOLDERS = ["Static", "Interactive", "Foliage"]

# Master Material Name
MASTER_MATERIAL_NAME = "M_Master"
MASTER_MATERIAL_PATH = f"{DEST_ROOT}/Materials/{MASTER_MATERIAL_NAME}"

# BumpOffset Staerke (Standardwert fuer MIs)
DEFAULT_BUMP_HEIGHT = 0.02

# Transform-Korrektur fuer Witcher 1 Exports
IMPORT_ROTATION = unreal.Rotator(90, -90, 0)  # Pitch, Yaw, Roll
IMPORT_SCALE = 8.0

# ============================================================
# HILFSFUNKTIONEN
# ============================================================

def log(msg):
    """Logging ins UE4 Output Log."""
    unreal.log(f"[MeshImporter] {msg}")

def log_warning(msg):
    unreal.log_warning(f"[MeshImporter] {msg}")

def log_error(msg):
    unreal.log_error(f"[MeshImporter] {msg}")

def normalize_texture_path(tex_path):
    """Normalisiert Textur-Pfade (Backslashes, Case)."""
    # Backslashes zu Forward-Slashes
    tex_path = tex_path.replace("\\", "/")
    # Nur den Dateinamen ohne Pfad-Prefix
    tex_name = os.path.basename(tex_path)
    # Erweiterung entfernen fuer UE4 Asset-Name
    name_no_ext = os.path.splitext(tex_name)[0]
    return tex_name, name_no_ext

def parse_mtl_file(mtl_path):
    """
    Parst eine MTL-Datei und gibt eine Liste von Material-Definitionen zurueck.
    Jede Definition ist ein Dict mit: name, map_Kd, map_bump, map_Ka
    """
    materials = []
    current_mat = None

    with open(mtl_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()

            if line.startswith("newmtl "):
                if current_mat:
                    materials.append(current_mat)
                mat_name = line[7:].strip()
                current_mat = {
                    "name": mat_name,
                    "map_Kd": None,
                    "map_bump": None,
                    "map_Ka": None,
                }

            elif current_mat:
                if line.startswith("map_Kd "):
                    current_mat["map_Kd"] = line[7:].strip()
                elif line.startswith("map_bump "):
                    current_mat["map_bump"] = line[9:].strip()
                elif line.startswith("map_Ka "):
                    current_mat["map_Ka"] = line[7:].strip()

    if current_mat:
        materials.append(current_mat)

    return materials

def get_texture_key(mat_def):
    """
    Erzeugt einen eindeutigen Key aus der Textur-Kombination
    fuer MI-Grouping.
    """
    kd = mat_def.get("map_Kd") or ""
    bump = mat_def.get("map_bump") or ""
    # Normalisieren
    kd = normalize_texture_path(kd)[1].lower() if kd else ""
    bump = normalize_texture_path(bump)[1].lower() if bump else ""
    return f"{kd}|{bump}"

def make_mi_name(texture_key):
    """Erzeugt einen sauberen MI-Namen aus dem Textur-Key."""
    parts = texture_key.split("|")
    diffuse_name = parts[0] if parts[0] else "default"
    # Entferne _bump suffix falls vorhanden fuer kuerzeren Namen
    name = diffuse_name.upper()
    # Sonderzeichen entfernen
    name = re.sub(r"[^A-Z0-9_]", "_", name)
    return f"MI_{name}"

# ============================================================
# ASSET IMPORT FUNKTIONEN
# ============================================================

def import_texture(source_file, dest_path):
    """Importiert eine einzelne Textur nach UE4."""
    asset_name = os.path.splitext(os.path.basename(source_file))[0]
    full_dest = f"{dest_path}/{asset_name}"

    # Pruefen ob bereits vorhanden
    if unreal.EditorAssetLibrary.does_asset_exist(full_dest):
        return unreal.EditorAssetLibrary.load_asset(full_dest)

    # Import Task erstellen
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", source_file)
    task.set_editor_property("destination_path", dest_path)
    task.set_editor_property("destination_name", asset_name)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    asset = unreal.EditorAssetLibrary.load_asset(full_dest)
    if asset:
        log(f"  Textur importiert: {asset_name}")
    else:
        log_warning(f"  Textur Import fehlgeschlagen: {source_file}")
    return asset

def import_mesh(source_file, dest_path):
    """Importiert ein OBJ Mesh nach UE4."""
    asset_name = os.path.splitext(os.path.basename(source_file))[0]
    full_dest = f"{dest_path}/{asset_name}"

    # Pruefen ob bereits vorhanden
    if unreal.EditorAssetLibrary.does_asset_exist(full_dest):
        return unreal.EditorAssetLibrary.load_asset(full_dest)

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", source_file)
    task.set_editor_property("destination_path", dest_path)
    task.set_editor_property("destination_name", asset_name)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)

    # FBX Import Options (werden auch fuer OBJ genutzt)
    options = unreal.FbxImportUI()
    options.set_editor_property("import_mesh", True)
    options.set_editor_property("import_materials", False)  # Wir machen eigene Materials
    options.set_editor_property("import_textures", False)   # Texturen separat
    options.set_editor_property("import_as_skeletal", False)
    options.static_mesh_import_data.set_editor_property("combine_meshes", True)
    options.static_mesh_import_data.set_editor_property("import_rotation", IMPORT_ROTATION)
    options.static_mesh_import_data.set_editor_property("import_uniform_scale", IMPORT_SCALE)

    task.set_editor_property("options", options)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    asset = unreal.EditorAssetLibrary.load_asset(full_dest)
    if asset:
        log(f"  Mesh importiert: {asset_name}")
    else:
        log_warning(f"  Mesh Import fehlgeschlagen: {source_file}")
    return asset

# ============================================================
# MASTER MATERIAL
# ============================================================

def create_master_material():
    """
    Erstellt das Master Material mit:
    - TextureSampleParameter2D 'Diffuse' -> BaseColor
    - TextureSampleParameter2D 'BumpMap' -> BumpOffset -> WorldPositionOffset
    - ScalarParameter 'BumpHeight' fuer MI-Kontrolle
    """
    if unreal.EditorAssetLibrary.does_asset_exist(MASTER_MATERIAL_PATH):
        log("Master Material existiert bereits, ueberspringe Erstellung.")
        return unreal.EditorAssetLibrary.load_asset(MASTER_MATERIAL_PATH)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    mat_factory = unreal.MaterialFactoryNew()

    material = asset_tools.create_asset(
        MASTER_MATERIAL_NAME,
        f"{DEST_ROOT}/Materials",
        unreal.Material,
        mat_factory
    )

    if not material:
        log_error("Master Material konnte nicht erstellt werden!")
        return None

    # Material Editor Library fuer Node-Erstellung
    mel = unreal.MaterialEditingLibrary

    # --- Diffuse Texture Parameter ---
    diffuse_param = mel.create_material_expression(
        material,
        unreal.MaterialExpressionTextureSampleParameter2D,
        -600, -200
    )
    diffuse_param.set_editor_property("parameter_name", "Diffuse")

    # --- BumpMap Texture Parameter ---
    bump_param = mel.create_material_expression(
        material,
        unreal.MaterialExpressionTextureSampleParameter2D,
        -600, 200
    )
    bump_param.set_editor_property("parameter_name", "BumpMap")

    # --- BumpHeight Scalar Parameter ---
    height_param = mel.create_material_expression(
        material,
        unreal.MaterialExpressionScalarParameter,
        -800, 400
    )
    height_param.set_editor_property("parameter_name", "BumpHeight")
    height_param.set_editor_property("default_value", DEFAULT_BUMP_HEIGHT)

    # --- BumpOffset Node ---
    bump_offset = mel.create_material_expression(
        material,
        unreal.MaterialExpressionBumpOffset,
        -300, 200
    )

    # Verbindungen herstellen
    # BumpMap R-Kanal -> BumpOffset Height
    mel.connect_material_expressions(
        bump_param, "R",
        bump_offset, "Height"
    )

    # HeightParam -> BumpOffset HeightRatio
    mel.connect_material_expressions(
        height_param, "",
        bump_offset, "HeightRatioInput"
    )

    # BumpOffset Output -> Diffuse Textur UVs (Parallax-Effekt)
    mel.connect_material_expressions(
        bump_offset, "",
        diffuse_param, "UVs"
    )

    # Diffuse -> BaseColor
    mel.connect_material_property(
        diffuse_param, "RGB",
        unreal.MaterialProperty.MP_BASE_COLOR
    )

    # Material-Einstellungen
    material.set_editor_property("two_sided", False)

    # Kompilieren und speichern
    mel.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(MASTER_MATERIAL_PATH)

    log("Master Material erstellt: " + MASTER_MATERIAL_PATH)
    return material

# ============================================================
# MATERIAL INSTANCES
# ============================================================

def create_material_instance(mi_name, master_material, diffuse_asset, bump_asset):
    """Erstellt eine Material Instance mit gesetzten Texturen."""
    mi_path = f"{DEST_ROOT}/Materials/{mi_name}"

    # Pruefen ob bereits vorhanden
    if unreal.EditorAssetLibrary.does_asset_exist(mi_path):
        return unreal.EditorAssetLibrary.load_asset(mi_path)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    mi_factory = unreal.MaterialInstanceConstantFactoryNew()

    mi = asset_tools.create_asset(
        mi_name,
        f"{DEST_ROOT}/Materials",
        unreal.MaterialInstanceConstant,
        mi_factory
    )

    if not mi:
        log_warning(f"MI konnte nicht erstellt werden: {mi_name}")
        return None

    # Parent Material setzen
    mi.set_editor_property("parent", master_material)

    # Texturen setzen
    if diffuse_asset:
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(
            mi, "Diffuse", diffuse_asset
        )

    if bump_asset:
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(
            mi, "BumpMap", bump_asset
        )

    # BumpHeight Standardwert
    unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(
        mi, "BumpHeight", DEFAULT_BUMP_HEIGHT
    )

    unreal.EditorAssetLibrary.save_asset(mi_path)
    log(f"  MI erstellt: {mi_name}")
    return mi

# ============================================================
# MATERIAL ZUWEISUNG
# ============================================================

def assign_material_to_mesh(mesh_asset, mi_asset, slot_index=0):
    """Weist eine Material Instance einem Mesh-Slot zu."""
    if not mesh_asset or not mi_asset:
        return

    mesh = mesh_asset
    # Static Mesh Material Slots setzen
    num_slots = len(mesh.static_materials)
    if slot_index < num_slots:
        mesh.set_material(slot_index, mi_asset)
    else:
        log_warning(f"  Slot {slot_index} existiert nicht bei {mesh.get_name()} (hat {num_slots} Slots)")

# ============================================================
# TEXTUR-SUCHE
# ============================================================

def find_texture_file(tex_name, source_root, subfolder):
    """
    Sucht eine Textur-Datei im Source-Ordner.
    Sucht zuerst im Subfolder, dann im Root, dann rekursiv.
    """
    # Normalisieren
    tex_filename, tex_base = normalize_texture_path(tex_name)

    # Suchpfade in Prioritaetsreihenfolge
    search_dirs = [
        os.path.join(source_root, subfolder),
        source_root,
    ]

    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for root, dirs, files in os.walk(search_dir):
            for f in files:
                if f.lower() == tex_filename.lower():
                    return os.path.join(root, f)

    # Globale Suche
    for root, dirs, files in os.walk(source_root):
        for f in files:
            if f.lower() == tex_filename.lower():
                return os.path.join(root, f)

    return None

# ============================================================
# HAUPTFUNKTION
# ============================================================

def run_import():
    """Hauptfunktion: Importiert alles."""

    log("=" * 60)
    log("STARTE MESH IMPORT")
    log("=" * 60)
    log(f"Source: {SOURCE_ROOT}")
    log(f"Destination: {DEST_ROOT}")

    # Pruefen ob Source existiert
    if not os.path.isdir(SOURCE_ROOT):
        log_error(f"Source-Ordner nicht gefunden: {SOURCE_ROOT}")
        log_error("Bitte SOURCE_ROOT in der Konfiguration anpassen!")
        return

    # Ordnerstruktur in UE4 erstellen
    for folder in ["Materials", "Textures", "Static", "Interactive", "Foliage"]:
        path = f"{DEST_ROOT}/{folder}"
        if not unreal.EditorAssetLibrary.does_directory_exist(path):
            unreal.EditorAssetLibrary.make_directory(path)

    # ---- PHASE 1: MTL-Dateien parsen und analysieren ----
    log("\n--- PHASE 1: MTL-Dateien analysieren ---")

    # Struktur: { texture_key: { "mi_name": str, "diffuse": str, "bump": str, "meshes": [(obj_path, subfolder, slot_index)] } }
    texture_groups = {}
    # Mapping: (obj_path, slot_index) -> texture_key
    mesh_material_map = {}

    total_mtl = 0
    total_materials = 0

    for subfolder in SUBFOLDERS:
        folder_path = os.path.join(SOURCE_ROOT, subfolder)
        if not os.path.isdir(folder_path):
            log_warning(f"Subfolder nicht gefunden: {subfolder}")
            continue

        for filename in os.listdir(folder_path):
            if not filename.lower().endswith(".mtl"):
                continue

            mtl_path = os.path.join(folder_path, filename)
            obj_name = os.path.splitext(filename)[0]
            obj_path = os.path.join(folder_path, obj_name + ".obj")

            if not os.path.isfile(obj_path):
                continue

            total_mtl += 1
            mat_defs = parse_mtl_file(mtl_path)

            for slot_idx, mat_def in enumerate(mat_defs):
                total_materials += 1
                tex_key = get_texture_key(mat_def)

                if tex_key not in texture_groups:
                    texture_groups[tex_key] = {
                        "mi_name": make_mi_name(tex_key),
                        "diffuse": mat_def.get("map_Kd"),
                        "bump": mat_def.get("map_bump"),
                        "meshes": [],
                    }

                texture_groups[tex_key]["meshes"].append(
                    (obj_path, subfolder, slot_idx)
                )
                mesh_material_map[(obj_path, slot_idx)] = tex_key

    log(f"MTL-Dateien geparst: {total_mtl}")
    log(f"Material-Definitionen: {total_materials}")
    log(f"Einzigartige Textur-Kombinationen (= MIs): {len(texture_groups)}")

    # Duplikat-MI-Namen aufloesen
    mi_name_counts = defaultdict(int)
    for tex_key, group in texture_groups.items():
        base_name = group["mi_name"]
        mi_name_counts[base_name] += 1
        if mi_name_counts[base_name] > 1:
            group["mi_name"] = f"{base_name}_{mi_name_counts[base_name]}"

    # ---- PHASE 2: Texturen importieren ----
    log("\n--- PHASE 2: Texturen importieren ---")

    texture_cache = {}  # tex_filename_lower -> UE4 asset
    textures_imported = 0
    textures_missing = 0

    unique_textures = set()
    for group in texture_groups.values():
        if group["diffuse"]:
            unique_textures.add(group["diffuse"])
        if group["bump"]:
            unique_textures.add(group["bump"])

    log(f"Einzigartige Texturen zu importieren: {len(unique_textures)}")

    with unreal.ScopedSlowTask(len(unique_textures), "Importiere Texturen...") as slow_task:
        slow_task.make_dialog(True)

        for tex_ref in unique_textures:
            if slow_task.should_cancel():
                log_warning("Import abgebrochen!")
                return
            slow_task.enter_progress_frame(1, f"Textur: {tex_ref}")

            tex_filename, tex_base = normalize_texture_path(tex_ref)
            tex_key_lower = tex_filename.lower()

            if tex_key_lower in texture_cache:
                continue

            # Textur-Datei finden
            tex_file = find_texture_file(tex_ref, SOURCE_ROOT, "")
            if tex_file:
                asset = import_texture(tex_file, f"{DEST_ROOT}/Textures")
                if asset:
                    texture_cache[tex_key_lower] = asset
                    textures_imported += 1

                    # Bump Maps als Linear markieren (kein sRGB)
                    if "bump" in tex_base.lower():
                        asset.set_editor_property("srgb", False)
                        asset.set_editor_property(
                            "compression_settings",
                            unreal.TextureCompressionSettings.TC_DEFAULT
                        )
                else:
                    textures_missing += 1
            else:
                log_warning(f"  Textur nicht gefunden: {tex_ref}")
                textures_missing += 1

    log(f"Texturen importiert: {textures_imported}")
    log(f"Texturen nicht gefunden: {textures_missing}")

    # ---- PHASE 3: Master Material erstellen ----
    log("\n--- PHASE 3: Master Material erstellen ---")
    master_material = create_master_material()
    if not master_material:
        log_error("Kann ohne Master Material nicht weitermachen!")
        return

    # ---- PHASE 4: Material Instances erstellen ----
    log("\n--- PHASE 4: Material Instances erstellen ---")

    mi_cache = {}  # texture_key -> MI asset
    mis_created = 0

    with unreal.ScopedSlowTask(len(texture_groups), "Erstelle Material Instances...") as slow_task:
        slow_task.make_dialog(True)

        for tex_key, group in texture_groups.items():
            if slow_task.should_cancel():
                log_warning("Import abgebrochen!")
                return
            slow_task.enter_progress_frame(1, f"MI: {group['mi_name']}")

            # Textur-Assets finden
            diffuse_asset = None
            bump_asset = None

            if group["diffuse"]:
                tex_fn = normalize_texture_path(group["diffuse"])[0].lower()
                diffuse_asset = texture_cache.get(tex_fn)

            if group["bump"]:
                tex_fn = normalize_texture_path(group["bump"])[0].lower()
                bump_asset = texture_cache.get(tex_fn)

            mi = create_material_instance(
                group["mi_name"],
                master_material,
                diffuse_asset,
                bump_asset
            )

            if mi:
                mi_cache[tex_key] = mi
                mis_created += 1

    log(f"Material Instances erstellt: {mis_created}")

    # ---- PHASE 5: Meshes importieren und Materials zuweisen ----
    log("\n--- PHASE 5: Meshes importieren ---")

    # Sammle alle einzigartigen OBJ-Pfade
    unique_objs = {}  # obj_path -> subfolder
    for tex_key, group in texture_groups.items():
        for obj_path, subfolder, slot_idx in group["meshes"]:
            if obj_path not in unique_objs:
                unique_objs[obj_path] = subfolder

    meshes_imported = 0
    materials_assigned = 0

    with unreal.ScopedSlowTask(len(unique_objs), "Importiere Meshes...") as slow_task:
        slow_task.make_dialog(True)

        for obj_path, subfolder in unique_objs.items():
            if slow_task.should_cancel():
                log_warning("Import abgebrochen!")
                return

            obj_name = os.path.splitext(os.path.basename(obj_path))[0]
            slow_task.enter_progress_frame(1, f"Mesh: {obj_name}")

            dest_path = f"{DEST_ROOT}/{subfolder}"
            mesh_asset = import_mesh(obj_path, dest_path)

            if not mesh_asset:
                continue

            meshes_imported += 1

            # Materials zuweisen (fuer jeden Slot)
            for slot_idx in range(len(mesh_asset.static_materials)):
                key = (obj_path, slot_idx)
                tex_key = mesh_material_map.get(key)
                if tex_key and tex_key in mi_cache:
                    assign_material_to_mesh(mesh_asset, mi_cache[tex_key], slot_idx)
                    materials_assigned += 1

            # Mesh speichern
            full_asset_path = f"{dest_path}/{obj_name}"
            unreal.EditorAssetLibrary.save_asset(full_asset_path)

    # ---- ZUSAMMENFASSUNG ----
    log("\n" + "=" * 60)
    log("IMPORT ABGESCHLOSSEN!")
    log("=" * 60)
    log(f"  Texturen importiert:  {textures_imported}")
    log(f"  Texturen fehlend:     {textures_missing}")
    log(f"  Master Material:      {MASTER_MATERIAL_PATH}")
    log(f"  Material Instances:   {mis_created}")
    log(f"  Meshes importiert:    {meshes_imported}")
    log(f"  Materials zugewiesen: {materials_assigned}")
    log("")
    log(f"  Einsparung: {total_materials} einzelne Materials -> {mis_created} MIs")
    log("=" * 60)


# ============================================================
# SCRIPT STARTEN
# ============================================================

if __name__ == "__main__":
    run_import()
else:
    # Wenn ueber UE4 Python Console ausgefuehrt
    run_import()
