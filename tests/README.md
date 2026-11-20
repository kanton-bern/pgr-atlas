# Tests

How PGR-Atlas is tested, for anyone changing the code or reviewing a change: the test tiers,
how to run them, when to add or delete a test, what CI runs, and which tests a change needs
([Test scope](#test-scope)).

The unit tests (`tests/test_*.py`, `packages/probe-core/tests/`) mock S3 and need no
credentials. Three browser and app tiers sit on top of them. Each user flow they cover is
listed in
[`docs/frontend-app/behavior-inventory.md`](../docs/frontend-app/behavior-inventory.md).

| Tier | Marker | Needs | What it covers |
|---|---|---|---|
| `components/` | `components` | the `frontend/` build (`npm run build`) | The five MapLibre components (`overview`, `overview_ifk`, `raster_bbox_map`, `anriss_map`, `gebaeudeschatten_map`) loaded on their own in Chromium, fed fake Streamlit render args: the shared chrome (legend, toggles, basemaps, zoom, coordinate search, the map error message), area-class filters, the IFK Anriss legend, reruns and popup, drawing a bbox or polygon (raster map and IFK map), the outline of an IFK area's Anrisse, the raster variable switch, legend and hover value, the raster layer's checkbox and opacity slider, the Raster-Derivate preview and pixel value against a fake crop server. Anriss map: layer box and overlay defaults, hover value, data updates that keep the viewport. Gebäudeschatten map: the mask crop against a fake crop server, its opacity slider, the layer box and cells key, outline overlays, the focus, and the pixel a click or Shift-click sends. |
| `e2e/` | `e2e` | S3 credentials for `adelboden-test` | The real app via `app/run_app.py` in Chromium: boot, sidebar, navigation, vector tiles from the tile sidecar, map chrome inside Streamlit, Experten-Modus, and the flows where a map click reaches Python: opening an Anriss from Simulierte Ereignisse and IFK and coming back, an IFK pixel, the IFK of an area from a rectangle link, a Raster-Karten Mode A run on an uploaded area, the download dialog's link to Rechtliches. |
| `apptest/` | `apptest` | S3 credentials for `adelboden-test` | `app.py` run in-process by Streamlit's `AppTest`, with widget state set directly: the Anriss view and lookup, IFK results and messages for a pixel and for an area (job, Rohdaten, link, reset), Raster-Karten limits, threshold, cancel, reset and Experten-Modus, the Gebäudeschatten view (a building's pixels, a pixel's buildings, reach options). |

The e2e and AppTest suites read fixed places in the test bucket, listed in
[`lake_data.py`](lake_data.py). Both default to `adelboden-test`, so they
never read the production bucket by accident.

Known bugs have tests marked `xfail(strict=True)`: they fail today, and they
turn red once the bug is fixed, so the marker comes off with the fix.

## Writing tests

1. **Use the cheapest tier that can catch the bug**: Vitest, then pytest unit,
   components, AppTest, e2e. E2E is only for what needs a real browser and a
   running app: clicks that reach Python, tiles, URLs, styles.
2. **Test shared code once**: in Vitest, plus one smoke test per component
   that uses it. Don't parametrize a test over every component, except the
   per-component smoke test. Example: the map chrome is tested on Simulierte Ereignisse,
   and `test_loads_without_js_errors` checks the other components.
3. **One behaviour, one test.** Name a new test's flow in
   [`behavior-inventory.md`](../docs/frontend-app/behavior-inventory.md), so
   a second test of the same flow shows up there. If the flow is already
   listed, extend that test or delete one.
4. **Wait for a condition, not a fixed time**: `expect(...)`,
   `wait_for_function`. Use `wait_for_timeout` only to get past a known
   debounce, with a comment that says so.
5. **Keep each tier within its time budget**, checked with `--durations`
   (CI prints the 25 slowest tests): components under 3 min of test time on
   CI (4 billed min), and no single test over 5 s without a reason.

## When to add a test

Add one when:

- you fixed a bug: a regression test at the cheapest tier, which fails
  before the fix;
- the behaviour is named in
  [`behavior-inventory.md`](../docs/frontend-app/behavior-inventory.md) and
  no tier covers it;
- the code handles an error path and nothing triggers it;
- you added shared code: test it where it lives, as rule 2 above says.

Don't add one when:

- another tier already asserts it;
- it asserts implementation: a call count, a private name, DOM structure
  that carries no behaviour;
- it needs a fixed sleep (rule 4 above);
- it pushes a tier past the budgets in rule 5 above without catching
  something the cheaper tiers can't.

A known bug that isn't fixed yet gets `xfail(strict=True)`, as described at
the top of this file, not a skipped test.

Delete or merge tests when:

- a tier is over the budgets in rule 5 above;
- two tests fail together for one cause;
- the behaviour left the inventory;
- an `xfail` starts passing: the marker comes off with the fix, and the
  test goes if another test already covers that flow.

**Coverage is deliberately not measured, and there is no threshold.** The
constraint is the 2,000 free Actions minutes a month, and
[`behavior-inventory.md`](../docs/frontend-app/behavior-inventory.md) is the
coverage map.

## Setup

```bash
uv sync                                   # app + dev tools from uv.lock
.venv/bin/python -m playwright install --with-deps chromium
(cd frontend && npm ci && npm run build)  # the components built from frontend/, into app/*/dist/
```

## Run

```bash
.venv/bin/python -m pytest                            # unit + component tests (default, ~1 min)
.venv/bin/python -m pytest -m e2e                     # full app, started on free ports (~2 min locally, about 8 on CI)
.venv/bin/python -m pytest -m apptest tests/apptest   # AppTest, on its own (6 to 25 min locally, about 20 on CI)
PGR_ATLAS_URL=http://127.0.0.1:8501 .venv/bin/python -m pytest -m e2e   # against a running app
.venv/bin/python -m pytest --headed --slowmo 300      # watch it click
```

Both suites take the S3 credentials from the environment or the repo's `.env`.
Without them, e2e fails with the app log attached, and AppTest fails at its
first test.

AppTest must run with its path: probe-core reads its bucket when it is first
imported, and a full collection imports it earlier, from the unit tests.

A running app used with `PGR_ATLAS_URL` has to allow the test browser's origin
on the sidecars (`SIDECAR_ALLOWED_ORIGINS`), or no vector tiles load.

## CI

What runs on a pull request:

| Workflow | When |
|---|---|
| `ci.yml` (hooks, gitleaks, stage build, workflow audit, ruff) | always, unless the pull request changes only Markdown and `docs/` |
| `unit.yml` (unit), `frontend.yml` (frontend/ lint, Vitest, build, components) | automatically, each when the pull request changes what it tests (paths in [Test scope](#test-scope)) |
| `e2e.yml`, `apptest.yml` | only on request: add the label `e2e` or `apptest`. A label runs its suite once; remove it and add it again for another run |

A release (`v*` tag) runs all of them. E2E and AppTest can also be started by hand for a
branch: `gh workflow run e2e.yml --ref <branch>` (or `apptest.yml`).

E2E and AppTest don't start on their own for a pull request because of their cost in Actions
minutes (the "Billed on CI" column in [Test scope](#test-scope)). They use the S3 key in the repo secrets
`ADELBODEN_TEST_S3_ACCESS_KEY` and `ADELBODEN_TEST_S3_KEY_SECRET`. The tests only read, but the
key can write and delete in every Hosttech bucket, because Hosttech keys are account-wide.

Not a test tier, and never on a pull request: `scan-images.yml` re-scans the images the stages
run with Trivy once a week, about 1 to 3 minutes a run
([deployment-process.md](../docs/deployment-process.md#4-ci-and-images), "The images that run
are scanned again every week").

## Test scope

Which tests a change needs. The paths match the `paths` filters in `ci.yml`, `unit.yml` and
`frontend.yml`, so change the table and the filters together. Markdown files never count, except
`app/legal/` for checks and unit.

| Tier | Local command | On a PR | Billed on CI | Needs it when |
|---|---|---|---|---|
| checks | `.venv/bin/ruff check app tests tools packages` and `.venv/bin/ruff format --check app tests tools packages`; after a workflow change `actionlint` and `zizmor .github/`. The rest (hooks, gitleaks, `kustomize build`, SOPS check) runs on CI only | automatic (`ci.yml`): every PR that changes more than Markdown and `docs/` (Markdown under `app/legal/` counts) | 1 min | any change beyond Markdown: CI runs it anyway; run ruff locally for any Python change |
| unit | `.venv/bin/python -m pytest --ignore=tests/components` (15 s) | automatic (`unit.yml`): `app/`, `tests/` except `tests/components/`, `packages/`, `tools/`, `pyproject.toml`, `uv.lock`, `unit.yml` | 1 min | any Python change, and any change to `app/texts.toml` |
| components | `.venv/bin/python -m pytest tests/components` (~1 min, after `npm run build` in `frontend/`) | automatic (`frontend.yml`, with ESLint, Prettier, type check, Vitest and the build): `frontend/`, `tests/components/`, `app/styles/tokens.css`, `pyproject.toml`, `uv.lock`, `frontend.yml` | 4 min | a map component's look or behaviour |
| e2e | `.venv/bin/python -m pytest -m e2e` (~2 min locally, S3 key in `.env`) | label `e2e` | about 8 min | what a user sees or does in the running app changes: navigation, sidebar, page titles, map clicks that reach Python, the tile sidecars, downloads, `run_app.py`, Streamlit or probe-core upgrades |
| apptest | `.venv/bin/python -m pytest -m apptest tests/apptest` (6 to 25 min locally, S3 key in `.env`) | label `apptest` | about 20 min | a view's logic or messages change (`app/views/`, `ui_text.py`, a German text in `texts.toml`, the Anriss, IFK, Raster-Karten or Gebäudeschatten flows), Streamlit or probe-core upgrades |

E2E and AppTest run for every release anyway, but a break found there holds the release
back: its stage pull requests wait for both runs to be green.
When the last column says a change needs them, run them before the pull request is merged:
locally first, which costs no Actions minutes, or with the label when that's not possible,
for example without the S3 key.
