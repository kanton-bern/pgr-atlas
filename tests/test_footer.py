from streamlit.testing.v1 import AppTest

LABELS = {
    "copyright": "Copyright",
    "working_group": "Working group",
    "contact": "Contact",
    "imprint": "Imprint",
    "legal": "Legal",
}


def _footer_script(drop_label: str = "") -> None:
    import streamlit as st

    import footer

    def page() -> None:
        st.write("page")

    pages = {
        name: st.Page(page, title=name, url_path=name) for name in ("contact", "imprint", "legal")
    }
    home = st.Page(page, title="home", default=True)
    labels = {k: v for k, v in st.session_state["labels"].items() if k != drop_label}
    st.navigation([home, *pages.values()], position="hidden")
    footer.render(pages, labels)


def _run(labels: dict[str, str]) -> AppTest:
    at = AppTest.from_function(_footer_script)
    at.session_state["labels"] = labels
    return at.run()


def test_footer_links_the_working_group_then_the_three_legal_pages():
    at = _run(LABELS)

    assert not at.exception
    links = at.get("page_link")
    assert [link.proto.label for link in links] == ["Working group", "Contact", "Imprint", "Legal"]
    assert links[0].proto.page == "https://www.naturgefahren.sites.be.ch/de/start/ueber-uns.html"
    assert links[0].proto.external
    assert [link.proto.page for link in links[1:]] == ["contact", "imprint", "legal"]
    assert not any(link.proto.external for link in links[1:])


def test_footer_starts_with_the_copyright_line():
    at = _run(LABELS)

    assert [c.value for c in at.caption] == ["Copyright"]


def test_footer_texts_come_from_the_labels():
    german = {key: f"de-{key}" for key in LABELS}

    at = _run(german)

    assert [link.proto.label for link in at.get("page_link")] == [
        "de-working_group",
        "de-contact",
        "de-imprint",
        "de-legal",
    ]


def test_missing_label_fails_with_its_key():
    at = AppTest.from_function(_footer_script, kwargs={"drop_label": "imprint"})
    at.session_state["labels"] = LABELS

    at.run()

    assert at.exception
    assert "imprint" in at.exception[0].value
