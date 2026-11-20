"""Polygon file upload for the Raster-Karten view: GeoJSON, KML, GeoParquet and
Shapefile (zipped, or as loose .shp/.shx/.dbf/... files).

Lives outside app.py so it can be unit-tested; app.py runs Streamlit code at
import.

Uploads come from anyone who can reach the app (there is no login), and only
small area files are expected, so parsing is fenced:
- In the app process only the names are checked (plain file names, allowed
  extensions, at most _MAX_FILES) and the files written to a private scratch
  folder (work_dirs), deleted right after parsing.
- Everything that touches the content -- unpacking a ZIP, checking that each
  file is what its extension says (_format_error), reading it with GDAL or
  pyarrow -- runs in a child process (this file run as a script) with a
  minimal environment (no S3 credentials) and hard limits on memory, CPU
  time and written file size, killed after _WALL_TIMEOUT_S. A parser that
  blows up, hangs or crashes on a crafted file takes only the child down.
- The child hands back only the polygon (WKB) and its CRS (PROJJSON).
server.maxUploadSize in docker/streamlit_config.toml caps each file (10 MB);
the ZIP limits below cap what a small ZIP may unpack to.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import zipfile
from xml.parsers import expat

import ui_text
import work_dirs

logger = logging.getLogger(__name__)

_MAX_FILES = 20  # a Shapefile bundle has ~8 parts
_ZIP_MAX_ENTRIES = 50
_ZIP_MAX_TOTAL_BYTES = 50 * 1024 * 1024
_ZIP_MAX_RATIO = 20

# The child's limits. The imports alone (geopandas, GDAL, pyarrow) reserve
# ~1 GB of address space and take ~1 s; real area files need a few MB more.
_MEM_LIMIT_BYTES = 2 * 1024**3
_CPU_LIMIT_S = 20
_WALL_TIMEOUT_S = 30
_FILE_SIZE_LIMIT_BYTES = 60 * 1024 * 1024  # any one file the child writes (ZIP entries)


def _safe_name(name: str) -> str | None:
    """Returns name if it is a plain file name, None if it has a directory part
    or is '', '.' or '..'."""
    if name in ("", ".", "..") or os.path.basename(name) != name:
        return None
    return name


def _zip_limit_error(members: list[zipfile.ZipInfo]) -> str | None:
    """Returns a German error message if the ZIP exceeds a limit, else None.

    Uses the sizes from the ZIP's central directory; zipfile never unpacks an
    entry past its declared file_size, so they bound what extractall writes.
    """
    if len(members) > _ZIP_MAX_ENTRIES:
        return ui_text.t(
            "upload.zip_too_many_entries", n_entries=len(members), max_entries=_ZIP_MAX_ENTRIES
        )

    total_size = sum(member.file_size for member in members)
    if total_size > _ZIP_MAX_TOTAL_BYTES:
        return ui_text.t(
            "upload.zip_too_large",
            size_mb=total_size // 2**20,
            max_mb=_ZIP_MAX_TOTAL_BYTES // 2**20,
        )

    for member in members:
        if member.compress_size == 0:
            continue
        ratio = member.file_size / member.compress_size
        if ratio > _ZIP_MAX_RATIO:
            return ui_text.upload_zip_ratio(member.filename, ratio, _ZIP_MAX_RATIO)
    return None


# What can be uploaded. GDAL recognizes formats by CONTENT, not by extension,
# and some of its formats point at other files or URLs (an OGR VRT can read
# any path on the server or fetch a URL) -- so a file is only handed to GDAL
# once its content matches its extension (_format_error). GeoParquet is read
# by pyarrow, not GDAL.
SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx", ".xml")
UPLOAD_EXTENSIONS = (
    ".geojson",
    ".json",
    ".kml",
    ".parquet",
    ".geoparquet",
    ".zip",
) + SHAPEFILE_PARTS
# The files that are actually opened -- each one checked by _format_error.
_READABLE = (".geojson", ".json", ".kml", ".parquet", ".geoparquet", ".shp")
_SHP_MAGIC = b"\x00\x00\x27\x0a"  # ESRI Shapefile file code 9994, big-endian


def _format_error(path: str) -> str | None:
    """None if the file at path is what its extension says, else a German
    error message. Only the file GDAL will open is checked (a Shapefile's
    .shp; its sidecars are only read by the Shapefile driver)."""
    lower = path.lower()
    try:
        if lower.endswith((".geojson", ".json")):
            with open(path, "rb") as file:
                doc = json.load(file)
            if not isinstance(doc, dict) or "type" not in doc:
                return ui_text.t("upload.not_geojson")
        elif lower.endswith(".kml"):
            if _kml_root(path).rsplit("}", 1)[-1] != "kml":
                return ui_text.t("upload.not_kml")
        elif lower.endswith(".shp"):
            with open(path, "rb") as file:
                if file.read(4) != _SHP_MAGIC:
                    return ui_text.t("upload.not_shapefile")
        elif lower.endswith((".parquet", ".geoparquet")):
            if "BROTLI" in _parquet_codecs(path):
                return ui_text.t("upload.parquet_brotli")
    except (ValueError, expat.ExpatError, UnicodeDecodeError):
        return ui_text.t("upload.wrong_format")
    return None


def _parquet_codecs(path: str) -> set[str]:
    """The compression codecs of every column chunk, from the footer alone
    (it is never compressed), so nothing is decompressed to find them out.
    Brotli is refused until pyarrow's embedded decoder is patched for
    CVE-2026-111497. Not a Parquet file: pyarrow raises ArrowInvalid,
    a ValueError."""
    import pyarrow.parquet as pq

    metadata = pq.ParquetFile(path).metadata
    return {
        metadata.row_group(row_group).column(column).compression
        for row_group in range(metadata.num_row_groups)
        for column in range(metadata.num_columns)
    }


def _kml_root(path: str) -> str:
    """The root element's name, after parsing the whole file. A DOCTYPE raises
    ValueError: KML needs none, and refusing it here keeps entity tricks (XXE,
    expansion bombs) from depending on the Expat version of either this Python
    or the GDAL that reads the file next."""
    root: list[str] = []

    def _refuse_doctype(*_args):
        raise ValueError("DOCTYPE in KML")

    def _start(name, _attrs):
        if not root:
            root.append(name)

    parser = expat.ParserCreate(namespace_separator="}")
    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.StartElementHandler = _start
    with open(path, "rb") as file:
        parser.ParseFile(file)
    return root[0]


def _find_file_by_suffix(root: str, suffix: str) -> str | None:
    for dirpath, _dirs, filenames in os.walk(root):
        for filename in filenames:
            if filename.lower().endswith(suffix):
                return os.path.join(dirpath, filename)
    return None


def extract_uploaded_polygon(files) -> tuple[object | None, object | None, str | None]:
    """files: list of Streamlit UploadedFile objects (one file, or several --
    a loose Shapefile sidecar bundle). Returns (shapely Polygon in its
    ORIGINAL crs, crs-or-None, error-or-None) -- reprojection happens
    separately (finalize_uploaded_polygon in area_upload.py) since a missing crs needs
    a round-trip through the sidebar to ask the user, not a hard failure here.

    Every format goes through a real temp directory (not read straight from
    the in-memory upload buffer): ESRI Shapefile can't be read from bytes
    (GDAL locates .shx/.dbf/.prj as real sibling files next to the .shp), and
    the fenced child process needs files anyway."""
    if len(files) > _MAX_FILES:
        return (
            None,
            None,
            ui_text.t("upload.too_many_files", n_files=len(files), max_files=_MAX_FILES),
        )
    for uploaded in files:
        if _safe_name(uploaded.name) is None:
            return None, None, ui_text.t("upload.bad_name", name=uploaded.name)
        if not uploaded.name.lower().endswith(UPLOAD_EXTENSIONS):
            return None, None, ui_text.t("upload.unsupported_type", name=uploaded.name)

    with tempfile.TemporaryDirectory(dir=work_dirs.kind_dir(work_dirs.UPLOADS)) as folder:
        for uploaded in files:
            with open(os.path.join(folder, uploaded.name), "wb") as out:
                out.write(uploaded.getvalue())
        result = _run_fenced(folder, [uploaded.name for uploaded in files])
    if result.get("error"):
        return None, None, result["error"]
    import pyproj
    import shapely.wkb

    polygon = shapely.wkb.loads(bytes.fromhex(result["wkb"]))
    crs = pyproj.CRS.from_json(result["crs"]) if result.get("crs") else None
    return polygon, crs, None


def _run_fenced(folder: str, names: list[str]) -> dict:
    """Parses the upload in folder in a limited child process (see module
    docstring); returns its {'wkb', 'crs'} or {'error'}."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": folder,
        "LANG": "C.UTF-8",
        # The system allocator: Arrow's own reserves large address ranges up
        # front, which the address-space limit would count.
        "ARROW_DEFAULT_MEMORY_POOL": "system",
        "OMP_NUM_THREADS": "1",
        "GDAL_NUM_THREADS": "1",
        "PROJ_NETWORK": "OFF",
        # The child's messages in the session's language (it has no session).
        ui_text.PROCESS_LANGUAGE_ENV: ui_text.language(),
    }
    try:
        child = subprocess.run(
            [sys.executable, os.path.abspath(__file__), folder, *names],
            env=env,
            cwd=folder,
            capture_output=True,
            timeout=_WALL_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("polygon upload: parser timed out after %ss", _WALL_TIMEOUT_S)
        return {"error": ui_text.t("upload.too_big")}
    if child.returncode != 0:
        logger.warning(
            "polygon upload: parser exited with %s: %s",
            child.returncode,
            child.stderr.decode(errors="replace")[-2000:],
        )
        return {"error": ui_text.t("upload.too_big")}
    try:
        return json.loads(child.stdout)
    except ValueError:
        logger.warning("polygon upload: parser sent no result")
        return {"error": ui_text.t("upload.too_big")}


def _set_child_limits():
    """Applies the child's limits. macOS can't lower the memory limits
    (RLIMIT_AS/DATA/RSS raise ValueError), so there a limit the OS
    refuses is skipped -- local development only. Everywhere else (the
    Linux pods) a refused limit ends the child: the parse never runs
    unfenced."""
    import resource

    # Tests lower the cap through the environment; it can never be raised.
    memory_limit_bytes = min(
        _MEM_LIMIT_BYTES, int(os.environ.get("POLYGON_UPLOAD_MEM_LIMIT", _MEM_LIMIT_BYTES))
    )
    for limit, value in (
        (resource.RLIMIT_AS, memory_limit_bytes),
        (resource.RLIMIT_CPU, _CPU_LIMIT_S),
        (resource.RLIMIT_FSIZE, _FILE_SIZE_LIMIT_BYTES),
        (resource.RLIMIT_CORE, 0),
    ):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            if sys.platform != "darwin":
                raise
            print(f"limit {limit} not supported on macOS, skipped", file=sys.stderr)


def _parse_folder(folder: str, names: list[str]) -> tuple[object | None, object | None, str | None]:
    """The child's work: (Polygon, crs, error) for the files `names` in folder."""
    import geopandas as gpd
    import shapely

    lower_names = [name.lower() for name in names]
    if len(names) == 1 and lower_names[0].endswith(".zip"):
        extract_dir = os.path.join(folder, "_extracted")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(os.path.join(folder, names[0])) as archive:
                limit_error = _zip_limit_error(archive.infolist())
                if limit_error is not None:
                    return None, None, limit_error
                archive.extractall(extract_dir)
        except zipfile.BadZipFile:
            return None, None, ui_text.t("upload.bad_zip")
        read_path = _find_file_by_suffix(extract_dir, ".shp")
        if read_path is None:
            return None, None, ui_text.t("upload.zip_no_shp")
    elif any(name.endswith(".shp") for name in lower_names):
        shp_name = next(name for name in names if name.lower().endswith(".shp"))
        read_path = os.path.join(folder, shp_name)
    elif len(names) == 1:
        read_path = os.path.join(folder, names[0])
    else:
        return None, None, ui_text.t("upload.files_no_shp")

    if not read_path.lower().endswith(_READABLE):
        return None, None, ui_text.t("upload.shp_part_alone")
    format_error = _format_error(read_path)
    if format_error is not None:
        return None, None, format_error
    try:
        if read_path.lower().endswith((".parquet", ".geoparquet")):
            features = gpd.read_parquet(read_path)
        else:
            features = gpd.read_file(read_path)
    except Exception as error:
        print(f"read failed: {type(error).__name__}: {error}", file=sys.stderr)
        return None, None, ui_text.t("upload.unreadable")

    if len(features) == 0:
        return None, None, ui_text.t("upload.no_geometry")
    if len(features) > 1:
        return None, None, ui_text.t("upload.too_many_objects", n_objects=len(features))
    geometry = features.geometry.iloc[0]
    if geometry is None or geometry.geom_type != "Polygon":
        geom_type = ui_text.t("upload.geometry_empty") if geometry is None else geometry.geom_type
        return None, None, ui_text.t("upload.unsupported_geometry", geom_type=geom_type)
    if len(geometry.interiors) > 0:
        # Silently dropping the hole (i.e. just using geometry.exterior below)
        # would be a quiet WRONG answer, not a missing feature: the excluded
        # area would end up treated as INCLUDED instead. Reject explicitly.
        return None, None, ui_text.t("upload.polygon_with_hole")
    # ArcGIS Shapefiles (PolygonZ) and KML carry a height per vertex. An area
    # has none, and everything downstream takes a ring of [E, N] pairs.
    return shapely.force_2d(geometry), features.crs, None


def _child_main(argv: list[str]) -> None:
    _set_child_limits()
    folder, names = argv[0], argv[1:]
    polygon, crs, error = _parse_folder(folder, names)
    result = (
        {"error": error}
        if error
        else {"wkb": polygon.wkb_hex, "crs": crs.to_json() if crs is not None else None}
    )
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    _child_main(sys.argv[1:])
