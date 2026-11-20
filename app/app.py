import contextlib
import logging
import os
import subprocess
import threading
from pathlib import Path

import botocore.exceptions
import streamlit as st
import pmtiles_server
import derivate_bbox_server
import download_gate_component
import footer
import gebaeudeschatten_view
import language
import s3_target
import ui_text
from ui_common import anriss_lookup_form, anriss_query_params
from ui_text import fmt_ch
from views import (
    anriss,
    expert_mode,
    ifk,
    ifk_area,
    legal,
    overview,
    raster_derivate,
    raster_karten,
)

# The data-lake read layer, S3 access and the derivate computations (IFK,
# rasters, event export) come from probe-core, the package this app shares
# with the pipeline (packages/probe-core).
from probe_core.data_lake import data_interface as data
from probe_core.s3 import S3_CONFIG, s3_key_exists
from state import init_session_state


# --- 1. CONFIG & SETUP ---
# Before the first text: every t() below reads the session's language.
language.init_language()
st.set_page_config(
    layout="wide",
    page_title=ui_text.t("app.title", app_name=ui_text.APP_NAME, topic=ui_text.t("app.topic")),
    page_icon=str(Path(__file__).parent / "static" / "logo_2026_small.svg"),
)

st.markdown('<meta name="referrer" content="no-referrer-when-downgrade">', unsafe_allow_html=True)
# Tokens first: app.css uses them, and the map components bundle the same file.
st.html(Path(__file__).parent / "styles" / "tokens.css")
st.html(Path(__file__).parent / "styles" / "app.css")


# Plain per-process memoization (NOT @st.cache_resource) for the gold-
# manifest refresh specifically — its progress callback writes into
# _init_status, a container st.status() below creates fresh every rerun.
# @st.cache_resource "replays" any Streamlit calls made during a cached
# function's execution on later cache-hit reruns, and that replay breaks
# for UI elements the function didn't create itself: CacheReplayClosureError
# ("a streamlit element is called on some layout block created outside the
# function"). So the ACTUAL refresh call below stays a plain, un-decorated
# call, guarded by a lock/cache-dict pair -- but those two objects must
# themselves be true once-per-process singletons, which a plain
# `_gold_manifest_cache = {}` / `threading.Lock()` at file scope does NOT
# give you here: Streamlit reruns a script's ENTIRE top-level code on every
# interaction, for every session, so those two lines re-execute (and
# rebind to brand new objects) on every single rerun -- each concurrent
# rerun ends up with its OWN independent dict and its OWN independent Lock
# instance, which obviously can't serialize against each other. Two
# browser sessions (separate threads, same process) hitting this within
# the same window can both see an empty cache (their OWN empty dict) and
# both call data.refresh_gold_manifest(), racing to INSERT the same
# newly-discovered id_kachel twice (ConstraintException, duplicate key --
# the lock alone does NOT prevent this).
# @st.cache_resource on these two trivial factories (no Streamlit UI calls
# inside them, so no replay risk at all) is what actually makes them
# once-per-process: every rerun/session gets the SAME dict and SAME Lock
# object back, so the lock below can actually serialize across them.
#
# The gold manifest is refreshed ONCE per process, at startup. The MAXI
# campaign is finished: every kachel is final and gold is immutable, so a
# periodic re-listing would find nothing new. A rebuilt or extended lake is
# picked up by restarting the app.


