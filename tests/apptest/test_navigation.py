"""The pages behind the sidebar navigation (st.navigation in app.py)."""

import pytest

from tests.apptest.conftest import (
    assert_no_exception,
    current_view,
    nav_links,
    new_app,
    open_page,
    page_title,
    run_view,
)
from tests.lake_data import ANRISS_ID, IFK_PIXEL

pytestmark = pytest.mark.apptest

# Each view's page header title: its label in the navigation.
_TITLES = {
    "Overview (All Events)": "Simulierte Ereignisse",
    "IFK": "IFK-Berechnung",
    "Raster-Karten": "Raster-Karten (ad hoc)",
    "Raster-Derivate": "Raster-Derivate",
    "Gebäudeschatten": "Gebäudeschatten",
}


def _language_buttons(at) -> dict[str, bool]:
    """The DE | FR buttons: {label: disabled}, the current language disabled."""
    return {b.label: b.disabled for b in at.sidebar.button if b.key.startswith("lang_")}


def test_there_is_no_language_toggle_while_the_texts_are_german_only(german_only_texts):
    at = run_view("Overview (All Events)")
    assert _language_buttons(at) == {}


def test_french_is_picked_in_the_sidebar_and_shown_in_the_url(french_texts):
    at = run_view("Overview (All Events)")
    assert _language_buttons(at) == {"DE": True, "FR": False}
    at.sidebar.button(key="lang_fr").click().run()
    assert_no_exception(at)
    assert _language_buttons(at) == {"DE": False, "FR": True}
    assert page_title(at) == "[FR] Simulierte Ereignisse"
    assert "[FR] IFK-Berechnung" in nav_links(at)
    assert at.query_params == {"lang": "fr"}
    at.sidebar.button(key="lang_de").click().run()
    assert page_title(at) == "Simulierte Ereignisse"
    assert at.query_params == {}


def test_a_link_opens_in_its_language(french_texts):
    at = new_app("Overview (All Events)")
    at.query_params.update({"lang": "fr"})
    at.run()
    assert_no_exception(at)
    assert page_title(at) == "[FR] Simulierte Ereignisse"


def test_a_link_in_a_language_the_app_lacks_opens_german(german_only_texts):
    at = new_app("Overview (All Events)")
    at.query_params.update({"lang": "fr"})
    at.run()
    assert_no_exception(at)
    assert page_title(at) == "Simulierte Ereignisse"
    assert at.query_params == {}


def test_the_navigation_links_every_view():
    at = run_view("Overview (All Events)")
    assert nav_links(at) == {title: view for view, title in _TITLES.items()}


# The legal pages' titles, which are also their keys in PAGE_URL_PATHS.
_LEGAL_PAGES = ["Kontakt", "Impressum", "Rechtliches"]


def _footer_links(at) -> list[str]:
    """The labels of the footer's links, in order (the external one first)."""
    return [link.proto.label for link in at.main.get("page_link")]


def test_every_view_has_the_footer_and_the_sidebar_navigation_does_not_link_legal_pages():
    at = run_view("Overview (All Events)")
    assert _footer_links(at) == [
        "Arbeitsgruppe Naturgefahren des Kantons Bern",
        "Kontakt",
        "Impressum",
        "Rechtliches",
    ]
    assert not set(nav_links(at)) & set(_LEGAL_PAGES)


@pytest.mark.parametrize("page", _LEGAL_PAGES)
def test_each_legal_page_has_one_h1_and_the_footer(page):
    at = new_app(page).run()
    assert_no_exception(at)
    assert page_title(at) == page
    assert len(_footer_links(at)) == 4


@pytest.mark.parametrize("view", list(_TITLES))
def test_each_view_has_its_header_and_the_anriss_lookup(view):
    """run_view also checks that the view's own link is the one marked."""
    at = run_view(view)
    assert page_title(at) == _TITLES[view]
    assert at.sidebar.number_input(key="_anriss_input").label == "Anriss-ID"


def test_the_open_anriss_is_the_last_link_and_its_page_title():
    at = run_view("Specific Simulation", selected_id_anriss=ANRISS_ID)
    links = nav_links(at)
    assert list(links)[-1] == f"Anriss {ANRISS_ID}"
    assert links[f"Anriss {ANRISS_ID}"] == "Specific Simulation"
    assert page_title(at) == f"Anriss {ANRISS_ID}"


def test_anriss_page_without_a_selected_anriss_opens_the_overview():
    at = new_app("Specific Simulation").run()
    assert_no_exception(at)
    assert current_view(at) == "Overview (All Events)"


def test_deselecting_the_anriss_returns_to_the_view_it_was_opened_from():
    at = run_view("Specific Simulation", selected_id_anriss=ANRISS_ID, _return_view="IFK")
    next(b for b in at.button if b.key == "btn_zurueck").click()
    at.run()
    assert_no_exception(at)
    assert current_view(at) == "IFK"
    assert at.session_state["selected_id_anriss"] is None
    assert at.query_params == {}


def test_deselecting_the_anriss_puts_the_selected_ifk_pixel_in_the_url():
    at = run_view(
        "Specific Simulation",
        selected_id_anriss=ANRISS_ID,
        _return_view="IFK",
        _ifk_pending=IFK_PIXEL,
    )
    next(b for b in at.button if b.key == "btn_zurueck").click()
    at.run()
    assert_no_exception(at)
    assert current_view(at) == "IFK"
    assert at.query_params == {"x": "2598502.5", "y": "1137502.5"}
    assert at.session_state["_ifk_pending"] == IFK_PIXEL


def _navigate_to(at, view):
    """What a click on the view's link does: a run of its page."""
    open_page(at, view).run()
    assert_no_exception(at)
    assert current_view(at) == view


def test_experten_modus_and_its_overrides_survive_switching_views():
    """Each view is its own page, so its widgets are new widgets."""
    at = run_view("IFK")
    at.sidebar.toggle(key="_expert_active").set_value(True).run()
    at.sidebar.slider(key="_expert_p_h_mean").set_value(0.3).run()
    at.session_state["_expert_anriss_overrides"] = {ANRISS_ID: {"p_A": 0.5}}

    for view in ("Raster-Karten", "Overview (All Events)", "IFK"):
        _navigate_to(at, view)
        assert at.session_state["_expert_active"]
        assert at.session_state["_expert_p_h_mean"] == 0.3
        assert at.session_state["_expert_anriss_overrides"] == {ANRISS_ID: {"p_A": 0.5}}
    assert at.sidebar.toggle(key="_expert_active").value
    assert at.sidebar.slider(key="_expert_p_h_mean").value == 0.3

    at.sidebar.toggle(key="_expert_active").set_value(False).run()
    assert "_expert_anriss_overrides" not in at.session_state
    _navigate_to(at, "Raster-Karten")
    assert not at.sidebar.toggle(key="_expert_active").value
