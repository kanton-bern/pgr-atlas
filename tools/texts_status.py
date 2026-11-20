#!/usr/bin/env python3
"""texts_status -- how much of app/texts.toml has French.

Prints the number of texts and how many have French, then the key of every
text still missing in French, one per line. A missing French text is not an
error (the app shows the German), so this always exits 0. CI prints it in the
unit job's log; the list goes to Kanton Bern (AWN) for translation.

    .venv/bin/python tools/texts_status.py
"""

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def main() -> None:
    sys.path.insert(0, str(APP))
    import ui_text

    texts = ui_text.load_texts(ui_text.TEXTS_PATH)
    missing = [key for key, entry in texts.items() if not entry.get("fr")]
    print(f"{len(texts)} texts, {len(texts) - len(missing)} with French.")
    if missing:
        print(f"Missing in French ({len(missing)}):")
        print("\n".join(missing))


if __name__ == "__main__":
    main()
