"""A "Link kopieren" button: copies the current page's absolute URL, with the
given query params, to the clipboard.

Streamlit has no clipboard button of its own, and the server cannot write to
the user's clipboard. This is an st.components.v2 component: inline HTML, CSS
and JS, mounted in the app's page (no iframe, no build step), so it can call
navigator.clipboard during the click. It is a real <button>, reachable and
pressed by keyboard; the result is announced in a status region ("copied"
for 4 s; the failure message stays until the next click).

The URL is built in the browser from window.location (scheme, host, any path
prefix of the deployment, the page) plus the query, so it is the link the user
would see in the address bar.
"""

import streamlit as st

_HTML = '<button type="button"></button><span role="status" aria-live="polite"></span>'

# Styled like the app's secondary buttons (app.css: Anthrazit outline, pill
# shape from the theme's buttonRadius), with tokens.css values: the custom
# properties reach into the component's shadow root.
_CSS = """
:host { display: inline-flex; align-items: center; gap: 0.75rem; }
button {
  font: inherit;
  color: var(--pgr-text);
  background: var(--pgr-bg);
  border: 1px solid var(--pgr-brand);
  border-radius: 999px;
  min-height: 2.5rem;
  padding: 0.25rem 0.75rem;
  cursor: pointer;
}
button:hover { border-color: var(--pgr-text); }
button:focus-visible { outline: 2px solid var(--pgr-focus); outline-offset: 2px; }
span { color: var(--pgr-text-muted); }
"""

_JS = """
export default function ({ parentElement, data }) {
  const button = parentElement.querySelector("button");
  const status = parentElement.querySelector("[role=status]");
  button.textContent = data.label;
  let timer;
  button.onclick = async () => {
    const url = new URL(window.location.href);
    url.search = new URLSearchParams(data.query).toString();
    url.hash = "";
    clearTimeout(timer);
    try {
      await navigator.clipboard.writeText(url.href);
      status.textContent = data.copied;
      timer = setTimeout(() => { status.textContent = ""; }, 4000);
    } catch {
      status.textContent = data.failed;
    }
  };
  return () => clearTimeout(timer);
}
"""


def copy_link_button(query: dict[str, str], labels: dict[str, str], key: str) -> None:
    """Draws the button.

    The component is registered on every call, not once at import: the
    registry belongs to the Streamlit runtime, and a module imported under one
    runtime (AppTest starts one per test) would be unknown to the next. An
    unchanged definition registers again without a warning, so _HTML, _CSS and
    _JS must stay constants: per-call values go in `data`.

    Args:
        query: the link's query params, e.g. {'x': '2598502.5', 'y': '1137502.5'}.
        labels: the texts: 'label' (the button), 'copied' and 'failed' (the
            status after a click).
        key: the element key.
    """
    mount = st.components.v2.component("copy_link", html=_HTML, css=_CSS, js=_JS)
    mount(key=key, data={"query": query, **labels}, width="content")
