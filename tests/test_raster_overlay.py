import io

import numpy as np
import pytest
from PIL import Image

import raster_overlay
from tests.raster_fixtures import ORIGIN, RES, write_geotiff

NODATA = -9999.0


@pytest.fixture()
def tif(tmp_path):
    # Row 0 is north. One nodata cell, one non-positive cell (invalid in mode 'a').
    arr = np.array([[10.0, 100.0, 1000.0], [NODATA, 0.0, 10_000.0]], dtype=np.float32)
    return write_geotiff(tmp_path / "depth_x.tif", arr, nodata=NODATA)


def _rgba(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def test_png_has_the_raster_shape_and_transparent_invalid_pixels(tif):
    rgba = _rgba(raster_overlay.render_png(tif, "a"))

    assert rgba.shape == (2, 3, 4)
    assert rgba[1, 0, 3] == 0  # nodata
    assert rgba[1, 1, 3] == 0  # 0 is not a valid return period
    assert (rgba[0, :, 3] == 255).all()


def test_mode_a_is_reversed_viridis_so_short_periods_are_yellow(tif):
    rgba = _rgba(raster_overlay.render_png(tif, "a"))

    shortest, longest = rgba[0, 0, :3].astype(int), rgba[1, 2, :3].astype(int)
    assert shortest[0] + shortest[1] > longest[0] + longest[1]  # yellow vs purple


def test_mode_b_counts_zero_as_a_valid_value(tif):
    rgba = _rgba(raster_overlay.render_png(tif, "b"))

    assert rgba[1, 1, 3] == 255
    assert rgba[1, 0, 3] == 0


def test_raster_without_valid_pixels_renders_transparent_and_has_no_description(tmp_path):
    empty = write_geotiff(tmp_path / "e.tif", np.full((2, 2), NODATA, dtype=np.float32), NODATA)

    assert (_rgba(raster_overlay.render_png(empty, "a"))[..., 3] == 0).all()
    assert raster_overlay.describe(empty, "a", "depth") is None


def test_hover_grid_is_little_endian_float32_with_nan_for_nodata(tif):
    grid = np.frombuffer(raster_overlay.hover_grid(tif), dtype="<f4").reshape(2, 3)

    assert grid[0].tolist() == [10.0, 100.0, 1000.0]
    assert np.isnan(grid[1, 0])
    assert grid[1, 2] == 10_000.0


def test_describe_mode_a(tif):
    description = raster_overlay.describe(tif, "a", "depth", threshold=0.25)

    assert description["label"] == "Fliesstiefe ≥ 0.25 m, Wiederkehrperiode"
    assert (description["unit"], description["log_scale"]) == ("Jahre", True)
    assert (description["vmin_label"], description["vmid_label"], description["vmax_label"]) == (
        "10",
        "316",
        "10'000",
    )
    assert description["hover"] == {
        "width": 3,
        "height": 2,
        "xmin": ORIGIN[0],
        "ymax": ORIGIN[1],
        "res": RES,
    }
    assert description["hover_caption"] is None
    assert description["gradient"].startswith("#fde725 0%")  # viridis_r starts yellow


def test_describe_mode_b(tif):
    description = raster_overlay.describe(tif, "b", "velocity", return_period=300)

    assert description["label"] == "Fliessgeschwindigkeit bei Wiederkehrperiode 300 Jahre"
    assert (description["unit"], description["log_scale"]) == ("m/s", False)
    assert (description["vmin_label"], description["vmax_label"]) == ("0.00", "10'000.00")


def test_legend_numbers_follow_the_session_language(tif, french_session):
    mode_a = raster_overlay.describe(tif, "a", "pressure", threshold=100.0)
    mode_b = raster_overlay.describe(tif, "b", "depth", return_period=10_000)
    assert mode_a["label"] == "[FR] [FR] Druck ≥ 100 kN/m², Wiederkehrperiode"
    assert mode_b["label"] == "[FR] [FR] Fliesstiefe bei Wiederkehrperiode 10 000 Jahre"
    assert raster_overlay.describe(tif, "a", "depth", threshold=0.25)["label"].startswith(
        "[FR] [FR] Fliesstiefe ≥ 0,25 m"
    )


def test_corners_are_tl_tr_br_bl_in_wgs84(tif):
    (tl, tr, br, bl) = raster_overlay.describe(tif, "b", "depth")["corners"]

    assert tl[1] > bl[1] and tr[1] > br[1]  # north on top
    assert tr[0] > tl[0] and br[0] > bl[0]  # east to the right
    assert 7.4 < tl[0] < 7.5 and 46.9 < tl[1] < 47.0  # LV95 2'600'000/1'200'000 is Bern


def test_hover_is_dropped_past_the_pixel_cap(tif, monkeypatch):
    monkeypatch.setattr(raster_overlay, "HOVER_GRID_MAX_PIXELS", 5)

    description = raster_overlay.describe(tif, "b", "depth")

    assert description["hover"] is None
    assert (
        description["hover_caption"]
        == "Pixelwerte beim Überfahren nur bis 5 Pixel (dieses Gebiet: 6 Pixel)."
    )
