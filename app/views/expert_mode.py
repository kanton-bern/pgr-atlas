"""Experten-Modus: ad-hoc probability overrides for IFK and Raster-Karten.

Open to every user of the app, off by default. The
overrides live in this session only and are never written to S3.
compute_ifk_default and build_raster_for_bbox default every override to
None, so with the toggle off override_kwargs() returns {} and both views
compute exactly what they compute without Experten-Modus.
"""

import json

import numpy as np
import pandas as pd
import streamlit as st

import language
import ui_text
from probe_core.derivate import ifk_and_raster

ABLAUF_SUM_TOLERANCE = 1e-6

# The per-Anriss factors the IFK view lets the user override. They are constant
# per id_anriss (build_probability_lookup.py checks that), so the editor has
# one row per Anriss.
_ANRISS_FACTORS = ("lambda_Hangmuren", "p_raeumlich", "p_A")

# The session keys the overrides live in, dropped when the toggle goes off.
_OVERRIDE_KEYS = (
    "_expert_p_h_mean",
    "_expert_p_h_max",
    "_expert_p_h_mean_pending",
    "_expert_ablauf_df",
    "_expert_anriss_overrides",
)

# Widget keys whose values keep_across_pages() carries to the next page. The
# p_Ablauf editor needs none: its data comes from '_expert_ablauf_df', and the
# p_h (max) slider is set from '_expert_p_h_mean' on every run.
_WIDGET_KEYS = ("_expert_active", "_expert_p_h_mean")

# Pixels; wide enough for "1000" and "1500" in the p_Ablauf editor.
_PARAM_COLUMN_WIDTH = 44


def keep_across_pages():
    """Keeps the toggle and the p_h slider as they are when the user switches
    views. Each view is its own st.Page and Streamlit puts the page into
    every widget's id, so the toggle on Raster-Karten is a different widget from
    the one on IFK. It would start at its default, off, and clear the overrides.
    A value written under the key before the widget is drawn is what the new
    widget starts from (Streamlit's pattern for widget state across pages). Runs
    on every page, so the state also survives a view without the panel, like
    the Anriss view opened from an IFK circle."""
    for key in _WIDGET_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def _ablauf_valid(ablauf_df) -> bool:
    return (
        ablauf_df is not None
        and abs(float(ablauf_df["p_ablauf"].sum()) - 1.0) < ABLAUF_SUM_TOLERANCE
    )


def override_kwargs(include_anriss: bool = False) -> dict:
    """kwargs to splat into compute_ifk_default/build_raster_for_bbox from
    the current Experten-Modus sidebar state.

    Args:
        include_anriss: True only for compute_ifk_default (IFK view);
            build_raster_for_bbox has no per-Anriss override parameter.

    Returns:
        {} with Experten-Modus off. A p_Ablauf edit that doesn't sum to 1 is
        left out rather than passed on to raise: the sidebar already shows it
        as not applied, so it shouldn't break the pixel or raster below.
    """
    if not st.session_state.get("_expert_active"):
        return {}
    kwargs = {}
    p_h_mean = st.session_state.get("_expert_p_h_mean")
    if p_h_mean is not None:
        kwargs["p_h_mean"] = p_h_mean
        kwargs["p_h_max"] = 1.0 - p_h_mean
    ablauf_df = st.session_state.get("_expert_ablauf_df")
    if _ablauf_valid(ablauf_df):
        kwargs["ablauf_override"] = ablauf_df
    if include_anriss:
        anriss_overrides = st.session_state.get("_expert_anriss_overrides")
        if anriss_overrides:
            kwargs["anriss_overrides"] = anriss_overrides
    return kwargs


def cache_signature():
    """Hashable summary of the override state, so a cached IFK/raster result
    is dropped when the overrides change on the same pixel or selection.

    It applies the same validity check as override_kwargs: an invalid
    p_Ablauf edit counts as None here too, so it doesn't trigger a recompute
    (an extra S3 read) whose kwargs wouldn't differ."""
    if not st.session_state.get("_expert_active"):
        return None
    p_h_mean = st.session_state.get("_expert_p_h_mean")
    ablauf_df = st.session_state.get("_expert_ablauf_df")
    ablauf_signature = tuple(ablauf_df["p_ablauf"].round(8)) if _ablauf_valid(ablauf_df) else None
    anriss_overrides = st.session_state.get("_expert_anriss_overrides") or {}
    anriss_signature = tuple(
        sorted(
            (id_anriss, tuple(sorted(factors.items())))
            for id_anriss, factors in anriss_overrides.items()
        )
    )
    return (p_h_mean, ablauf_signature, anriss_signature)


