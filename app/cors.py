"""CORS headers for the sidecar servers (pmtiles_server, derivate_bbox_server).

Deployed, the browser reaches the sidecars through a path prefix on the app's
own origin (PMTILES_PATH_PREFIX, DERIVATE_BBOX_PATH_PREFIX), so CORS does not
apply there. It only matters in local port mode, where the map components on
:8501 fetch from another port. Only the origins in SIDECAR_ALLOWED_ORIGINS (a
comma list, default the local Streamlit origins) get an
Access-Control-Allow-Origin header; any other origin gets none, and the browser
blocks its script from reading the response.
"""

import os

_DEFAULT_ALLOWED_ORIGINS = "http://localhost:8501,http://127.0.0.1:8501"


def allowed_origins() -> frozenset[str]:
    """Returns the origins from SIDECAR_ALLOWED_ORIGINS, without trailing slashes."""
    raw = os.environ.get("SIDECAR_ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS)
    return frozenset(o.strip().rstrip("/") for o in raw.split(",") if o.strip())


def set_cors_headers(handler, expose_headers: str = "") -> None:
    """Echoes the request's Origin as Access-Control-Allow-Origin if it is allowed.

    Args:
        handler: the tornado.web.RequestHandler answering the request.
        expose_headers: value for Access-Control-Expose-Headers, sent together
            with an allowed origin; empty sends none.
    """
    handler.set_header("Vary", "Origin")
    origin = handler.request.headers.get("Origin")
    if origin not in allowed_origins():
        return
    handler.set_header("Access-Control-Allow-Origin", origin)
    if expose_headers:
        handler.set_header("Access-Control-Expose-Headers", expose_headers)
