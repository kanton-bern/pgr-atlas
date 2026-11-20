"""Raster-Karten overlays: colour one finished raster GeoTIFF for MapLibre's
image source, and read its raw values for the hover readout.

Pure functions of the GeoTIFF on disk, so derivate_bbox_server.py can serve
them per request (/job/<id>/<var>.png, .f32) and views/raster_karten.py can describe the
overlay without holding its bytes. The colouring is its own: it spans this
raster's real min/max, unlike raster_utils (fixed vmin/vmax for the
Raster-Derivate mosaics).

The raster is not reprojected or resampled to Web Mercator: this transforms
just the 4 LV95 corners individually and lets maplibre's GPU warp the
untouched original pixels onto them -- maplibre's image source accepts an
arbitrary quadrilateral, not just an axis-aligned bbox, so this stays exact
even though LV95's axes aren't quite parallel to lon/lat's.

mode 'a' (Wiederkehrperiode, years) colors log-scale reversed viridis
(yellow = short/frequent = higher danger, purple = long/rare), the same
direction as Raster-Derivate's return-period layers (raster_utils._RAMPS
'log'). Unlike Derivate it still spans this
raster's own real min/max, not the fixed 100..100'000 yr domain. mode 'b'
(Intensität) colors linear viridis (yellow = high intensity). Legend titles
match Derivate's: "Fliesstiefe ≥ 0.25 m, Wiederkehrperiode" / "Fliesstiefe
bei Wiederkehrperiode 100 Jahre".
"""

import io

import matplotlib.colors
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from pyproj import Transformer

import ui_text

VARIABLE_UNITS = {"depth": "m", "velocity": "m/s", "pressure": "kN/m²"}

# Hover-value lookup ships the raw grid to the browser as compact binary
# (float32, 4 bytes per pixel), fetched once per variable from the job route,
# not a per-pixel JSON click round-trip to the server -- instant feedback on
# mousemove. The ceiling covers the largest raster a job makes on the stages'
# 8 GiB pods (max_raster_kacheln() = 81 kacheln, about 3.24 M pixels at 5 m)
# and keeps one variable's grid at 16 MB should that cap grow. Measured:
# at 3.24 M pixels the route serves the 13 MB grid in
# 0.03 s and the browser fetches and parses it in 41 ms (localhost), adding
# 13 MB of JS heap. A raster past the ceiling skips hover data (image + legend
# still show, a caption explains the missing readout).
HOVER_GRID_MAX_PIXELS = 4_000_000

_TO_WGS84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)
# The smallest colour span, so a raster of one value doesn't divide by zero.
_MIN_SPAN = 1e-12


def colormap_gradient_css(cmap_obj, steps=10):
    """CSS `linear-gradient` color-stop list ("#hex N%, ...") sampling
    `cmap_obj` evenly -- shared by every value legend in this app (the
    single-anriss view's _legend_html and the Raster-Karten overlay's
    describe) so both stay pixel-identical to the actual colormap without
    duplicating the sampling formula."""
    return ", ".join(
        f"{matplotlib.colors.to_hex(cmap_obj(i / (steps - 1)))} {i * 100 // (steps - 1)}%"
        for i in range(steps)
    )


def _fmt_legend_value(value, mode):
    """mode 'a' (Wiederkehrperiode) values can legitimately extrapolate into
    the billions of years (rare, low-lambda_Ereignis pixels) -- a power of ten
    past 10⁶ keeps the legend readable instead of a wall of digits, and whole
    years otherwise need no decimals. mode 'b' (Intensität) values are small
    physical quantities (depth in m, etc.) where whole numbers would round
    everything to "0" -- 2 decimals instead, matching _legend_html's existing
    depth/velocity/pressure convention."""
    if mode == "a":
        return ui_text.fmt_ch(value, sci_from=1e6)
    return ui_text.fmt_ch(value, digits=2)


def _read(tif_path):
    """Band 1 as float32 with nodata as NaN, plus the raster's bounds and
    pixel size."""
    with rasterio.open(tif_path) as src:
        values = src.read(1).astype(np.float32)
        nodata = src.nodata
        bounds = src.bounds
        pixel_size = float(src.res[0])
    if nodata is not None:
        values[values == nodata] = np.nan
    return values, bounds, pixel_size