def config_json_bytes(snapshot: dict | None = None) -> bytes:
    """The override state (p_h, p_Ablauf, per-Anriss overrides) as JSON.

    Overrides are never stored server-side, so this download is the only
    record of what produced a result.

    Args:
        snapshot: kwargs as returned by override_kwargs, to export instead of
            the live sidebar state. The Raster-Karten job passes the snapshot
            it was submitted with, since the sidebar can change while it runs.
            The IFK view passes nothing: its result is dropped on every
            override change (cache_signature), so it always matches the
            sidebar.
    """
    if snapshot is not None:
        p_h_mean = snapshot.get("p_h_mean")
        ablauf_df = snapshot.get("ablauf_override")
        anriss_overrides = snapshot.get("anriss_overrides") or {}
    else:
        p_h_mean = st.session_state.get("_expert_p_h_mean")
        ablauf_df = st.session_state.get("_expert_ablauf_df")
        anriss_overrides = st.session_state.get("_expert_anriss_overrides") or {}
    config = {
        "p_h_mean": p_h_mean,
        "p_h_max": (1.0 - p_h_mean) if p_h_mean is not None else None,
        "ablauf": ablauf_df.to_dict("records") if ablauf_df is not None else None,
        "anriss_overrides": anriss_overrides,
    }
    return json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8")


def _p_h_mean_from_max():
    """on_change of the p_h (max) slider: '_expert_p_h_mean' is the value the
    overrides read, so a move of the max slider is written to it. Rounded to
    the slider step, or 1 - 0.8 would be 0.19999999999999996."""
    st.session_state["_expert_p_h_mean"] = round(1.0 - st.session_state["_expert_p_h_max"], 2)


def _p_h_editor():
    """Two sliders, p_h (mean) and p_h (max), that always sum to 1: moving one
    moves the other the opposite way, so each value is raised by dragging its
    own slider to the right."""
    default = ifk_and_raster.GOLD_P_H_MEAN
    # Streamlit forbids writing a widget's key once the widget exists in this
    # run, and the reset button comes after the sliders: it stores the value
    # under a pending key, applied here before the sliders on the next run.
    if "_expert_p_h_mean_pending" in st.session_state:
        st.session_state["_expert_p_h_mean"] = st.session_state.pop("_expert_p_h_mean_pending")
    if "_expert_p_h_mean" not in st.session_state:
        st.session_state["_expert_p_h_mean"] = default
    # The max slider is set from the mean on every run, before it is drawn:
    # that is what moves it when the mean slider was dragged.
    st.session_state["_expert_p_h_max"] = round(1.0 - st.session_state["_expert_p_h_mean"], 2)
    st.caption(ui_text.t("expert.p_h_intro"))
    st.slider(
        ui_text.t("expert.p_h_mean_slider"),
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        key="_expert_p_h_mean",
    )
    st.slider(
        ui_text.t("expert.p_h_max_slider"),
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        key="_expert_p_h_max",
        on_change=_p_h_mean_from_max,
    )
    st.caption(ui_text.expert_p_h_caption(default))
    if st.button(ui_text.t("expert.p_h_reset"), key="_expert_p_h_reset_btn", width="stretch"):
        st.session_state["_expert_p_h_mean_pending"] = default
        st.rerun()


def _replace_ablauf(ablauf_df, generation: int):
    """Shows `ablauf_df` in a new editor. st.data_editor keeps its edits under
    its key across reruns and would apply them again on top of new data, so
    every change made here (not typed in the editor) mounts it under a new key
    (the generation is part of the key)."""
    st.session_state["_expert_ablauf_df"] = ablauf_df
    st.session_state["_expert_ablauf_editor_gen"] = generation + 1
    st.rerun()


def _ablauf_zero_rows(edited, generation: int):
    st.markdown(ui_text.t("expert.ablauf_zero_heading"))
    # The button goes below the two selectboxes: three side by side don't fit
    # the 300 px sidebar.
    param_col, value_col = st.columns(2)
    param = param_col.selectbox(
        ui_text.t("expert.ablauf_zero_param"),
        list(ui_text.PARAM_LABELS),
        key="_expert_ablauf_zero_param",
        format_func=ui_text.PARAM_LABELS.get,
    )
    value = value_col.selectbox(
        ui_text.t("expert.ablauf_zero_value"),
        sorted(edited[param].unique()),
        key=language.translated_options(f"_expert_ablauf_zero_value_{param}"),
        format_func=lambda v: ui_text.in_locale(f"{v:g}"),
    )
    if st.button(
        ui_text.t("expert.ablauf_zero_button"), key="_expert_ablauf_zero_btn", width="stretch"
    ):
        mask = edited[param] == value
        _replace_ablauf(edited.assign(p_ablauf=edited["p_ablauf"].where(~mask, 0.0)), generation)


