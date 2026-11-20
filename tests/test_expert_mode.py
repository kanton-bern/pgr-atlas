"""Experten-Modus: merging an edit in the IFK view's per-Anriss factor editor."""

import pandas as pd

from views.expert_mode import merged_anriss_overrides

_DISPLAYED = pd.DataFrame(
    {
        "id_anriss": [11, 22],
        "lambda_Hangmuren": [0.5, 0.25],
        "p_raeumlich": [0.1, 0.2],
        "p_A": [1.0, 1.0],
    }
)


def _edit(**cells):
    """_DISPLAYED with cells changed, e.g. _edit(p_A=(22, 0.5))."""
    edited = _DISPLAYED.copy()
    for column, (id_anriss, value) in cells.items():
        edited.loc[edited["id_anriss"] == id_anriss, column] = value
    return edited


def test_no_edit_keeps_the_overrides():
    current = {11: {"p_A": 0.3}}
    assert merged_anriss_overrides(_DISPLAYED, _DISPLAYED.copy(), current) == current


def test_an_edited_cell_becomes_an_override():
    merged = merged_anriss_overrides(_DISPLAYED, _edit(p_A=(22, 0.5)), {})
    assert merged == {22: {"p_A": 0.5}}


def test_an_edit_keeps_the_same_anriss_s_earlier_override_of_another_factor():
    # The earlier override is what the editor displays, so its cell is unchanged.
    displayed = _edit(p_raeumlich=(11, 0.9))
    edited = displayed.copy()
    edited.loc[edited["id_anriss"] == 11, "p_A"] = 0.5
    merged = merged_anriss_overrides(displayed, edited, {11: {"p_raeumlich": 0.9}})
    assert merged == {11: {"p_raeumlich": 0.9, "p_A": 0.5}}


def test_overrides_of_anrisse_not_in_the_editor_stay():
    merged = merged_anriss_overrides(_DISPLAYED, _edit(p_A=(11, 0.5)), {99: {"p_A": 0.1}})
    assert merged == {99: {"p_A": 0.1}, 11: {"p_A": 0.5}}


def test_the_current_overrides_are_not_changed_in_place():
    current = {11: {"p_A": 0.3}}
    merged_anriss_overrides(_DISPLAYED, _edit(p_raeumlich=(11, 0.9)), current)
    assert current == {11: {"p_A": 0.3}}
