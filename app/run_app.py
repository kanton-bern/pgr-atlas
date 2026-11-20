"""Container entrypoint that starts the two background Tornado proxies
(pmtiles_server, derivate_bbox_server) BEFORE Streamlit itself, in the same
process -- instead of app.py's own st.cache_resource-gated calls, which only
fire as a side effect of a real browser session's script execution.

That per-session lazy start is fine for a single-instance deployment (every
request hits the one process, so the first visitor warms it for everyone),
but breaks under k8s multi-replica session affinity: a pod that has never
had a real session sits with both ports CLOSED indefinitely, while
ingress-nginx's cookie affinity for the split /pmtiles-data and
/derivate-bbox Ingress keys its hash
on cookie + backend Service/*port* -- meaning a browser's main "/" session
can be correctly pinned to one pod while its /pmtiles-data requests land on
a DIFFERENT, cold one, 502ing forever regardless of how long the deployment
has been up.

Fix: start both proxies unconditionally, once, before any client can
possibly connect -- so every pod is always ready regardless of which pod
ends up serving which request. Safe to run alongside app.py's own
_ensure_pmtiles_server()/_ensure_derivate_bbox_server() (unchanged, still
needed for a plain `streamlit run app.py` dev/local workflow that doesn't go
through this entrypoint) because pmtiles_server.start()/
derivate_bbox_server.start() are idempotent themselves -- a second call
in the same process is a no-op, not a second thread racing to bind the same
port.

Runs Streamlit itself in the SAME process (not a subprocess/exec) so the
daemon threads started here -- which die with their owning process -- stay
alive for the process's whole lifetime instead of belonging to a short-lived
parent that exits once it has spawned them.
"""

import ctypes
import os
import sys

from dotenv import load_dotenv

# The S3 keys are in this process's environment. Linux lets any process of the
# same user read it (/proc/<pid>/environ), so the upload parser, which is
# started without the keys (polygon_upload.py), could read them here. A
# non-dumpable process closes its /proc entries and its memory to other
# processes of the user. It also writes no core dump, which would hold the
# keys too.
if sys.platform == "linux":
    _PR_SET_DUMPABLE = 4
    if ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        sys.exit(f"prctl(PR_SET_DUMPABLE, 0) failed: {os.strerror(ctypes.get_errno())}")

# A .env next to where the app is started (local development) provides the S3
# credentials. In a container there is none and the environment is used as is.
# probe_core reads its settings when they are used, so loading here is enough.
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import s3_target  # noqa: E402

# Before anything imports probe_core: it binds the bucket at import time.
s3_target.apply()
s3_target.warn_if_no_credentials()

import pmtiles_server  # noqa: E402
import derivate_bbox_server  # noqa: E402
import work_dirs  # noqa: E402

# Uploads and raster results a crashed pod or a closed session left behind.
work_dirs.sweep()

pmtiles_port = int(os.environ.get("PMTILES_PORT", 8505))
pmtiles_bind = os.environ.get("PMTILES_BIND", "0.0.0.0")
derivate_bbox_port = int(os.environ.get("DERIVATE_BBOX_PORT", 8503))
derivate_bbox_bind = os.environ.get("DERIVATE_BBOX_BIND", "0.0.0.0")
# Streamlit reads the same variable; docker/streamlit_config.toml sets 8501.
streamlit_port = int(os.environ.get("STREAMLIT_SERVER_PORT", 8501))

# The tile proxy's /readyz answers for all three servers; the Dockerfile
# HEALTHCHECK uses it.
pmtiles_server.start(
    pmtiles_port,
    pmtiles_bind,
    ready_urls=(
        f"http://127.0.0.1:{streamlit_port}/_stcore/health",
        f"http://127.0.0.1:{derivate_bbox_port}/healthz",
    ),
)
derivate_bbox_server.start(derivate_bbox_port, derivate_bbox_bind)
print(
    f"pmtiles_server on {pmtiles_bind}:{pmtiles_port} "
    f"(prefix {os.environ.get('PMTILES_PATH_PREFIX', '')!r}), "
    f"derivate_bbox_server on {derivate_bbox_bind}:{derivate_bbox_port} "
    f"(prefix {os.environ.get('DERIVATE_BBOX_PATH_PREFIX', '')!r}), "
    f"readiness at :{pmtiles_port}/readyz",
    file=sys.stderr,
    flush=True,
)

from streamlit.web import cli as stcli  # noqa: E402

if __name__ == "__main__":
    stcli.main(args=["run", "app.py"], prog_name="streamlit")
