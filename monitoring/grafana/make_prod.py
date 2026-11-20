"""Generate the prod dashboard file from the test one.

Grafana only lets us create dashboards in two folders, one per stage, so each
stage gets its own copy. They differ only in title and the variables' defaults;
everything else comes from pgr-atlas-test.json, the one we edit (README.md next
to this file).

Both files hold what Grafana's "Edit as code" shows (the dashboard's spec in
the v2 format, without uid or folder), so they are pasted there as they are.
This script only writes pgr-atlas-prod.json; it does not talk to Grafana.

    python3 monitoring/grafana/make_prod.py          # writes pgr-atlas-prod.json
    python3 monitoring/grafana/make_prod.py --check  # exit 1 if it is out of date
"""

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE / "pgr-atlas-test.json"
TARGET = HERE / "pgr-atlas-prod.json"

TEST_TITLE = "PGR Atlas (test)"
PROD_TITLE = "PGR Atlas (prod)"
# The variables' defaults on prod, as Grafana's "Edit as code" shows them there.
# The data source's value is its id in Grafana, not its name.
PROD_VARIABLE_DEFAULTS = {
    "datasource": {"text": "aw3-pgr-atlas-prod-mmtqvldq-kb-metrics", "value": "e2227ef0daddab"},
    "namespace": {"text": "aw3-pgr-atlas-prod-apps", "value": "aw3-pgr-atlas-prod-apps"},
}


def render(dashboard: dict) -> str:
    return json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n"


def to_prod(test: dict) -> dict:
    # Catches the classic format, a full export (apiVersion/metadata/spec around
    # it) and the prod or a backup copy saved over the source by mistake
    if "elements" not in test or test.get("title") != TEST_TITLE:
        sys.exit(
            f'{SOURCE.name}: expected the "Edit as code" text of the dashboard '
            f"{TEST_TITLE!r}, found title {test.get('title')!r}"
        )

    prod = copy.deepcopy(test)
    prod["title"] = PROD_TITLE
    variables = {variable["spec"]["name"]: variable["spec"] for variable in prod["variables"]}
    for name, default in PROD_VARIABLE_DEFAULTS.items():
        variables[name]["current"] = dict(default)
    return prod


def main() -> None:
    expected = render(to_prod(json.loads(SOURCE.read_text())))
    if "--check" in sys.argv[1:]:
        if not TARGET.exists() or TARGET.read_text() != expected:
            sys.exit(f"{TARGET.name} is out of date: run python3 monitoring/grafana/make_prod.py")
        print(f"{TARGET.name} is up to date")
        return
    TARGET.write_text(expected)
    print(f"wrote {TARGET.name}")


if __name__ == "__main__":
    main()
