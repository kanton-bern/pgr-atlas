import pytest

import anriss_map_component
import gebaeudeschatten_map_component
import ifk_map_component
import overview_component
import raster_bbox_component


def test_missing_build_fails_with_the_command_that_fixes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(overview_component, "_FRONTEND_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="npm run build"):
        overview_component.maplibre_overview(center_lat=46.8, center_lon=7.5, pmtiles_port=8505)


def test_missing_ifk_build_fails_with_the_command_that_fixes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ifk_map_component, "_FRONTEND_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="npm run build"):
        ifk_map_component.ifk_pixel_map(center_lat=46.8, center_lon=7.5)


def test_missing_raster_build_fails_with_the_command_that_fixes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(raster_bbox_component, "_FRONTEND_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="npm run build"):
        raster_bbox_component.raster_bbox_map(center_lat=46.8, center_lon=7.5)


def test_missing_anriss_build_fails_with_the_command_that_fixes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(anriss_map_component, "_FRONTEND_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="npm run build"):
        anriss_map_component.anriss_result_map(
            bounds=[[46.6, 7.6], [46.61, 7.61]],
            cells_geojson=None,
            cells_version="v1",
            cells_label="Fliesstiefe",
            legend=None,
            overlays=[],
            variables=[],
            active_variable="depth",
        )


def test_missing_gebaeudeschatten_build_fails_with_the_command_that_fixes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(gebaeudeschatten_map_component, "_FRONTEND_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="npm run build"):
        gebaeudeschatten_map_component.gebaeudeschatten_map(
            bounds=[[46.6, 7.6], [46.61, 7.61]], layers={}, servers={}
        )