@st.cache_resource(show_spinner=False)
def _app_version() -> str | None:
    """Client-facing "which version am I looking at" string. In the image:
    PGR_ATLAS_VERSION, baked in by CI (the release tag, e.g. v0.3.1, or
    <branch>-<short sha> for branch builds) -- the image has no git and no
    .git, so the git fallback below only ever works in a local checkout,
    where it gives the last commit's date + short SHA. Cached per-process,
    so None when neither is there: the footer words that in the session's
    language."""
    _baked = os.getenv("PGR_ATLAS_VERSION")
    if _baked:
        return _baked
    try:
        _repo_dir = os.path.dirname(os.path.abspath(__file__))
        _date = subprocess.check_output(
            ["git", "log", "-1", "--format=%cd", "--date=format:%d.%m.%Y"],
            cwd=_repo_dir,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        _sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_repo_dir,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return f"{_date} ({_sha})"
    except Exception:
        return None


@st.cache_resource
def _get_gold_manifest_cache() -> dict:
    return {}


@st.cache_resource
def _get_gold_manifest_lock() -> threading.Lock:
    return threading.Lock()


_gold_manifest_cache = _get_gold_manifest_cache()
_gold_manifest_lock = _get_gold_manifest_lock()

# --- Cold-start sequence: everything below only does real WORK on the
# first request to a freshly started server process (each step is
# @st.cache_resource, or the gold-manifest dict/lock pair above) — later
# reruns hit cache and every call here returns instantly. But Streamlit
# reruns this whole top-level script on EVERY interaction (e.g. clicking an
# anriss), so without this guard the st.status(...) UI itself would still
# re-create its container and replay every .update()/.write() call on every
# single click even though the underlying data never actually changes —
# that's the "why does it say Suche berechnete Kacheln again"
# flash. _is_cold_start (keyed off the same gold-manifest cache dict
# checked inside _refresh_gold_manifest below) is true only for the actual
# first run; every later rerun swaps in a no-op shim so this block's body
# stays textually identical but doesn't touch the UI at all.
_is_cold_start = "result" not in _gold_manifest_cache


class _NoOpStatus:
    def update(self, *a, **k):
        pass

    def write(self, *a, **k):
        pass


@contextlib.contextmanager
def _startup_status():
    """The startup steps' status box, removed once they are done. On an error
    (e.g. st.stop() after the S3 message) it stays, with the message in it."""
    slot = st.empty()
    with slot.status(ui_text.t("startup.status"), expanded=True) as status:
        yield status
    slot.empty()


if _is_cold_start:
    _status_cm = _startup_status()
else:
    _status_cm = contextlib.nullcontext(_NoOpStatus())

with _status_cm as _init_status:
    # Aggregate stats + map centre only (pmtiles renders the individual
    # anrisse now, nothing here needs a 61M-row DataFrame).
    @st.cache_resource(show_spinner=False)
    def _get_manifest_stats():
        return data.catalog_overview_stats()

    _init_status.update(label=ui_text.t("startup.manifest"))
    # The first S3 access of a page load: missing or wrong credentials show
    # here. A message instead of the traceback; the details go to the log.
    try:
        _manifest_stats = _get_manifest_stats()
    except (botocore.exceptions.NoCredentialsError, botocore.exceptions.ClientError):
        logging.getLogger(__name__).exception("S3 is not reachable with the configured credentials")
        st.error(
            ui_text.t("startup.s3_error")
            if s3_target.has_credentials()
            else ui_text.t("startup.no_credentials")
        )
        st.stop()
    overview_anriss_count = _manifest_stats["anriss_count"]
    overview_area_count = _manifest_stats["area_count"]
    overview_pq_count = _manifest_stats["pq_count"]
    _overview_center_lat = _manifest_stats["center_lat"]
    _overview_center_lon = _manifest_stats["center_lon"]
    _init_status.write(
        ui_text.t(
            "startup.manifest_done",
            anriss_count=fmt_ch(overview_anriss_count),
            pq_count=fmt_ch(overview_pq_count),
            area_count=fmt_ch(overview_area_count),
        )
    )

    # Not count_data_lake_pixels(): a live S3 COUNT(*) across every
    # finalized gold kachel takes over a minute, too slow for startup.
    @st.cache_resource(show_spinner=False)
    def _get_sim_count():
        return data.count_simulations()

    _init_status.update(label=ui_text.t("startup.sim_count"))
    _overview_sim_count = _get_sim_count()
    _init_status.write(ui_text.t("startup.sim_count_done", sim_count=fmt_ch(_overview_sim_count)))

    # Gold-finalize state (S3, "which kacheln are sealed") — re-checked at
    # most once per process, at startup (see the note above
    # _get_gold_manifest_cache). Drives load_kachel_coverage() below: the app
    # shows finalized gold tiles only, never partially-scattered ones. See
    # _gold_manifest_cache above for why this isn't @st.cache_resource.
    def _refresh_gold_manifest(_progress_callback=None):
        with _gold_manifest_lock:
            if "result" not in _gold_manifest_cache:
                _gold_manifest_cache["result"] = data.refresh_gold_manifest(
                    progress_callback=_progress_callback
                )
            return _gold_manifest_cache["result"]

    def _gold_progress(done, total, _msg):
        # refresh_gold_manifest is a plain S3 directory listing + a local
        # insert, no per-kachel data reads. This fires at most twice (0/N, N/N), not once per kachel. Its message is
        # German; startup.gold_done below says the same in the session's language.
        _init_status.update(
            label=ui_text.t("startup.gold_progress", done=fmt_ch(done), total=fmt_ch(total))
        )

    _init_status.update(label=ui_text.t("startup.gold"))
    _gold_manifest_stats = _refresh_gold_manifest(_progress_callback=_gold_progress)
    # gold_finalized_kachel_count/expected_gold_kachel_count (see
    # data_interface.py's _expected_gold_kacheln docstring) are the
    # real numerator/denominator -- every kachel/anriss's 5x5
    # GOLD_MAX_REACH_M neighborhood, matching what gold's finalize phase can
    # actually close, including legitimate "empty" neighbor tiles.
    _overview_gold_kachel_count = data.gold_finalized_kachel_count()
    _total_kacheln = data.expected_gold_kachel_count()
    _init_status.write(
        ui_text.t(
            "startup.gold_done",
            done=fmt_ch(_overview_gold_kachel_count),
            total=fmt_ch(_total_kacheln),
            new=fmt_ch(_gold_manifest_stats["new_kacheln"]),
        )
    )

    # "Available now" counterpart to _manifest_stats above — anrisse with at
    # least one finalized gold kachel indexed (upper bound, see
    # gold_coverage_stats' docstring), vs. the manifest's planned totals.
    @st.cache_resource(show_spinner=False)
    def _get_gold_coverage_stats():
        return data.gold_coverage_stats()

    _init_status.update(label=ui_text.t("startup.gold_coverage"))
    _gold_coverage_stats = _get_gold_coverage_stats()
    _init_status.write(
        ui_text.t(
            "startup.gold_coverage_done",
            anriss_count=fmt_ch(_gold_coverage_stats["anriss_count"]),
        )
    )

    # Streamlit's own static handler for custom components reads+returns the
    # WHOLE file on every request regardless of Range headers, which breaks
    # PMTiles (built on range requests to fetch only the header/directory/
    # tile chunks it needs). Proxy the tileset from S3 through a small
    # Tornado server instead, forwarding Range headers through to S3's own
    # native Range support (Tornado is already a Streamlit dependency) —
    # see pmtiles_server.py.
    # Overridable so a second streamlit instance (e.g. a preview deploy on a
    # different --server.port) can run its own PMTiles proxy without racing
    # a production instance for the same port. PMTILES_BIND="127.0.0.1" +
    # PMTILES_PATH_PREFIX (e.g. "/pmtiles-data") is the fronted-by-nginx
    # case (see README §Preview instance): the proxy binds localhost-only
    # and a reverse proxy exposes it under a path on the same public port
    # as the app itself, instead of needing its own firewall rule. Left
    # unset, both default to today's behavior (own public port, no prefix).
    PMTILES_SERVER_PORT = int(os.environ.get("PMTILES_PORT", 8505))
    PMTILES_BIND = os.environ.get("PMTILES_BIND", "0.0.0.0")
    PMTILES_PATH_PREFIX = os.environ.get("PMTILES_PATH_PREFIX", "")

    @st.cache_resource(show_spinner=False)
    def _ensure_pmtiles_server():
        return pmtiles_server.start(PMTILES_SERVER_PORT, PMTILES_BIND)

    _init_status.update(label=ui_text.t("startup.pmtiles"))
    _ensure_pmtiles_server()
    _init_status.write(
        ui_text.t("startup.server_done", name="PMTiles-Server", port=PMTILES_SERVER_PORT)
    )

    # Raster-Derivate view's live map layer: a small Tornado
    # service that crops+colorizes the current viewport directly from the
    # canton-wide mosaic COGs on every pan/zoom -- see derivate_bbox_
    # server.py's module docstring. Same override/prefix pattern as the
    # PMTiles proxy above, for the same reason (a second preview instance,
    # or an nginx-fronted deploy terminating the public port itself).
    DERIVATE_BBOX_SERVER_PORT = int(os.environ.get("DERIVATE_BBOX_PORT", 8503))
    DERIVATE_BBOX_BIND = os.environ.get("DERIVATE_BBOX_BIND", "0.0.0.0")
    DERIVATE_BBOX_PATH_PREFIX = os.environ.get("DERIVATE_BBOX_PATH_PREFIX", "")

    @st.cache_resource(show_spinner=False)
    def _ensure_derivate_bbox_server():
        return derivate_bbox_server.start(DERIVATE_BBOX_SERVER_PORT, DERIVATE_BBOX_BIND)

    _init_status.update(label=ui_text.t("startup.raster_server"))
    _ensure_derivate_bbox_server()
    _init_status.write(
        ui_text.t("startup.server_done", name="Raster-Server", port=DERIVATE_BBOX_SERVER_PORT)
    )

# derivate_bbox_server.py, for the views that link to or draw from it.
_BBOX_SERVER = dict(port=DERIVATE_BBOX_SERVER_PORT, path_prefix=DERIVATE_BBOX_PATH_PREFIX)

_overview_stats = overview.Stats(
    manifest=_manifest_stats,
    gold=_gold_coverage_stats,
    sim_count=_overview_sim_count,
    gold_kacheln=_overview_gold_kachel_count,
    total_kacheln=_total_kacheln,
    as_of=_gold_manifest_stats["newest_modified"],
)


@st.cache_resource(show_spinner=False)
def _overview_pmtiles_exists():
    return s3_key_exists(pmtiles_server.S3_BUCKET, overview.PMTILES_FILENAME)


if not _overview_pmtiles_exists():
    st.warning(
        ui_text.t(
            "overview.pmtiles_missing",
            bucket=pmtiles_server.S3_BUCKET,
            filename=overview.PMTILES_FILENAME,
        )
    )


# --- SESSION STATE ---
init_session_state()
# Before any st.switch_page below: a switch ends this run early, and Streamlit
# then drops the state of every widget not drawn yet.
expert_mode.keep_across_pages()


# --- NAVIGATION ---
# One st.Page per view, so each view has a URL (/ifk, /anriss, ...) and browser
# back/forward move between views. The sidebar's own list of links below is
# the menu (position="hidden"). Each page's function renders its view from app/views/
# (Gebäudeschatten: gebaeudeschatten_view.py) with the servers it needs.
def _overview_page():
    overview.render(
        _overview_stats,
        servers=dict(pmtiles_port=PMTILES_SERVER_PORT, pmtiles_path_prefix=PMTILES_PATH_PREFIX),
        anriss_page=_PAGES[anriss.VIEW_MODE],
    )


def _ifk_page():
    expert_mode.render_sidebar()
    ifk_area.render_sidebar()
    ifk.render(
        servers=dict(
            pmtiles_port=PMTILES_SERVER_PORT,
            pmtiles_path_prefix=PMTILES_PATH_PREFIX,
            bbox_server=_BBOX_SERVER,
        ),
        default_center=(_overview_center_lat, _overview_center_lon),
        anriss_page=_PAGES[anriss.VIEW_MODE],
    )


def _raster_karten_page():
    expert_mode.render_sidebar()
    raster_karten.render(
        servers=dict(pmtiles_port=PMTILES_SERVER_PORT, pmtiles_path_prefix=PMTILES_PATH_PREFIX),
        bbox_server=_BBOX_SERVER,
        default_center=(_overview_center_lat, _overview_center_lon),
    )


def _raster_derivate_page():
    raster_derivate.render(
        servers=dict(pmtiles_port=PMTILES_SERVER_PORT, pmtiles_path_prefix=PMTILES_PATH_PREFIX),
        bbox_server=_BBOX_SERVER,
        default_center=(_overview_center_lat, _overview_center_lon),
    )


def _gebaeudeschatten_page():
    gebaeudeschatten_view.render_sidebar()
    gebaeudeschatten_view.render(
        servers=dict(pmtiles_port=PMTILES_SERVER_PORT, pmtiles_path_prefix=PMTILES_PATH_PREFIX),
        bbox_server=_BBOX_SERVER,
    )


def _anriss_page():
    anriss.render(
        _PAGES,
        servers=dict(pmtiles_port=PMTILES_SERVER_PORT, pmtiles_path_prefix=PMTILES_PATH_PREFIX),
        link_error=_anriss_link_error,
    )


# Built on every run, like everything at this file's top level, so the page
# titles (the navigation's labels) follow the session's language.
_PAGES = {
    overview.VIEW_MODE: st.Page(
        _overview_page,
        title=ui_text.t("nav.overview"),
        url_path="simulierte-ereignisse",
        default=True,
    ),
    ifk.VIEW_MODE: st.Page(_ifk_page, title=ui_text.t("nav.ifk"), url_path="ifk"),
    raster_karten.VIEW_MODE: st.Page(
        _raster_karten_page, title=ui_text.t("nav.raster_karten"), url_path="raster-karten"
    ),
    raster_derivate.VIEW_MODE: st.Page(
        _raster_derivate_page, title=ui_text.t("nav.raster_derivate"), url_path="raster-derivate"
    ),
    anriss.VIEW_MODE: st.Page(_anriss_page, title=ui_text.t("nav.anriss"), url_path="anriss"),
}
# Only where the gold bucket holds the Gebäudeschatten data (published by the
# pipeline); elsewhere, e.g. Bedag's adelboden-test, the view doesn't exist.
if gebaeudeschatten_view.is_available():
    _PAGES[gebaeudeschatten_view.VIEW_MODE] = st.Page(
        _gebaeudeschatten_page,
        title=ui_text.t("nav.gebaeudeschatten"),
        url_path="gebaeudeschatten",
    )


def _close_legal_page():
    """The cross on a legal page: back to the view the legal page was opened from,
    with that view's URL (e.g. /anriss?id=...)."""
    view = st.session_state.get("_view_before_legal", overview.VIEW_MODE)
    st.switch_page(_PAGES[view], query_params=st.session_state.get("_query_before_legal"))


# The legal pages are reached from the footer only: registered, but not in the
# sidebar navigation (which loops over _PAGES) and not in the Anriss guard.
_LEGAL_PAGES = {
    "contact": st.Page(
        legal.page_function("kontakt", _close_legal_page),
        title=ui_text.t("footer.contact"),
        url_path="kontakt",
    ),
    "imprint": st.Page(
        legal.page_function("impressum", _close_legal_page),
        title=ui_text.t("footer.imprint"),
        url_path="impressum",
    ),
    "legal": st.Page(
        legal.page_function("rechtliches", _close_legal_page),
        title=ui_text.t("footer.legal"),
        url_path="rechtliches",
    ),
}
_current_page = st.navigation(
    list(_PAGES.values()) + list(_LEGAL_PAGES.values()), position="hidden"
)
if _current_page not in _LEGAL_PAGES.values():
    st.session_state["_view_before_legal"] = next(
        view_mode for view_mode, page in _PAGES.items() if page is _current_page
    )
    st.session_state["_query_before_legal"] = st.query_params.to_dict()
# The Anriss page needs a selected Anriss: from its link (/anriss?id=), else
# the one already selected. Without either it opens Simulierte Ereignisse; a bad link
# stays, to say what's wrong with it.
_anriss_link_error = None
if _current_page is _PAGES[anriss.VIEW_MODE]:
    _anriss_link_error = anriss.select_from_link()
    if st.session_state.selected_id_anriss is None and _anriss_link_error is None:
        st.switch_page(_PAGES[overview.VIEW_MODE])

# --- SIDEBAR ---
# The logos are served from app/static/ (enableStaticServing in
# app/.streamlit/config.toml), so the page loads nothing from third-party hosts.
st.sidebar.markdown(
    """
    <div class="pgr-sidebar-head">
        <div class="pgr-app-title">"""
    + ui_text.APP_NAME
    + """ <span class="pgr-app-topic">"""
    + ui_text.t("app.topic")
    + """</span></div>
        <img src="app/static/logo-be.svg" class="pgr-logo-be">
        <img src="app/static/logo_2026_wide.svg" class="pgr-logo-wide">
    </div>
    """,
    unsafe_allow_html=True,
)


# ── Navigation: a list of links, the open Anriss indented below them.
# The active link sits in the "nav_current" container, which app.css marks
# with the red bar. Links, not buttons, so navigation and actions differ.
def _nav_link(page, label, query_params=None):
    with st.container(key="nav_current" if page is _current_page else None):
        st.page_link(page, label=label, query_params=query_params, width="stretch")


with st.sidebar.container(key="pgr_nav"):
    for _nav_vm, _nav_page in _PAGES.items():
        if _nav_vm != anriss.VIEW_MODE:
            _nav_link(_nav_page, _nav_page.title)
    if st.session_state.selected_id_anriss is not None:
        with st.container(key="pgr_nav_sub"):
            _nav_link(
                _PAGES[anriss.VIEW_MODE],
                ui_text.nav_anriss(st.session_state.selected_id_anriss),
                query_params=anriss_query_params(st.session_state.selected_id_anriss),
            )

# _anriss_pending lets map-click and back-button update the keyed widget before it renders.
if "_anriss_pending" in st.session_state:
    st.session_state["_anriss_input"] = st.session_state.pop("_anriss_pending")

# "Anriss öffnen" by ID: under the navigation, the same on every view.
anriss_lookup_form(_PAGES[anriss.VIEW_MODE])

_current_page.run()

download_gate_component.mount_download_gate(
    ui_text.t("download_gate.title"),
    ui_text.t("download_gate.statement"),
    ui_text.t("download_gate.accept"),
    ui_text.t("download_gate.decline"),
    _LEGAL_PAGES["legal"],
)
footer.render(
    _LEGAL_PAGES,
    {
        "copyright": ui_text.t("footer.copyright"),
        "working_group": ui_text.t("footer.working_group"),
        "contact": ui_text.t("footer.contact"),
        "imprint": ui_text.t("footer.imprint"),
        "legal": ui_text.t("footer.legal"),
    },
)

# The sidebar's foot: version, data source and DE | FR. Added after the page has
# run, so it is the last sidebar element on every view (st.sidebar order follows
# call order); app.css keeps it at the bottom of the sidebar, always in view.
# The bucket probe-core actually bound at import, not just what the env says.
with st.sidebar.container(key="pgr_sidebar_foot"):
    st.markdown(
        ui_text.version_footer(
            _app_version() or ui_text.t("app.version_unknown"),
            s3_target.source_label(S3_CONFIG["endpoint_url"]),
            data.S3_BUCKET_GOLD,
        ),
        unsafe_allow_html=True,
    )
    language.render_toggle()
