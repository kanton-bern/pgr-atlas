# Contributing to PGR-Atlas

Thank you for helping. This page is for anyone who wants to change PGR-Atlas: how a change gets
from your branch into the app, and what a pull request needs. The setup, commands and code
conventions are in [`AGENTS.md`](AGENTS.md), the quick reference for everyday work.

To change only the app's German or French texts, you don't need any of this:
[`docs/texts-guide.md`](docs/texts-guide.md) walks you through it in the browser.

## How a change reaches the app

1. Cut a branch from the latest `main` (Branches, below).
2. Make the change, and run the lint and the default tests locally
   ([commands](AGENTS.md#commands)).
3. Open a pull request into `main` with the description below.
4. CI runs the checks that match what you changed (Tests and checks, below).
5. Another maintainer reviews it. Once it is approved and its checks are green, a maintainer
   merges it.
6. The change goes live with the next release: a maintainer tags it and moves test, then prod
   ([deployment-process.md](docs/deployment-process.md#5-releasing-a-version)).

## Code reviews

Every change is reviewed, including those from project members. The project uses GitHub pull requests
for this; the [GitHub documentation](https://docs.github.com/en/pull-requests) explains how they
work.

A maintainer merges a pull request once another maintainer has approved it and its checks are
green. Green means every workflow that started on it passed; a workflow whose paths the pull
request doesn't touch doesn't start and doesn't count
([deployment-process.md](docs/deployment-process.md#4-ci-and-images)).

## Branches

- Nobody pushes to `main` directly. Bedag's Flux deploys from it, so every change goes through
  a pull request into `main`.
- Work on a short-lived branch named `<area>/<topic>`, such as `fix/ifk-legend` or
  `docs/release-steps`, cut from the latest `main`. Short-lived branches stay easy to review and
  rarely conflict.
- One pull request per change, so each can be reviewed, released and reverted on its own.
- Pull requests are merged with a merge commit, so undoing one is a single revert of that
  commit: `git revert -m 1 <merge commit>`.

## Pull request descriptions

A reviewer should understand a pull request in under 30 seconds. The description uses these
sections, in this order; the pull request template has the headings.

| Section | When |
|---|---|
| **What** | Always. One sentence, under 50 words, starting with a verb in the present tense (Adds, Fixes, Removes) |
| **Why** | Always. One to three short sentences, with the issue it closes |
| **Changes** | Always. One idea per bullet, the most important first, tests and cleanup last. More than about five bullets: group them under short bold labels |
| **How to test** | Most pull requests. Two to four steps a reviewer can follow |
| **Risk and rollout** | Only for a migration, a feature flag, a breaking change, or a change to configuration or an environment variable. One line each for risk, rollout and rollback |
| **Screenshots** | When the change is visible in the app |
| **Reviewer focus** | Optional. One or two lines on the file or decision that deserves the most scrutiny |

- Leave out an optional section that doesn't apply, rather than writing "N/A" or "None".
- In How to test, name only the checks you actually ran, with their result
  (`.venv/bin/python -m pytest tests/test_polygon_upload.py` passed, 39 tests). CI reports its
  own results on the pull request; don't repeat them.
- End How to test with a **Not verified** line naming what you didn't or couldn't check: an
  environment, a data volume, a browser, an integration.
- Use plain language, without filler such as "This PR" or "Basically". Put files, functions
  and commands in backticks. Keep bullets flat, without nesting.

## Tests and checks

- CI runs the lint, unit and component tests on a pull request when it changes what they test.
  [`tests/README.md`](tests/README.md#test-scope) lists which paths trigger which tests.
- The browser tests (e2e) and AppTest need the S3 test key and use many Actions minutes, so they
  don't run on a pull request on their own. If a change affects what users see or do in the
  app, run them locally, or add the label `e2e` or `apptest` to the pull request.
- Before you push, run the lint and the default tests locally
  ([commands](AGENTS.md#commands)).

## Texts

User-facing texts, in German and French, live in [`app/texts.toml`](app/texts.toml), not in
the code. [`docs/texts-guide.md`](docs/texts-guide.md) explains how to change them.

## Third-party licenses

When you add or update a dependency, update [`THIRD-PARTY-LICENSES.md`](THIRD-PARTY-LICENSES.md)
too. The file says how to regenerate its lists.

## Security

Never commit a credential: the repository and the container image are public. To report a
vulnerability, follow [`SECURITY.md`](SECURITY.md) rather than opening a public issue.

## Code of Conduct

Please read and follow the [Code of Conduct](CODE-OF-CONDUCT.md).

## Developer documentation

[`README.md`](README.md) covers running, building and deploying the app.
[`docs/README.md`](docs/README.md) indexes the rest of the documentation.
