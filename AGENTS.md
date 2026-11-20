# AGENTS.md

The quick reference for anyone working in this repo, people and coding assistants alike: setup,
commands, the rules that keep the app safe to deploy, and where to change what. How to open a
pull request is in [`CONTRIBUTING.md`](CONTRIBUTING.md); [`docs/README.md`](docs/README.md)
indexes the rest.

PGR-Atlas is Kanton Bern's explorer for process sources and hazard simulations, used by the
canton's hazard analysts. It is a Streamlit app (Python 3.12, managed with uv) with five MapLibre
map components (TypeScript, built with Vite from `frontend/` into `app/*/dist/`). It reads all
its data from one S3 bucket at runtime and stores none itself. Bedag hosts it: their Flux
(a GitOps tool) deploys whatever is on `main`. [`README.md`](README.md) explains what the app
does.

## Setup

```bash
uv sync                                                        # Python, exactly as in uv.lock
.venv/bin/python -m playwright install --with-deps chromium    # for the browser tests
(cd frontend && npm ci && npm run build)                       # the map components
git config core.hooksPath .githooks                            # ruff on staged files, once per clone
```

Running the app needs S3 credentials in a `.env` file at the repo root (git-ignored). The
project owner issues them; [`README.md`](README.md#running-locally) lists the variables. Without
them the app stops and names what is missing.

To work on several branches at once, use one git worktree per branch, each cut from the latest
`origin/main` (`git fetch origin` first). A new worktree has none of the git-ignored parts, so
in it run `uv sync` and the frontend build above, and link the repo's `.env` into its root.
Without a `.venv` the pre-commit hook skips ruff (it says so in one line); without `app/*/dist`
the component tests fail.

## Commands

```bash
.venv/bin/ruff check app tests tools packages          # lint (ruff pinned in uv.lock)
.venv/bin/ruff format --check app tests tools packages # format check
.venv/bin/python -m pytest                             # unit, probe-core and component tests (~1 min), the default gate
.venv/bin/python -m pytest -m e2e                      # full app in a browser (~2 min locally, about 8 on CI, needs S3)
.venv/bin/python -m pytest -m apptest tests/apptest    # AppTest in-process (6 to 25 min locally, about 20 on CI, needs S3)
cd app && uv run python run_app.py                     # run the app locally on 8501/8505/8503
```

In `frontend/`: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run test`
(Vitest), `npm run build`. After changing a workflow in `.github/workflows/`: `actionlint` and
`zizmor .github/`.

## Non-negotiables

- **No direct pushes to `main`.** Flux deploys from it, so every change goes through a pull
  request.
- **Merging, release tags, and changes on GitHub, at Bedag or in an S3 bucket are maintainer
  steps.** They reach users or live data. A coding assistant does one only when asked for that
  specific step.
- **No credentials in Git.** Secrets live in `.env` (git-ignored) and in SOPS-encrypted files
  under `deploy/stages/`.
- **`deploy/stages/` is production.** Flux applies it to the running clusters on merge. Change
  the test stage first, and check the change with a server-side dry run
  ([deployment-process.md](docs/deployment-process.md#testing-a-change-without-deploying-it)).
- **Tests and local runs read the `adelboden-test` bucket only**, a one-region copy of the data.
  Set `PROBE_S3_ENDPOINT_URL` and `PROBE_S3_BUCKET=adelboden-test` explicitly: a `.env` with only
  the keys falls back to probe-core's default bucket `maxi`, the whole canton's data.
- **Everything under `app/` becomes public**: it is copied into a public container image. No
  credentials, `.env` files or infrastructure config there.

## Working agreement

1. **Pull requests** follow [`CONTRIBUTING.md`](CONTRIBUTING.md): one pull request per change,
   from a short-lived branch cut from the latest `main`, merged after one approval and green
   checks, with the description sections listed there.
2. **Measure before optimising.** Show the numbers first, so the pull request proves its gain.
3. **Replace, don't deprecate.** A pull request that supersedes code deletes the old code too.
   The app is the only consumer of its own code, so a second path is only more to maintain. The
   exception is probe-core's API, which the pipeline also uses (Conventions).
4. **Releases:** a `v*` tag builds the app image, and the build opens one pull request per stage
   that sets `image.tag`. Merge test's, check the app on test, then merge prod's
   ([deployment-process.md](docs/deployment-process.md#5-releasing-a-version)). `proxy-v*` and
   `s3tools-v*` tags build the images in `tools/proxy/` and `tools/s3/`; a pull request then
   moves each stage to the new tag.

## Conventions

The linter limits (`pyproject.toml`, `frontend/eslint.config.js`) are kept in sync between both
languages and not repeated here. What a linter cannot check:

- **Names say what a value is, so code reads without its author.** Use full words from the
  domain vocabulary (`selection`, `id_anriss`, `building_pixels`, not `sel`, `v_id`, `b_px`) and
  put units in names (`_m`, `_cm`, `_px`, `_s`). Single letters only in tiny loops, maths and
  LV95 coordinates (`e`, `n`). Prefer a named intermediate step to a long expression, an early
  return to nested conditions, and a named constant to a magic number. A rename never touches
  a contract: session and widget keys, URL parameters, text keys, component arguments, S3
  columns, or probe-core's public names, which the pipeline imports.
- **`app/` modules import each other as top-level modules**, because `pyproject.toml` sets
  `pythonpath = ["app"]` and the image runs from `app/`: `from ui_text import ...`, not
  `from app.ui_text import ...`. Absolute imports only, no `..` paths.
- **User-facing texts go in `app/texts.toml`** (German and French per entry), not inline in a
  view, because Kanton Bern (AWN) edits that file ([`docs/texts-guide.md`](docs/texts-guide.md)). Look a
  text up with `ui_text.t("key", **values)` where it is shown, not at import (the language is
  per session), and pass the key as a literal string so `tests/test_texts.py` can check it. The
  file holds whole sentences, punctuation included; Python passes only formatted values.
  `tools/texts_status.py` lists the keys still missing French. The map components hold no text:
  their `map.*` entries reach them as the `labels` render argument (`app/map_labels.py`).
- **Numbers shown to the user go through `ui_text.fmt_ch`** (or `in_locale` for a format it
  can't write), so they follow the session's language. Pass `lang=ui_text.EXPORT_LANGUAGE` for a
  number in a downloaded file.
- **A radio or select box whose options show a text or a number** (a `format_func` with `t()`
  or `fmt_ch`) gets its key from `language.translated_options("key")`. Streamlit sends the pick
  as the label it shows, so without that a language switch resets it or leaves it in the old
  language.
- **Colours, spacing and typography come from `app/styles/tokens.css`**, so the app and the maps
  share one set of values. No hard-coded hex values. `docs/frontend-app/style-tokens.md` maps
  them to the Kanton Bern style guide.
- **Shared map behaviour goes in `frontend/src/shared/`** and is tested once there, not again
  per component.
- **Code shared with the pipeline lives in `packages/probe-core`**, a package of its own (a uv
  workspace member) so the pipeline can install it without the app. Change it there, in the
  same pull request as the app code that needs it; `uv sync` installs it editable, so there is
  no version to bump. Keep app code out of it, and don't copy its code into `app/`. The pipeline
  pins a release tag of this repo, so a breaking change to its API needs a note in the release.
- **`[tool.ruff.lint.per-file-ignores]` lists legacy debt.** New code passes without an entry;
  an entry goes when its function is split.
- **Known bugs get a test marked `xfail(strict=True)`, not `skip`**: the test turns red once the
  bug is fixed, so the marker comes off with the fix.
- **No Python type checker runs.** Annotate for readers; nothing checks the annotations.
- **Domain terms stay German**, as written, in code, docs and UI: Anriss, IFK, Kachel,
  Gebäudeschatten, Derivate, Simulierte Ereignisse, Experten-Modus.
- **Images in `deploy/stages/` come from Bedag's mirror** `artifacts.bedag.cloud/ghcr/...`:
  Bedag's cluster refuses a `ghcr.io` reference.

## Security

- Secrets live in `.env` and in SOPS-encrypted files under `deploy/stages/`. Keep credentials
  out of test fixtures, pull request descriptions, issues and commit messages too. gitleaks in
  CI catches the obvious shapes, not a key pasted into Markdown prose.
- `deploy/stages/**/secrets/secret-values.yaml` stays SOPS-encrypted; CI checks this.
- The container image is public. Nothing secret goes into it, build arguments included.
- `app/pmtiles_server.py` and `app/derivate_bbox_server.py` are Tornado servers on their own
  ports with their own origin allowlist (`app/cors.py`, `SIDECAR_ALLOWED_ORIGINS`). Treat
  changes there as security-relevant; widen the allowlist only for a real new origin, never to
  make a test pass.
- `app/polygon_upload.py` and `app/derivate_download.py` cap upload and download sizes. The caps
  protect the shared pods; don't raise one to get a single case through.
- A pull request that touches the sidecar servers, upload or download handling, `tools/proxy/`,
  `deploy/`, `.github/workflows/` or credentials gets a security check of its diff before it is
  opened, and names that area in Reviewer focus.
- **The repo is public.** Infrastructure config may be public, Bedag's hostnames, cluster names
  and network policies included (the canton's decision). Credentials may not, except
  SOPS-encrypted. No IP address, personal email address or individual's name in a new file,
  comment, commit message or pull request description.
- Dependabot holds the geo stack, DuckDB and numpy at patch releases on purpose: a larger update
  needs a manual test (`.github/dependabot.yml`). Don't bump one of those by hand in an
  unrelated pull request.

## Where to change what

| To change | Go to |
|---|---|
| What a view shows or does | `app/views/<view>.py`, or `app/gebaeudeschatten_view.py` |
| UI text, German and French | `app/texts.toml`; number formatting and key choice in `app/ui_text.py` |
| Kontakt, Impressum, Rechtliches texts, or the footer | `app/legal/<name>.<lang>.md` (a missing `.fr.md` falls back to German); `app/footer.py` |
| Map behaviour or look | `frontend/src/<component>/`, shared parts in `frontend/src/shared/` |
| Colours, spacing, typography | `app/styles/tokens.css` |
| The Python side of a map component | `app/<name>_component.py` |
| Data reads, the lake schema, IFK and raster maths | `packages/probe-core/src/probe_core/` |
| Tile serving or raster cropping | `app/pmtiles_server.py`, `app/derivate_bbox_server.py` |
| App startup, ports, sidecars | `app/run_app.py` |
| What CI runs and when | `.github/workflows/` and the Test scope table in `tests/README.md`, together |
| What runs in the clusters | `deploy/stages/` (Flux applies it from `main`) |
| Alert rules and scraping; the Grafana dashboards | `deploy/stages/base/monitoring/`; `monitoring/grafana/` |
| Alert mail routing | `deploy/applied-by-bedag/` (Bedag applies it by hand, not Flux) |
| The S3 toolbox | `tools/s3/` (image), `deploy/stages/<stage>/s3-toolbox/` (pod) |
| The nginx proxy in the app pod | `tools/proxy/` |

## Testing

[`tests/README.md`](tests/README.md) is the reference for the test tiers, their commands, when
each is needed and when to add a test. Use the cheapest tier that can catch the bug. The repo
has 2,000 free GitHub Actions minutes a month, so e2e and AppTest run on a pull request only
with the label `e2e` or `apptest`: run them locally first. Stop a locally running app before
AppTest: when the sidecar ports (8503, 8505) are taken, it exits with status 1 and prints
nothing.

## Keeping this file true

[`docs/README.md`](docs/README.md#maintenance) has the maintenance rules. In short: when a
command, path or rule here changes, fix this file in the same pull request.