def _colour_scale(values, mode):
    """(valid, norm, vmin, vmid, vmax, cmap_name) for one raster, or None if
    it has no valid (non-nodata) pixels at all."""
    valid = np.isfinite(values)
    if mode == "a":
        valid &= values > 0
    if not np.any(valid):
        return None

    if mode == "a":
        log_values = np.log10(values, where=valid, out=np.full_like(values, np.nan))
        log_min = float(np.nanmin(log_values[valid]))
        log_max = float(np.nanmax(log_values[valid]))
        span = max(log_max - log_min, _MIN_SPAN)
        norm = np.zeros_like(values, dtype=np.float32)
        norm[valid] = np.clip((log_values[valid] - log_min) / span, 0, 1)
        vmin, vmax, vmid = 10**log_min, 10**log_max, 10 ** ((log_min + log_max) / 2)
        cmap_name = "viridis_r"
    else:
        vmin, vmax = float(np.nanmin(values[valid])), float(np.nanmax(values[valid]))
        vmid = (vmin + vmax) / 2
        span = max(vmax - vmin, _MIN_SPAN)
        norm = np.zeros_like(values, dtype=np.float32)
        norm[valid] = np.clip((values[valid] - vmin) / span, 0, 1)
        cmap_name = "viridis"
    return valid, norm, vmin, vmid, vmax, cmap_name


def render_png(tif_path, mode) -> bytes:
    """The coloured overlay as PNG bytes. Row 0 is the NORTH edge, matching
    the corner order describe() returns. A raster without valid pixels
    renders fully transparent."""
    values, _, _ = _read(tif_path)
    scale = _colour_scale(values, mode)
    if scale is None:
        valid = np.zeros(values.shape, dtype=bool)
        norm, cmap_name = np.zeros_like(values), "viridis"
    else:
        valid, norm, _, _, _, cmap_name = scale
    rgba = (plt.get_cmap(cmap_name)(norm) * 255).astype(np.uint8)
    rgba[~valid, 3] = 0

    png = io.BytesIO()
    plt.imsave(png, rgba, format="png")
    return png.getvalue()


def hover_grid(tif_path) -> bytes:
    """The raw values, row-major from the north-west corner, as
    little-endian float32 with NaN for nodata. '<f4' matches the byte order
    a JS Float32Array reads on every real deployment target (x86/ARM both
    run little-endian), so nodata gaps read back as NaN in JS too, no
    separate sentinel needed."""
    values, _, _ = _read(tif_path)
    return values.astype("<f4").tobytes()


def describe(tif_path, mode, variable, threshold=None, return_period=None) -> dict | None:
    """Everything the map needs about one overlay except its bytes: the
    WGS84 quad corners, the legend, and the hover grid's geometry.

    Returns None if the raster has no valid (non-nodata) pixels at all.
    Otherwise {corners, gradient, label, unit, log_scale, vmin_label,
    vmid_label, vmax_label, hover, hover_caption}. hover is
    {width, height, xmin, ymax, res} while the raster is within
    HOVER_GRID_MAX_PIXELS, else None with hover_caption explaining why."""
    values, bounds, pixel_size = _read(tif_path)
    scale = _colour_scale(values, mode)
    if scale is None:
        return None
    _, _, vmin, vmid, vmax, cmap_name = scale

    variable_label = ui_text.t(f"variable.{variable}")
    if mode == "a":
        label = ui_text.overlay_label_return_period(
            variable_label, threshold, VARIABLE_UNITS[variable]
        )
        unit, log_scale = ui_text.t("unit.years"), True
    else:
        label = ui_text.overlay_label_intensity(variable_label, return_period)
        unit, log_scale = VARIABLE_UNITS[variable], False

    # TL, TR, BR, BL -- row 0 of the array (and of the PNG render_png
    # writes) is the NORTH edge, matching rasterio's/imsave's shared
    # top-down row convention, so this corner order lines up with the pixels.
    corners_lv95 = [
        (bounds.left, bounds.top),
        (bounds.right, bounds.top),
        (bounds.right, bounds.bottom),
        (bounds.left, bounds.bottom),
    ]
    corners_lonlat = [list(_TO_WGS84.transform(east, north)) for east, north in corners_lv95]

    hover = None
    hover_caption = None
    height, width = values.shape
    if width * height <= HOVER_GRID_MAX_PIXELS:
        hover = {
            "width": width,
            "height": height,
            "xmin": bounds.left,
            "ymax": bounds.top,
            "res": pixel_size,
        }
    else:
        cap = ui_text.fmt_ch(HOVER_GRID_MAX_PIXELS)
        pixels = ui_text.fmt_ch(width * height)
        hover_caption = ui_text.t("overlay.hover_too_large", cap=cap, pixels=pixels)

    return {
        "corners": corners_lonlat,
        "gradient": colormap_gradient_css(plt.get_cmap(cmap_name)),
        "label": label,
        "unit": unit,
        "log_scale": log_scale,
        "hover": hover,
        "hover_caption": hover_caption,
        "vmin_label": _fmt_legend_value(vmin, mode),
        "vmid_label": _fmt_legend_value(vmid, mode),
        "vmax_label": _fmt_legend_value(vmax, mode),
    }
