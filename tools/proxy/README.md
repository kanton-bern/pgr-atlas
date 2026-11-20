# proxy: one entry port for the app pod

A small nginx that runs as a second container in the app pod at Bedag. It
listens on port 8080 and forwards by path to the three servers of the app
container, on localhost:

| Path | Goes to | Prefix |
|---|---|---|
| `/pmtiles-data/…` | tile server, `127.0.0.1:8505` | removed |
| `/derivate-bbox/…` | raster server, `127.0.0.1:8503` | removed |
| everything else | Streamlit, `127.0.0.1:8501`, including its WebSocket | kept |
| `/proxy-healthz` | answered by nginx itself | |

The whole configuration is [default.conf](default.conf).

## Why

With more than one pod, a browser has to stay on the pod that holds its
session. The Ingress does that with a cookie (`pgr-atlas-affinity`), but it
pins per Service: with one Service per port, a session's `/derivate-bbox/…`
requests can land on another pod than its Streamlit session (see
`app/run_app.py`). Tiles and
raster-derivate crops come from S3 and don't mind. The files of a finished
Raster-Karten job (`/job/<id>/…`) and the download ZIPs (`/download/<id>.zip`)
exist only in the pod that made them (`app/raster_jobs.py`), so any other pod
answers 404 for them.

With this proxy the pod has one port, the stage has one Service and one
Ingress, and the cookie pins everything a browser asks for to the same pod.

## What it does not do

- No TLS, no caching, no access log: the Ingress in front does TLS and logs.
- No buffering: responses are streamed through, because tiles are read with
  `Range` requests and downloads are written while they are built.
- Uploads above 16 MB are refused (`413`); Streamlit's own limit is 10 MB.

## Trying it locally

The proxy reaches the app on `127.0.0.1`, so it has to share the app
container's network, as it does in a pod:

```bash
docker build -t pgr-atlas-proxy:local tools/proxy
docker run -d --name app -p 127.0.0.1:8080:8080 \
  -e PROBE_S3_ACCESS_KEY_ID -e PROBE_S3_SECRET_ACCESS_KEY -e PROBE_S3_BUCKET=adelboden-test \
  -e PMTILES_PATH_PREFIX=/pmtiles-data -e DERIVATE_BBOX_PATH_PREFIX=/derivate-bbox \
  ghcr.io/skerlakanalytics/pgr-atlas:latest
docker run -d --name proxy --network container:app pgr-atlas-proxy:local
# http://localhost:8080
```

The build runs `nginx -t`, so a configuration nginx would refuse fails the
build, not the pod.

## Releasing

```bash
git switch main && git pull
git tag -a proxy-v0.1.0 -m "short description"
git push origin proxy-v0.1.0        # CI builds :v0.1.0 and :latest
```

Then set the new version in the stage's `pgr-atlas/values.yaml` (the `proxy`
container's `tag:`), open a PR and merge it.

The package `pgr-atlas-proxy` must be public on ghcr.io, like the other two
images, so that Bedag's mirror (`artifacts.bedag.cloud/ghcr/…`) can serve it.
A new package starts private: after the first build, switch it to public once
in the package's settings on GitHub.

The base image is nginx's own `nginxinc/nginx-unprivileged` from Docker Hub,
pinned by digest, on nginx's stable branch (even minor versions); Dependabot
proposes its patch releases, and the next stable (1.32) is a manual change. The copy on ghcr.io is not kept
up to date (last build 2025-03), which is why the stages don't use it directly.
