"""The S3 target the app reads, named in the environment, e.g. "bedag" on the
Bedag stages: Bedag's own S3.

A target is a set of environment variables

    PGR_ATLAS_S3_<NAME>_ENDPOINT_URL   (required: it is what defines the target)
    PGR_ATLAS_S3_<NAME>_REGION / _BUCKET / _ACCESS_KEY_ID / _SECRET_ACCESS_KEY

and PGR_ATLAS_S3_TARGET=<name> picks one. apply() copies the picked target
onto probe-core's PROBE_S3_* variables; run_app.py calls it before anything
from probe_core is imported. A field the target leaves out is removed from
PROBE_S3_*, so probe-core falls back to its own default (for the key: its
older variable names).

Without PGR_ATLAS_S3_TARGET nothing changes and PROBE_S3_* is used as set,
as in local development.
"""

import os
import re
import sys
from urllib.parse import urlsplit

TARGET_VAR = "PGR_ATLAS_S3_TARGET"
FIELDS = ("ENDPOINT_URL", "REGION", "BUCKET", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY")
LABELS = {"bedag": "Bedag", "hosttech": "Hosttech"}
_ENDPOINT_VAR = re.compile(r"PGR_ATLAS_S3_([A-Z0-9]+)_ENDPOINT_URL")


def available() -> list[str]:
    """Names of the configured targets (lower case, sorted)."""
    return sorted(
        m.group(1).lower()
        for var, value in os.environ.items()
        if value and (m := _ENDPOINT_VAR.fullmatch(var))
    )


def current() -> str | None:
    return os.environ.get(TARGET_VAR) or None


def source_label(endpoint_url: str) -> str:
    """Who runs the S3 the app reads, for the footer. Derived from the
    endpoint actually in use, never from the target's name, so a target
    that points somewhere else can't be shown as what it is called."""
    host = urlsplit(endpoint_url).hostname or endpoint_url
    if host.endswith("gos3.io"):
        return LABELS["hosttech"]
    if host.endswith(".be.ch"):
        return LABELS["bedag"]
    return host


def apply() -> str | None:
    """Copies the picked target onto PROBE_S3_*; returns its name, or None
    when no target is picked. An unknown target ends the process: running
    silently against the wrong S3 would defeat the point of the switch."""
    name = current()
    if name is None:
        return None
    if name not in available():
        sys.exit(
            f"{TARGET_VAR}={name!r}, but PGR_ATLAS_S3_{name.upper()}_ENDPOINT_URL "
            f"is not set (configured: {available()})"
        )
    for field in FIELDS:
        value = os.environ.get(f"PGR_ATLAS_S3_{name.upper()}_{field}")
        if value:
            os.environ[f"PROBE_S3_{field}"] = value
        else:
            os.environ.pop(f"PROBE_S3_{field}", None)
    print(
        f"S3 target {name}: {os.environ['PROBE_S3_ENDPOINT_URL']}, "
        f"bucket {os.environ.get('PROBE_S3_BUCKET', '(default)')}",
        file=sys.stderr,
        flush=True,
    )
    return name


def has_credentials() -> bool:
    """True if probe-core finds an S3 key and secret in the environment. Asked
    of probe-core, so the app names no variables of its own. Call after
    apply(): this imports probe_core."""
    from probe_core import s3

    return bool(s3.S3_CONFIG["access_key"] and s3.S3_CONFIG["secret_key"])


def warn_if_no_credentials() -> None:
    """Says at startup what the first page load would otherwise fail on."""
    if not has_credentials():
        print(
            "No S3 credentials: PROBE_S3_ACCESS_KEY_ID / PROBE_S3_SECRET_ACCESS_KEY are not "
            "set. They come from .env (local development) or the stage's Secret (clusters); "
            "every page will show an error until they are set.",
            file=sys.stderr,
            flush=True,
        )
