# Documentation

The map of PGR-Atlas's documentation, for developers, operators and Kanton Bern (AWN). Every
document here is maintained and describes how things are now. Decisions and their reasons are
in [`adr/`](adr/).

New here? Start with [`../README.md`](../README.md) for what the app is,
[`../CONTRIBUTING.md`](../CONTRIBUTING.md) to propose a change, and
[`../AGENTS.md`](../AGENTS.md), the quick reference for everyday work (setup, commands, rules).
To change only the app's texts, go straight to [`texts-guide.md`](texts-guide.md). The domain
terms are explained in [`glossary.md`](glossary.md).

## Current reference

| Document | What it covers |
|---|---|
| [`../README.md`](../README.md) | What the app shows, where it runs, running it locally, how it is built and deployed, repo layout |
| [`../AGENTS.md`](../AGENTS.md) | The quick reference for people and coding assistants: setup, commands, non-negotiables, the working agreement, conventions, security, where to change what, testing |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | How a change reaches the app, reviews, branches, pull request descriptions, tests and checks, for anyone opening a pull request |
| [`../SECURITY.md`](../SECURITY.md) | Reporting a vulnerability, supported versions, scope |
| [`../THIRD-PARTY-LICENSES.md`](../THIRD-PARTY-LICENSES.md) | The open source software and assets the app ships, and how to regenerate the lists |
| [`ONBOARDING_FRONTEND.md`](ONBOARDING_FRONTEND.md) | The mental model, a step-by-step local run with a live frontend mount, and shipping a frontend change. Start here for frontend work |
| [`deployment-process.md`](deployment-process.md) | Architecture and request path, GitOps, CI and images, releasing, operating and debugging, cluster access |
| [`s3.md`](s3.md) | The object stores, buckets and keys, the s3-toolbox and `s3m`, versioning |
| [`monitoring.md`](monitoring.md) | Alerting, the Grafana dashboards and the S3 check, all live on test and prod |
| [`glossary.md`](glossary.md) | The German domain terms (Anriss, Prozessquelle, Kachel, IFK, Umhüllende, Derivate, Gebäudeschatten, …) explained in English |
| [`frontend-app/behavior-inventory.md`](frontend-app/behavior-inventory.md) | Every user flow per view and the test that covers it. The map the tests are written against |
| [`texts-guide.md`](texts-guide.md) | Changing the app's German and French texts in `app/texts.toml`, step by step in the browser. Written for Kanton Bern (AWN) |
| [`frontend-app/style-tokens.md`](frontend-app/style-tokens.md) | The Kanton Bern style guide mapped to `app/styles/tokens.css` |
| [`adr/`](adr/) | Architecture decision records. `0001`: the map components move to Streamlit Components v2 (accepted, not implemented yet) |
| [`../app/README.md`](../app/README.md) | What is in `app/`, changing shared code, configuration, the path convention, verifying a change |
| [`../frontend/README.md`](../frontend/README.md) | Frontend setup, scripts, layout, tilesets, styles and tokens |
| [`../tests/README.md`](../tests/README.md) | The test tiers, how to run them, when to add a test, and the test-scope table |
| [`../tools/s3/README.md`](../tools/s3/README.md) · [`../tools/proxy/README.md`](../tools/proxy/README.md) | The `s3m` tool and the s3tools image; the nginx proxy image |

## Maintenance

`AGENTS.md` is what people and coding assistants read first, so a wrong line there costs more
than a missing one. Keep it true by trigger, not by calendar.

**Fix it in the same PR that caused it:**

- A command in `AGENTS.md` fails or changes. This is the worst kind of rot — fix it first.
- A review catches something a newcomer should have known. One line added.
- The same review comment comes up twice. One line added.
- A path, directory or convention named in `AGENTS.md` moves. Update it; don't leave a pointer.

**Budget.** `AGENTS.md` stays under 200 lines. A section that pushes it over moves to
the README of the area it covers — the file does not get longer.
A rule that only matters for part of the codebase was in the wrong place to begin with.

**Deleting.** A document that no longer describes how things are gets deleted rather than
archived. The git history keeps it either way.