def _ablauf_editor():
    if "_expert_ablauf_df" not in st.session_state:
        st.session_state["_expert_ablauf_df"] = ifk_and_raster.load_default_ablauf()
    generation = st.session_state.get("_expert_ablauf_editor_gen", 0)
    edited = st.data_editor(
        st.session_state["_expert_ablauf_df"],
        key=f"_expert_ablauf_editor_widget_{generation}",
        disabled=["mu", "xsi", "tau0"],
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        # Narrow parameter columns, so all four fit the 300 px sidebar.
        column_config={
            **{
                col: st.column_config.Column(label, width=_PARAM_COLUMN_WIDTH)
                for col, label in ui_text.PARAM_LABELS.items()
            },
            "p_ablauf": st.column_config.NumberColumn("p_Ablauf", min_value=0.0, format="%.6f"),
        },
    )
    # min_value above keeps the widget from taking a negative entry; clip()
    # also covers a pasted value.
    edited = edited.assign(p_ablauf=edited["p_ablauf"].clip(lower=0.0))
    st.session_state["_expert_ablauf_df"] = edited
    total = float(edited["p_ablauf"].sum())
    if abs(total - 1.0) < ABLAUF_SUM_TOLERANCE:
        st.caption(ui_text.expert_ablauf_sum_ok(total))
    else:
        st.warning(ui_text.expert_ablauf_sum_invalid(total))

    _ablauf_zero_rows(edited, generation)

    if st.button(
        ui_text.t("expert.ablauf_normalize"),
        key="_expert_ablauf_normalize_btn",
        disabled=total == 0,
        width="stretch",
    ):
        _replace_ablauf(edited.assign(p_ablauf=edited["p_ablauf"] / total), generation)
    if st.button(ui_text.t("expert.ablauf_reset"), key="_expert_ablauf_reset_btn", width="stretch"):
        _replace_ablauf(ifk_and_raster.load_default_ablauf(), generation)


def _clear_overrides():
    """Toggle off is a clean slate, so turning it on again later never brings
    back old edits, and '_expert_active' is the only thing override_kwargs and
    cache_signature need to check. The editor generation is bumped, not reset:
    back at 0 it could pick up the first editor's stale edits."""
    st.session_state["_expert_ablauf_editor_gen"] = (
        st.session_state.get("_expert_ablauf_editor_gen", 0) + 1
    )
    for key in _OVERRIDE_KEYS:
        st.session_state.pop(key, None)


def render_sidebar():
    """The Experten-Modus toggle and, while it is on, the override editors."""
    st.sidebar.markdown("---")
    # A bordered, teal-tinted box, so the toggle doesn't read as just another
    # sidebar row (client feedback). Styled by .st-key-expert_modus_box in
    # styles/app.css.
    with st.sidebar.container(border=True, key="expert_modus_box"):
        active = st.toggle(
            ui_text.t("expert.toggle"),
            key="_expert_active",
            value=False,
            help=ui_text.t("expert.toggle_help"),
        )
    if not active:
        _clear_overrides()
        return
    st.sidebar.caption(ui_text.t("expert.beta_note", contact=ui_text.FEEDBACK_CONTACT))
    with st.sidebar.expander(ui_text.t("expert.p_h_expander")):
        _p_h_editor()
    with st.sidebar.expander(ui_text.t("expert.ablauf_expander")):
        _ablauf_editor()


def merged_anriss_overrides(displayed: pd.DataFrame, edited: pd.DataFrame, current: dict) -> dict:
    """The per-Anriss overrides after an edit in the factor editor.

    Args:
        displayed: the factors the editor showed (with any active override).
        edited: the editor's rows after the edit.
        current: the overrides before the edit, {id_anriss: {factor: value}}.

    Returns:
        `current` with every cell that differs from `displayed` set. The
        cells are compared with what was displayed, not with the production
        values, and merged into `current`: an untouched cell matches what is
        displayed, so rebuilding from the differences alone would drop an
        Anriss's other, earlier overrides.
    """
    merged = {id_anriss: dict(factors) for id_anriss, factors in current.items()}
    for _, row in edited.iterrows():
        shown = displayed.loc[displayed["id_anriss"] == row["id_anriss"]].iloc[0]
        for factor in _ANRISS_FACTORS:
            if not np.isclose(row[factor], shown[factor]):
                merged.setdefault(int(row["id_anriss"]), {})[factor] = float(row[factor])
    return merged


def anriss_factor_editor(ereignisse: pd.DataFrame, key: str) -> bool:
    """IFK: overrides for the Anrisse that contribute to the selected pixel
    (the circles on the map). They are stored by id_anriss, not by pixel, so
    an override also applies where the same Anriss reaches another pixel.

    Args:
        ereignisse: compute_ifk_default's per-event table of the pixel.
        key: the editor's widget key, one per pixel.

    Returns:
        True if the edit changed the overrides; the caller reruns.
    """
    st.markdown("---")
    st.markdown(ui_text.t("expert.anriss_heading"))
    displayed = (
        ereignisse[["id_anriss", *_ANRISS_FACTORS]]
        .drop_duplicates("id_anriss")
        .reset_index(drop=True)
    )
    edited = st.data_editor(
        displayed,
        key=key,
        disabled=["id_anriss"],
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        column_config={c: st.column_config.NumberColumn(min_value=0.0) for c in _ANRISS_FACTORS},
    )
    for factor in _ANRISS_FACTORS:
        edited[factor] = edited[factor].clip(lower=0.0)
    merged = merged_anriss_overrides(
        displayed, edited, st.session_state.get("_expert_anriss_overrides") or {}
    )
    if merged == st.session_state.get("_expert_anriss_overrides", {}):
        return False
    st.session_state["_expert_anriss_overrides"] = merged
    return True
