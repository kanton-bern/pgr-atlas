# Grafana dashboards

Bedag's Grafana lets the project create dashboards only in two folders, one per stage,
so there are two copies of the same dashboard:

| File | Grafana folder | Dashboard | Opens on |
|---|---|---|---|
| [pgr-atlas-test.json](pgr-atlas-test.json) | `aw3-pgr-atlas-test-r8fpkg4c` | PGR Atlas (test) | data source `aw3-pgr-atlas-test-r8fpkg4c-kb-metrics`, stage test |
| [pgr-atlas-prod.json](pgr-atlas-prod.json) | `aw3-pgr-atlas-prod-mmtqvldq` | PGR Atlas (prod) | data source `aw3-pgr-atlas-prod-mmtqvldq-kb-metrics`, stage prod |

**Edit only the test file.** [make_prod.py](make_prod.py) generates the prod
file from it and changes nothing but the title and the default data source and
stage. Both copies can still switch data source; the stage follows it.

## How to change the dashboards

**The file in this repo is the source. Edit it here and paste it into
Grafana**, not the other way round.

1. Edit [pgr-atlas-test.json](pgr-atlas-test.json) in an editor.
2. In Grafana, open **PGR Atlas (test)** → *Edit* → *Edit as code*.
3. Select everything in that editor, paste the whole file over it, and save.
   The editor checks the text first and marks what it rejects in red; fix those
   lines in the file, not in Grafana, and paste again.
4. Look at the dashboard: does the changed panel show what it should?
5. Generate the prod file: `python3 monitoring/grafana/make_prod.py`. It only
   writes `pgr-atlas-prod.json`; it does not talk to Grafana.
6. Paste [pgr-atlas-prod.json](pgr-atlas-prod.json) into *Edit as code* of
   **PGR Atlas (prod)** the same way, and look at it there.
7. PR, merge.

`python3 monitoring/grafana/make_prod.py --check` says whether the prod file is
up to date with the test one. It does not know what Grafana has.

If someone did change the test dashboard in Grafana's UI, copy its *Edit as
code* text back over the test file before the next edit, or that change is lost
with the next paste. Changes made in the prod dashboard's UI are always lost:
make them on test.

Nothing deploys the dashboards from Git: the pastes in steps 3 and 6 are the
deployment.

## What the files hold

The text Grafana (13, dashboard format v2) shows under *Edit as code*: the
dashboard's content without its uid and folder. Three things the editor rejects:

- **The file from *Export*.** It wraps the same content in `apiVersion`,
  `metadata` and `spec`. Paste only what is inside `spec`.
- **The classic format** (`panels`, `schemaVersion`).
- **A threshold step without `value`.** Every step needs a number, the first
  one too (`"value": 0`).

What the panels show: [docs/monitoring.md](../../docs/monitoring.md), section 8.
