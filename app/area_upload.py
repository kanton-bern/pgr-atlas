"""The sidebar's file upload of an area (GeoJSON, KML, GeoParquet, Shapefile),
for the views that compute over a drawn or uploaded area.

Parsing and validation live in polygon_upload.py. An upload produces the same
{'type': 'polygon', 'ring': [[E, N], ...]} selection the map's rectangle and
polygon tools do, so nothing downstream needs to know where a selection came
from.

A view names its session keys by a prefix ("_raster"): the selection is
"<prefix>_selection", the upload's state "<prefix>_upload_state", and the
widgets' keys start with "<prefix>_upload".
"""

import geopandas as gpd
import streamlit as st

import ui_text
from polygon_upload import UPLOAD_EXTENSIONS, extract_uploaded_polygon
from ui_common import LV95_PLAUSIBLE_BOUNDS

# Old Swiss data still turns up in LV03 fairly often; GeoJSON's own spec
# default is WGS84. Offered explicitly (not guessed from coordinate magnitude
# -- LV03/LV95 ranges can be ambiguous close to their shared origin) only
# when a file doesn't declare its own CRS.
_UPLOAD_CRS_CHOICES = {
    "WGS84 (EPSG:4326)": 4326,
    "LV95 (EPSG:2056)": 2056,
    "LV03 (EPSG:21781)": 21781,
}

# Simplify only past this many vertices, so the component channel and the
# ST_Contains WKT stay small whatever the file. preserve_topology=True keeps
# the result valid, so the tolerance isn't a hard bound: tested on 8 random
# wiggly polygons (800 vertices each), the deviation stayed under ~1.0 m, a 5x
# margin under the 5 m gold pixel grid. tolerance=2.0 measured up to ~2.5 m.
_UPLOAD_SIMPLIFY_VERTEX_THRESHOLD = 500
_UPLOAD_SIMPLIFY_TOLERANCE_M = 1.0


def ring_in_switzerland(ring) -> bool:
    """True if every point of the REPROJECTED ring lies in a generous LV95
    box around Switzerland (LV95_PLAUSIBLE_BOUNDS). It catches both a missing
    crs and a wrong one: RFC 7946 makes GDAL's GeoJSON driver report
    EPSG:4326 for a file without a crs member, even when the numbers are LV95
    (confirmed with a test file). Both give implausible LV95 coordinates, so
    the user is asked instead of getting a garbage area."""
    xmin, ymin, xmax, ymax = LV95_PLAUSIBLE_BOUNDS
    return all(xmin <= east <= xmax and ymin <= north <= ymax for east, north in ring)


def _uploaded_files_identity(files) -> str:
    """Stable identity for a set of UploadedFile objects: tells "the same
    upload as last rerun" (skip re-parsing) from "a new one, even of an
    identical file" (re-parse).

    Keyed on Streamlit's per-upload file_id, not on the file's content.
    Removing a file and attaching the same bytes again is a new upload, which
    a content hash can't tell from a file still sitting in the uploader: that
    silently ate a re-upload after the selection was deleted on the map. It
    also means "Löschen" and "Zurücksetzen" don't need to clear the upload
    state: a still-attached file keeps looking processed (the reset sticks),
    and a real re-upload gets a new file_id."""
    return "|".join(sorted(uploaded.file_id for uploaded in files))


def finalize_uploaded_polygon(polygon, crs) -> dict:
    """geom: shapely Polygon in `crs`. Returns the unified selection shape,
    reprojected to LV95 and simplified if it has an unusually large number
    of vertices (see _UPLOAD_SIMPLIFY_VERTEX_THRESHOLD)."""
    polygon_lv95 = gpd.GeoSeries([polygon], crs=crs).to_crs(2056).iloc[0]
    if len(polygon_lv95.exterior.coords) > _UPLOAD_SIMPLIFY_VERTEX_THRESHOLD:
        polygon_lv95 = polygon_lv95.simplify(_UPLOAD_SIMPLIFY_TOLERANCE_M, preserve_topology=True)
    ring = [list(point) for point in polygon_lv95.exterior.coords]
    return {"type": "polygon", "ring": ring}


