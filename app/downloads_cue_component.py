"""The floating cue that points at a view's downloads section.

Every view with downloads puts them below the map, where they are off screen
while the user works on the map. This is a small pill in the bottom-right
corner of the window that smooth-scrolls the page down to them.

An st.components.v2 component with inline HTML, CSS and JS, mounted in the
app's page (no iframe, no build step), as in copy_link_component.py: the pill
needs the page's own DOM to find the section, watch it and scroll to it.

The section is the keyed container `downloads_section()` draws, which
Streamlit renders as the class `st-key-pgr_downloads_section` -- the same
mechanism the download gate uses to find a download link. The pill hides
itself while the section is on screen, and while there is none (a view with
no selection yet draws an empty container), so it never covers the map for
nothing. Where it sits is in app.css, under .st-key-pgr_downloads_cue.
"""

import footer
import streamlit as st
import ui_text
from streamlit.delta_generator import DeltaGenerator

# The key of the container the cue scrolls to. One per page: no view shows two
# downloads sections at once.
SECTION_KEY = "pgr_downloads_section"

_HTML = '<button type="button" hidden><span aria-hidden="true">↓</span><span></span></button>'

# Styled like the app's primary buttons (Anthrazit, pill shape), with
# tokens.css values: the custom properties reach into the shadow root.
# Where the pill sits is in app.css, on the element's keyed container: the
# component's own element is a full-size box the page's styles own, and a
# page style beats a :host rule.
_CSS = """
:host { display: block; }
button {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  max-width: calc(100vw - 2.5rem);
  font: inherit;
  color: var(--pgr-bg);
  background: var(--pgr-brand);
  border: 1px solid var(--pgr-brand);
  border-radius: 999px;
  min-height: 2.5rem;
  padding: 0.25rem 1rem;
  box-shadow: var(--mc-shadow);
  cursor: pointer;
}
button > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
button:hover { background: var(--pgr-brand-dark); border-color: var(--pgr-brand-dark); }
button:focus-visible { outline: 2px solid var(--pgr-focus); outline-offset: 2px; }
button[hidden] { display: none; }
"""

# `hidden` takes the button out of the a11y tree and out of the tab order, so
# hiding it visually hides it everywhere.
#
# The target is looked up again on every sync, not captured once: a Streamlit
# rerun replaces the container's element. The MutationObserver catches that
# and a section that only now has content; the IntersectionObserver reports
# whether the section is on screen.
_JS = """
export default function ({ parentElement, data }) {
  const button = parentElement.querySelector("button");
  button.lastElementChild.textContent = data.label;
  let target = null;
  let frame = 0;
  // The bottom 15% of the window doesn't count as "on screen": a section whose
  // first line peeks over the edge still needs the scroll. Not more than that:
  // below a short map the whole page scrolls only a couple of hundred pixels,
  // and the pill has to go once that scroll has been used. A section that is
  // fully in the window counts anyway: a short one at the very end of the page
  // can't be scrolled out of that bottom 15%, and would keep the pill forever.
  let reached = false;
  let whole = false;
  const update = () => { button.hidden = reached || whole; };
  const observer = new IntersectionObserver(
    ([entry]) => { reached = entry.isIntersecting; update(); },
    { rootMargin: "0px 0px -15% 0px" },
  );
  const wholeObserver = new IntersectionObserver(
    ([entry]) => { whole = entry.intersectionRatio >= 1; update(); },
    { threshold: 1 },
  );
  // The footer is stuck to the bottom of the window and wraps when the window
  // is narrow, so the pill sits above however tall it is right now.
  const clearFooter = () => {
    const footer = document.querySelector("." + data.footerClass);
    const bar = footer && (footer.closest("[data-testid=stLayoutWrapper]") || footer);
    button.style.marginBottom = (bar ? Math.round(bar.offsetHeight) : 0) + "px";
  };
  const sync = () => {
    clearFooter();
    const found = document.querySelector("." + data.sectionClass);
    const usable = found && found.offsetHeight > 0 ? found : null;
    if (usable === target) return;
    if (target) {
      observer.unobserve(target);
      wholeObserver.unobserve(target);
    }
    target = usable;
    if (target) {
      observer.observe(target);
      wholeObserver.observe(target);
    } else {
      reached = false;
      whole = false;
      button.hidden = true;
    }
  };
  const schedule = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; sync(); });
  };
  const mutations = new MutationObserver(schedule);
  mutations.observe(document.body, { childList: true, subtree: true });
  window.addEventListener("resize", schedule);
  sync();
  button.onclick = () => {
    if (!target) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
    // Keyboard users carry on inside the section they just jumped to.
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  };
  return () => {
    window.removeEventListener("resize", schedule);
    mutations.disconnect();
    observer.disconnect();
    wholeObserver.disconnect();
    cancelAnimationFrame(frame);
  };
}
"""


def downloads_section() -> DeltaGenerator:
    """The container a view's downloads go in, which `downloads_cue` scrolls to.

    Returns:
        The container, for use as `with downloads_section():`. Drawing nothing
        in it leaves it empty, and the cue then stays hidden.
    """
    return st.container(key=SECTION_KEY)


def downloads_cue() -> None:
    """Draws the cue. Call it once per view that has a downloads section,
    after `downloads_section()`.

    The component is registered on every call, not once at import: the
    registry belongs to the Streamlit runtime, and a module imported under one
    runtime (AppTest starts one per test) would be unknown to the next. An
    unchanged definition registers again without a warning, so _HTML, _CSS and
    _JS must stay constants: per-call values go in `data`.
    """
    mount = st.components.v2.component("downloads_cue", html=_HTML, css=_CSS, js=_JS)
    mount(
        key="pgr_downloads_cue",
        data={
            "label": ui_text.t("app.downloads_cue"),
            "sectionClass": f"st-key-{SECTION_KEY}",
            "footerClass": f"st-key-{footer.CONTAINER_KEY}",
        },
        width="content",
    )
