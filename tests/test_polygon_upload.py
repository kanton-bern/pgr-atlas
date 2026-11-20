"""Tests for polygon_upload: upload name checks, ZIP limits, and parsing."""

import io
import json
import sys
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

import polygon_upload
import ui_text
from polygon_upload import extract_uploaded_polygon

_SQUARE = [[8.0, 47.0], [8.1, 47.0], [8.1, 47.1], [8.0, 47.1], [8.0, 47.0]]


class _UploadedFile:
    """The part of Streamlit's UploadedFile that extract_uploaded_polygon uses."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _geojson(*geometries: dict) -> bytes:
    features = [{"type": "Feature", "geometry": g, "properties": {}} for g in geometries]
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def _zip(entries: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _shapefile_entries(tmp_path) -> dict[str, bytes]:
    """A one-polygon Shapefile bundle with a text attribute, as real exports have."""
    features = gpd.GeoDataFrame(
        {"name": ["Gebiet Adelboden"]}, geometry=[Polygon(_SQUARE)], crs="EPSG:2056"
    )
    features.to_file(tmp_path / "gebiet.shp")
    return {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.stem == "gebiet"}


@pytest.mark.parametrize("name", ["../../etc/passwd", "sub/gebiet.geojson", "", ".", ".."])
def test_unsafe_name_is_rejected(name):
    upload = _UploadedFile(name, _geojson({"type": "Polygon", "coordinates": [_SQUARE]}))

    extracted, _, error = extract_uploaded_polygon([upload])

    assert extracted is None
    assert "Ungültiger Dateiname" in error


def test_unsafe_name_in_shapefile_bundle_is_rejected():
    files = [_UploadedFile("gebiet.shp", b""), _UploadedFile("../gebiet.dbf", b"")]

    _, _, error = extract_uploaded_polygon(files)

    assert "Ungültiger Dateiname" in error


def test_zip_with_too_many_entries_is_rejected():
    entries = {f"e{i}.txt": b"x" for i in range(polygon_upload._ZIP_MAX_ENTRIES + 1)}

    _, _, error = extract_uploaded_polygon([_UploadedFile("a.zip", _zip(entries))])

    assert "Einträge" in error


def test_zip_at_entry_limit_is_unpacked():
    entries = {f"e{i}.txt": b"x" for i in range(polygon_upload._ZIP_MAX_ENTRIES)}

    _, _, error = extract_uploaded_polygon([_UploadedFile("a.zip", _zip(entries))])

    assert "keine .shp-Datei" in error


def test_zip_over_total_size_is_rejected(monkeypatch):
    monkeypatch.setattr(polygon_upload, "_ZIP_MAX_TOTAL_BYTES", 1000)
    entries = {"a.bin": b"a" * 600, "b.bin": b"b" * 600}
    # The limit is checked in the parser's child process, which a monkeypatch
    # can't reach -- so the check itself, on this ZIP's directory.
    with zipfile.ZipFile(io.BytesIO(_zip(entries, zipfile.ZIP_STORED))) as archive:
        error = polygon_upload._zip_limit_error(archive.infolist())

    assert "MB" in error and "entpackt" in error


def test_zip_bomb_entry_is_rejected():
    bomb = _zip({"bomb.bin": b"\0" * 1_000_000})

    _, _, error = extract_uploaded_polygon([_UploadedFile("a.zip", bomb)])

    assert "Kompressionsverhältnis" in error
    assert "bomb.bin" in error


def test_corrupt_zip_is_rejected():
    _, _, error = extract_uploaded_polygon([_UploadedFile("a.zip", b"not a zip")])

    assert "ZIP-Datei ist beschädigt" in error


def test_geojson_polygon_is_accepted():
    polygon = {"type": "Polygon", "coordinates": [_SQUARE]}
    upload = _UploadedFile("gebiet.geojson", _geojson(polygon))

    extracted, crs, error = extract_uploaded_polygon([upload])

    assert error is None
    assert extracted.geom_type == "Polygon"
    assert crs.to_epsg() == 4326


def test_geojson_with_two_features_is_rejected():
    polygon = {"type": "Polygon", "coordinates": [_SQUARE]}
    upload = _UploadedFile("gebiet.geojson", _geojson(polygon, polygon))

    _, _, error = extract_uploaded_polygon([upload])

    assert "2 Objekte" in error


def _geoparquet(compression: str) -> bytes:
    features = gpd.GeoDataFrame({"name": ["Gebiet"]}, geometry=[Polygon(_SQUARE)], crs="EPSG:4326")
    buffer = io.BytesIO()
    features.to_parquet(buffer, compression=compression)
    return buffer.getvalue()


def test_zstd_geoparquet_is_accepted():
    upload = _UploadedFile("gebiet.geoparquet", _geoparquet("zstd"))

    extracted, crs, error = extract_uploaded_polygon([upload])

    assert error is None
    assert extracted.geom_type == "Polygon"
    assert crs.to_epsg() == 4326


def test_brotli_geoparquet_is_rejected_before_decompression():
    upload = _UploadedFile("gebiet.parquet", _geoparquet("brotli"))

    extracted, _, error = extract_uploaded_polygon([upload])

    assert extracted is None
    assert error == ui_text.t("upload.parquet_brotli")


def test_parquet_extension_without_parquet_content_is_rejected():
    extracted, _, error = extract_uploaded_polygon([_UploadedFile("gebiet.parquet", _geojson())])

    assert extracted is None
    assert error == ui_text.t("upload.wrong_format")


def test_zipped_shapefile_is_accepted(tmp_path):
    upload = _UploadedFile("gebiet.zip", _zip(_shapefile_entries(tmp_path)))

    extracted, crs, error = extract_uploaded_polygon([upload])

    assert error is None
    assert extracted.geom_type == "Polygon"
    assert crs.to_epsg() == 2056


def test_loose_shapefile_bundle_is_accepted(tmp_path):
    files = [_UploadedFile(n, data) for n, data in _shapefile_entries(tmp_path).items()]

    extracted, _, error = extract_uploaded_polygon(files)

    assert error is None
    assert extracted.geom_type == "Polygon"


def test_shapefile_polygon_z_loses_its_height(tmp_path):
    """ArcGIS exports areas as PolygonZ; the selection ring is [E, N] only."""
    square_z = [(e, n, 0.0) for e, n in _SQUARE]
    gpd.GeoDataFrame(geometry=[Polygon(square_z)], crs="EPSG:3857").to_file(tmp_path / "z.shp")
    entries = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.stem == "z"}

    extracted, _, error = extract_uploaded_polygon([_UploadedFile("z.zip", _zip(entries))])

    assert error is None
    assert not extracted.has_z
    assert {tuple(p) for p in extracted.exterior.coords} == {tuple(p) for p in _SQUARE}


def test_kml_polygon_with_altitude_loses_its_height():
    kml = (
        b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Polygon>'
        b"<outerBoundaryIs><LinearRing><coordinates>8,47,1350 8.1,47,1350 8.1,47.1,1350 "
        b"8,47.1,1350 8,47,1350</coordinates></LinearRing></outerBoundaryIs></Polygon>"
        b"</Placemark></kml>"
    )

    extracted, _, error = extract_uploaded_polygon([_UploadedFile("gebiet.kml", kml)])

    assert error is None
    assert not extracted.has_z


# ── Only what the extension says is handed to GDAL ──────────────────────────


def _secret_vrt(tmp_path) -> bytes:
    """An OGR VRT that makes GDAL read a file elsewhere on the server -- what
    an attacker would upload under an innocent name."""
    secret = tmp_path / "secret.csv"
    secret.write_text('WKT,secret\n"POLYGON ((8 47, 8.1 47, 8.1 47.1, 8 47.1, 8 47))",s3cr3t\n')
    return (
        f'<OGRVRTDataSource><OGRVRTLayer name="secret"><SrcDataSource>{secret}</SrcDataSource>'
        f'<GeometryField encoding="WKT" field="WKT"/></OGRVRTLayer></OGRVRTDataSource>'
    ).encode()


def test_vrt_would_read_server_files_if_handed_to_gdal(tmp_path):
    # Why the content check exists: GDAL opens a VRT whatever it's called.
    disguised = tmp_path / "gebiet.geojson"
    disguised.write_bytes(_secret_vrt(tmp_path))
    assert gpd.read_file(disguised)["secret"].tolist() == ["s3cr3t"]


@pytest.mark.parametrize("name", ["gebiet.geojson", "gebiet.json", "gebiet.kml", "gebiet.shp"])
def test_vrt_under_an_allowed_name_is_rejected(tmp_path, name):
    extracted, crs, error = extract_uploaded_polygon([_UploadedFile(name, _secret_vrt(tmp_path))])
    assert extracted is None and error is not None


def test_vrt_inside_a_zip_is_rejected(tmp_path):
    extracted, _, error = extract_uploaded_polygon(
        [_UploadedFile("gebiet.zip", _zip({"gebiet.shp": _secret_vrt(tmp_path)}))]
    )
    assert extracted is None and error is not None


@pytest.mark.parametrize("name", ["gebiet.vrt", "gebiet.gml", "gebiet.csv", "gebiet.gpkg"])
def test_other_extensions_are_rejected(name):
    extracted, _, error = extract_uploaded_polygon([_UploadedFile(name, b"x")])
    assert extracted is None and "nicht unterstützt" in error


def test_object_without_geometry_is_named_empty():
    extracted, _, error = extract_uploaded_polygon(
        [_UploadedFile("gebiet.geojson", _geojson(None))]
    )
    assert extracted is None
    assert error == (
        "Geometrietyp „leer“ wird nicht unterstützt - es wird genau ein Polygon erwartet."
    )


def test_lone_shapefile_sidecar_is_rejected(tmp_path):
    extracted, _, error = extract_uploaded_polygon(
        [_UploadedFile("gebiet.dbf", _secret_vrt(tmp_path))]
    )
    assert extracted is None and "nicht allein" in error


def test_kml_polygon_is_accepted():
    kml = (
        b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Polygon>'
        b"<outerBoundaryIs><LinearRing><coordinates>8,47 8.1,47 8.1,47.1 8,47.1 8,47</coordinates>"
        b"</LinearRing></outerBoundaryIs></Polygon></Placemark></kml>"
    )
    extracted, crs, error = extract_uploaded_polygon([_UploadedFile("gebiet.kml", kml)])
    assert error is None and extracted.geom_type == "Polygon"


def _kml_with_doctype(doctype: str, name: str) -> bytes:
    return (
        f'<?xml version="1.0"?>{doctype}<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark>'
        f"<name>{name}</name><Polygon><outerBoundaryIs><LinearRing><coordinates>"
        "8,47 8.1,47 8.1,47.1 8,47.1 8,47</coordinates></LinearRing></outerBoundaryIs>"
        "</Polygon></Placemark></kml>"
    ).encode()


def test_kml_with_external_entity_is_rejected(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cr3t")
    kml = _kml_with_doctype(f'<!DOCTYPE kml [<!ENTITY x SYSTEM "file://{secret}">]>', "&x;")
    extracted, _, error = extract_uploaded_polygon([_UploadedFile("gebiet.kml", kml)])
    assert extracted is None and error == ui_text.t("upload.wrong_format")


def test_kml_with_entity_bomb_is_rejected():
    entities = '<!ENTITY a "aaaaaaaaaa">' + "".join(
        f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(8)
    )
    kml = _kml_with_doctype(f"<!DOCTYPE kml [{entities}]>", "&i;")
    extracted, _, error = extract_uploaded_polygon([_UploadedFile("gebiet.kml", kml)])
    assert extracted is None and error == ui_text.t("upload.wrong_format")


def test_kml_doctype_is_found_in_utf16():
    # Not a byte search for "<!DOCTYPE": the parser sees it in any encoding.
    kml = (
        _kml_with_doctype("<!DOCTYPE kml>", "Gebiet")
        .decode()
        .replace('version="1.0"', 'version="1.0" encoding="UTF-16"')
    )
    extracted, _, error = extract_uploaded_polygon(
        [_UploadedFile("gebiet.kml", kml.encode("utf-16"))]
    )
    assert extracted is None and error == ui_text.t("upload.wrong_format")


def test_upload_leaves_nothing_behind(tmp_path):
    import work_dirs

    extract_uploaded_polygon(
        [_UploadedFile("gebiet.geojson", _geojson({"type": "Polygon", "coordinates": [_SQUARE]}))]
    )
    extract_uploaded_polygon([_UploadedFile("gebiet.geojson", b"not json")])
    assert list(work_dirs.kind_dir(work_dirs.UPLOADS).iterdir()) == []


# ── The parser runs fenced ──────────────────────────────────────────────────


def test_parser_crash_or_runaway_is_contained(monkeypatch):
    # 100k-deep JSON makes the parser raise RecursionError: the child dies,
    # the app gets a plain message.
    extracted, _, error = extract_uploaded_polygon(
        [_UploadedFile("d.geojson", b'{"type":' + b"[" * 100_000 + b"]" * 100_000 + b"}")]
    )
    assert extracted is None and "zu gross" in error

    monkeypatch.setattr(polygon_upload, "_WALL_TIMEOUT_S", 0.01)
    extracted, _, error = extract_uploaded_polygon(
        [_UploadedFile("gebiet.geojson", _geojson({"type": "Polygon", "coordinates": [_SQUARE]}))]
    )
    assert extracted is None and "zu gross" in error


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="macOS refuses RLIMIT_AS; the memory cap applies on Linux",
)
def test_parser_memory_is_capped(monkeypatch):
    # A cap below what the child needs to even import geopandas: it runs out
    # of memory, and that stays inside the child.
    import subprocess

    real_run = subprocess.run

    def run_with_smaller_cap(command, **kwargs):
        kwargs["env"] = {**kwargs["env"], "POLYGON_UPLOAD_MEM_LIMIT": str(300 * 1024**2)}
        return real_run(command, **kwargs)

    monkeypatch.setattr(polygon_upload.subprocess, "run", run_with_smaller_cap)
    extracted, _, error = extract_uploaded_polygon(
        [_UploadedFile("gebiet.geojson", _geojson({"type": "Polygon", "coordinates": [_SQUARE]}))]
    )
    # Killed while importing, or a MemoryError while reading -- either way a message.
    assert extracted is None and error in (
        ui_text.t("upload.too_big"),
        ui_text.t("upload.unreadable"),
    )


def test_parser_gets_no_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("PROBE_S3_SECRET_ACCESS_KEY", "s3cr3t")
    import subprocess

    seen = {}
    real_run = subprocess.run

    def spy(command, **kwargs):
        seen.update(kwargs["env"])
        return real_run(command, **kwargs)

    monkeypatch.setattr(polygon_upload.subprocess, "run", spy)
    extracted, _, error = extract_uploaded_polygon(
        [_UploadedFile("gebiet.geojson", _geojson({"type": "Polygon", "coordinates": [_SQUARE]}))]
    )
    assert error is None and extracted.geom_type == "Polygon"
    assert not any("S3" in k or "AWS" in k or "SECRET" in k for k in seen)


# ── Limits the OS refuses ──────────────────────────────────────────────


class _RefusesMemoryLimit:
    """Stands in for `resource`: records limits, refuses RLIMIT_AS like macOS."""

    def __init__(self):
        import resource

        self.RLIMIT_AS, self.RLIMIT_CPU = resource.RLIMIT_AS, resource.RLIMIT_CPU
        self.RLIMIT_FSIZE, self.RLIMIT_CORE = resource.RLIMIT_FSIZE, resource.RLIMIT_CORE
        self.set = []

    def setrlimit(self, limit, values):
        if limit == self.RLIMIT_AS:
            raise ValueError("current limit exceeds maximum limit")
        self.set.append(limit)


@pytest.mark.parametrize("platform, parses", [("darwin", True), ("linux", False)])
def test_refused_memory_limit_is_skipped_only_on_macos(monkeypatch, platform, parses):
    fake = _RefusesMemoryLimit()
    monkeypatch.setitem(__import__("sys").modules, "resource", fake)
    monkeypatch.setattr(polygon_upload.sys, "platform", platform)
    if parses:
        polygon_upload._set_child_limits()
        assert fake.set == [
            fake.RLIMIT_CPU,
            fake.RLIMIT_FSIZE,
            fake.RLIMIT_CORE,
        ]  # the rest still applies
    else:
        with pytest.raises(ValueError):
            polygon_upload._set_child_limits()