def reset_widget(prefix: str):
    """Empties the uploader. The widget can't be emptied through session_state
    (Streamlit raises for a file_uploader), so its key's generation is bumped
    and it remounts empty."""
    generation_key = f"{prefix}_upload_widget_gen"
    st.session_state[generation_key] = st.session_state.get(generation_key, 0) + 1


def expander(prefix: str):
    """The file upload, collapsed: an alternative to drawing, and the
    uploader takes space even when empty. Not in an st.form, so an upload
    updates the map at once, like a finished drawing."""
    with st.sidebar.expander(ui_text.t("upload.expander")):
        files = st.file_uploader(
            ui_text.t("upload.label"),
            accept_multiple_files=True,
            type=[extension.lstrip(".") for extension in UPLOAD_EXTENSIONS],
            key=f"{prefix}_upload_{st.session_state.get(f'{prefix}_upload_widget_gen', 0)}",
        )
        if not files:
            return
        upload_id = _uploaded_files_identity(files)
        state = st.session_state.get(f"{prefix}_upload_state")
        if state is None or state["upload_id"] != upload_id:
            # A new upload, not a rerun with the same file still attached:
            # parse it once.
            state = _parse_upload(prefix, files, upload_id)
            st.session_state[f"{prefix}_upload_state"] = state
            if state["status"] == "done":
                st.rerun()
        _upload_status(prefix, state, upload_id)


def _parse_upload(prefix: str, files, upload_id: str) -> dict:
    """Parses an upload; selects its polygon if it lands in Switzerland.
    Returns the upload state: status 'done', 'error' or 'pending_crs'."""
    polygon, crs, error = extract_uploaded_polygon(files)
    if error:
        return {"upload_id": upload_id, "status": "error", "error": error}
    selection = finalize_uploaded_polygon(polygon, crs) if crs is not None else None
    if selection is not None and ring_in_switzerland(selection["ring"]):
        st.session_state[f"{prefix}_selection"] = selection
        return {"upload_id": upload_id, "status": "done"}
    # No crs at all, or one that puts the polygon outside Switzerland (see
    # ring_in_switzerland): ask for it.
    return {"upload_id": upload_id, "status": "pending_crs", "geom": polygon, "crs": crs}


def _crs_hint(state: dict) -> str:
    """Why the upload needs a CRS, in the language shown now: the state keeps
    what happened, not the text."""
    if state.get("retried"):
        return ui_text.t("app.warning", text=ui_text.t("upload.crs_still_outside"))
    if state.get("crs") is not None:
        return ui_text.t("app.warning", text=ui_text.t("upload.crs_outside", crs=state["crs"]))
    return ui_text.t("upload.crs_missing")


def _upload_status(prefix: str, state: dict, upload_id: str):
    if state["status"] == "error":
        st.error(ui_text.t("app.warning", text=state["error"]))
    elif state["status"] == "done":
        # On every rerun while this upload is current: the st.rerun() right
        # after parsing would wipe a one-off message before it's seen.
        st.success(ui_text.t("upload.done"))
    elif state["status"] == "pending_crs":
        st.warning(_crs_hint(state))
        _crs_picker(prefix, state, upload_id)


def _crs_picker(prefix: str, state: dict, upload_id: str):
    label = st.selectbox(
        ui_text.t("upload.crs_select"),
        list(_UPLOAD_CRS_CHOICES),
        key=f"{prefix}_upload_crs_choice",
    )
    if not st.button(
        ui_text.t("upload.crs_apply"), key=f"{prefix}_upload_crs_confirm", width="stretch"
    ):
        return
    selection = finalize_uploaded_polygon(state["geom"], _UPLOAD_CRS_CHOICES[label])
    if ring_in_switzerland(selection["ring"]):
        st.session_state[f"{prefix}_selection"] = selection
        st.session_state[f"{prefix}_upload_state"] = {"upload_id": upload_id, "status": "done"}
    else:
        # A wrong guess stays pending (with its polygon, so no re-upload is
        # needed): the user can try another choice.
        st.session_state[f"{prefix}_upload_state"] = {
            "upload_id": upload_id,
            "status": "pending_crs",
            "geom": state["geom"],
            "retried": True,
        }
    st.rerun()
