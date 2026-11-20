# Style tokens: Kanton Bern web style guide → pgr-atlas

Source: Web-Styleguide Kanton Bern,
<https://kantonbern.snowflake.ch/styleguides/1/Kanton-Bern/>, fetched 2026-10-05. The guide is
live and can change. Pattern IDs (`A2`, `M9`, …) and states come from its `info.csv`. Colours
come from its "Styles" page (`styles_all.html`). Sizes are the computed styles of the pattern
pages at 1440 px width.

Pattern states: **Freigegeben** = approved, **Zur Abnahme** = awaiting approval (tagged
`[Pending approval]` below), **In Planung** = planned. The colour and typography pages carry
no state; this mapping treats them as approved.

## 1. Colours

### Brand
| Name | Value | Guide use |
|---|---|---|
| Black | `#000000` | text, focus bar, link underline |
| Red | `#EA161F` | brand accent, link hover underline (`--bottom-line-1px-red`) |
| White | `#FFFFFF` | page background, text on dark |

### Backgrounds (sand + grey)
| Name | Value |
|---|---|
| Light Sand | `#FCF8F3` |
| Sand | `#FAF1E3` |
| Dark Sand | `#F7E9D2` |
| Sand (Hover) | `#F2E0C3` |
| Cappuchino | `#EBD3AE` |
| Very Light Grey | `#F8F8F8` |
| Light Grey | `#F2F2F2` |
| Grey | `#DEDEDE` |

### Functional
| Name | Value | 10 % tint (background) |
|---|---|---|
| Dark-Red (error, CTA) | `#D01018` | `#FCE8E9` |
| Blue (info) | `#1775D3` | `#E9F2FB` |
| Green (success) | `#3D8608` | `#ECF3E6` |
| Orange (warning) | `#DD6600` | `#FCEFE5` |
| Anthrazit (primary button) | `#4E4E4E` | hover `#404040` |
| Grey (secondary text, borders) | `#707070` | Line Grey 50 %: `rgba(112,112,112,.5)` |

## 2. Typography

Font: **Roboto**, weights 100, 300, 400, 500, 700 (woff, `roboto-v30-latin-ext_latin-*`).

| Pattern | Size / line height | Weight | State |
|---|---|---|---|
| A2 H1 | 54 / 62 px | 100 | Freigegeben |
| A436 H1 (GDS) | 34 / 42.5 px | 300 | Freigegeben |
| A12 H2 | 30 / 36 px | 300 | Freigegeben |
| A13 H3 | 26 / 32 px | 300 | Freigegeben |
| A80 H4 | 24 / 28 px (21/25 on small screens) | 300 | Freigegeben |
| A81 H5 | 21 / 25 px | 300 | Freigegeben |
| H6 (styles page) | 18 / 21 px | 300 | – |
| A1 Body text | 16 / 26 px | 300 | In Planung |
| A3 Intro text | 16 / 26 px | 500 | Freigegeben |
| A523 Small text | 13 / 16.25 px | 300 | Freigegeben |
| A67 Text link | 16 / 24 px, black, 1 px black bottom border; hover/focus: red border | 400 | Freigegeben |

All text is black (`#000`) on light backgrounds.

## 3. Components

| Pattern | Spec | State |
|---|---|---|
| A27 Primary button | `#4E4E4E` bg, white 16 px/500, pill (radius 49 px), padding 12 × 40 px; hover/focus: `scale(1.07)` | Pending approval |
| A714 Call-to-action button | as primary, bg `#D01018` | Pending approval |
| A29 Secondary button | white bg, 1 px `#4E4E4E` border, `#707070` 16 px/400 text, pill | Pending approval |
| A33/A34 Disabled buttons | `.not-active`, no hover scale | In Planung |
| M9 Input field | bg `#FEFEFE`, 1 px `#707070` border, **square corners**, 16 px/400, floating label 13 px | Pending approval |
| M9 Input focus | 1 px black border + **6 px black left bar** | Pending approval |
| M10 Invalid input | 2 px `#D01018` border, label in `#D01018` | Pending approval |
| M135 Textarea | as input | Pending approval |
| Checkbox / radio focus | 4 px black border on the custom box | Pending approval |

Icons: the guide ships SVG icons (e.g. `information-anthrazit.svg`) and the `uicons-regular-rounded`
icon font.

## 4. Mapping to `app/styles/tokens.css`

The tokens in `app/styles/tokens.css` and where each comes from in the guide. Streamlit's own
widgets take the same values from the theme in `app/.streamlit/config.toml` (`primaryColor`
Anthrazit, `borderColor` `#707070`, `buttonRadius = "full"`).

| Token | Value | Source / note |
|---|---|---|
| `--pgr-bg` | `#FFFFFF` | Guide pages are white (the canton's decision Q1) |
| `--pgr-surface` | `#F8F8F8` (sidebar, quiet boxes) | Very Light Grey (Q2) |
| `--pgr-project` | `#5B7D7E` | Project accent, identity band only; see §4.1 (Q1) |
| `--pgr-brand` | `#4E4E4E` | Anthrazit for primary buttons, active nav and map buttons |
| `--pgr-brand-dark` | `#404040` | Anthrazit (Hover) |
| `--pgr-accent` | `#EA161F` | Red, used sparingly: active-nav marker, link hover line |
| `--pgr-text` | `#000000` | All guide text is black; hover and focus are black too |
| `--pgr-text-muted` | `#707070` | Secondary text and input borders (4.95:1 on white) |
| `--pgr-line` | `rgba(112,112,112,.5)` | Line Grey 50 %: rules between the sidebar nav rows |
| `--pgr-input-bg` | `#FEFEFE` | M9, with a 1 px `#707070` border from the theme |
| `--pgr-radius-input` | `0` | M9's square corners; buttons are pills through the theme (A27) |
| `--pgr-error` / `-info` / `-success` / `-warning` | `#D01018` / `#1775D3` / `#3D8608` / `#DD6600`, error and info with their 10 % tints | Functional colours |
| `--pgr-focus` | `#000000` | Focus colour; see §6 |
| `--mc-font` | `Roboto, Arial, sans-serif` | Typography |
| `--mc-title-size` / `--mc-body-size` | 13 / 12 px, weight 400 | Small text A523 is 13 px; 300 is too thin at 12 px on a map |
| `--mc-radius` | 7 px | The guide has no map chrome; own layout approved (Q4) |
| `--pgr-overview-map-min-height` | 400 px | Own layout: the Simulierte Ereignisse map fills the window down to the footer, but no lower than this |

**App type scale** (the guide's scale is built for content pages; the app is a dense tool):
page title = H4 (24/28, 300), section = H5 (21/25, 300), subsection = H6 (18/21, 300),
body 16 px **400** (A1's 300 is still "In Planung"), small 13 px 400. H1–H3 are not used.

Alerts use the guide's 10 % tints with a functional-colour left border and black text. Data
colours (legend ramps, classes) are not tokens; they stay with the code that draws the data.

### 4.1 Project accent: a nod to the teal (Q1)

Kanton Bern (AWN) wants the guide followed, with a small nod to the project teal `#5B7D7E` if it fits.
Checked against the guide's colour roles and contrast:

| Pair | Ratio | Meaning |
|---|---|---|
| `#5B7D7E` on white / on `#F8F8F8` | 4.49 / 4.23:1 | fine for a non-text shape (≥ 3:1); fails for body text |
| `#5B7D7E` next to Red `#EA161F` | 1.01:1 | same lightness: the two differ only by hue |
| `#5B7D7E` next to Anthrazit `#4E4E4E` | 1.85:1 | too close to tell apart as a state |
| `#3A6162` (dark teal in `logo_2026_*.svg`) on white | 6.85:1 | the logo's own teal; not needed as a token |

There is room for **one** nod, as long as the teal never takes a role the guide already gives to
another colour:
- **Use:** a 4 px band in `--pgr-project` across the top of the whole page that marks the
  project identity. It repeats the teal that the project logo already carries, so it reads as
  part of the logo, not as a second brand colour.
- **Don't use** for the page background, buttons, active navigation, focus, links, alerts or
  text. Those keep the guide's black, Anthrazit and red.
- **Never** place it next to red as a signal (active vs inactive, error vs ok): at 1.01:1 the
  difference disappears for red–green colour-blind users.

### 4.2 Map data colours outside the tokens

Data layers on the maps use data ramps, not the UI tokens. One choice is recorded here because
it was made against the tokens:

- **Gebäudeschatten, selected building's shadow ("zählt als abgeschattet"): `#08519c`** (dark
  blue from the ColorBrewer Blues ramp, accepted by the project owner).
  It sits on the canton's lilac "Im Schatten" mask (`#9b6fc9` at 0.45), so it needs a
  different hue, not a darker lilac. No token fits: Blue (info) `#1775D3` is too close to the
  neighbour pixels' light blue `#5bc4ef` for tritan vision (ΔE 17), and Anthrazit would make
  "counts" vs "excluded" (grey) a lightness-only difference again. Checked with CIEDE2000 after
  a Machado 2009 simulation (protan, deutan, tritan at full severity), composited at the map
  opacities: against the mask ΔE 39.5 / 32.0 / 37.9 / 46.6 (normal / protan / deutan / tritan),
  the old lilac 19.5 / 18.9 / 18.5 / 17.3. Set in `SHADOW_COLOR`, `app/gebaeudeschatten_view.py`.

## 5. Contrast (WCAG 2.1, computed)

AA: text ≥ 4.5:1 (≥ 3:1 for large text, i.e. ≥ 24 px or ≥ 18.7 px bold); UI parts ≥ 3:1.

| Pair | Ratio | Result |
|---|---|---|
| White text on the project teal `#5B7D7E` | 4.49:1 | **fails** for body text (AA large only) |
| Black on white / Light Sand / Cappuchino | 21 / 19.9 / 14.5:1 | AA |
| White on Anthrazit `#4E4E4E` (primary button) | 8.32:1 | AA |
| White on Dark-Red `#D01018` (CTA) | 5.57:1 | AA |
| White on Red `#EA161F` | 4.53:1 | AA (barely) |
| `#D01018` text on white (error) | 5.57:1 | AA |
| `#707070` on white / on `#F8F8F8` | 4.95 / 4.66:1 | AA |
| Light-Grey (`#707070` at 68 %) on white | 2.68:1 | **fails**: don't use for text |
| Blue / Green on white (and white on them) | 4.64 / 4.55:1 | AA |
| Orange `#DD6600` on white (and white on it) | 3.51:1 | **fails** for body text |
| Input border `#707070` on white | 4.95:1 | AA (UI) |
| Line Grey 50 % on white | 1.98:1 | **fails** as a UI boundary (fine as a decorative divider) |
| Grey `#DEDEDE` on white | 1.35:1 | decorative only |

Rules that follow:
- Warnings: never orange text. Use the orange tint `#FCEFE5` + orange left border + black text.
- Light-Grey 68 % and Line Grey 50 % only for decoration, never for text or control borders.

## 6. Focus and keyboard

- The guide's inputs have a clear focus state (black 6 px left bar), and so do checkboxes/radios.
- **The guide's buttons and links have no focus outline**: focus only scales the button
  (`scale(1.07)`) or turns a link's underline red. For WCAG 2.4.7 (focus visible) this is weak,
  and for keyboard users the scale is easy to miss. The app therefore adds
  `outline: 2px solid` in `--pgr-focus` on `:focus-visible` for buttons, links and map controls
  (black on white is 21:1; `app/styles/app.css`, `frontend/src/shared/map-controls.css`). The
  canton approved the outline (Q6).

## 7. Decisions of Kanton Bern (AWN)

The questions the guide left open, and the canton's answers.

| # | Question | Answer |
|---|---|---|
| Q1 | The guide uses a white page. Is the earlier teal app background (`#5B7D7E`) an approved project colour, or should the app follow the guide? (White text on it fails AA by 0.01.) | Follow the guide (white page), and check whether a small nod to `#5B7D7E` fits without breaking the guide's visual line. Checked in §4.1: one identity band |
| Q2 | Sidebar background: Very Light Grey `#F8F8F8` or Light Sand `#FCF8F3`? | `#F8F8F8` |
| Q3 | Buttons, inputs and the body-text weight are "Zur Abnahme"/"In Planung". Can we use them as they are? | Use them; recheck their state in the guide before a release that changes them |
| Q4 | The guide has nothing for map UI (legends, basemap switcher, search, draw tools, tooltips). Is "guide colours + Roboto + our own layout" fine? | Yes |
| Q5 | Logo: the app shows `logo-be.svg` + the project logo `logo_2026_wide.svg`. Does the guide's logo/caption pattern (A137 logo caption, 16 px/400) apply to a web app? | Keep the current logos; use A137 for the caption text. The app name is 24 px/700 instead of A137's 16 px/400, so it reads as the app's title; black as in A137 |
| Q6 | Button focus only scales in the guide. May we add a visible focus outline (§6)? | Yes |

## 8. Fonts

Roboto 300/400/500/700 is self-hosted as woff, from the guide's `fonts/` folder; nothing loads
from a CDN:
- Streamlit: `app/static/fonts/` with `[[theme.fontFaces]]` and `theme.font` in
  `app/.streamlit/config.toml`.
- Map components: the same files, bundled by Vite through `@font-face` in `map-controls.css`.
- Roboto is Apache 2.0, listed in `THIRD-PARTY-LICENSES.md`.
