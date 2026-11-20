# PGR-Atlas at Bedag: architecture and operations

How PGR-Atlas runs on Bedag's Kubernetes platform, how a
change gets there, how to release a version, and how to look at a running
stage. It is written for whoever releases or operates the app, and for anyone
who wants to understand the setup. This is the one operations document for the
Bedag setup. Two topics have
their own documents:

- [s3.md](s3.md): the object stores, buckets, keys and the s3-toolbox.
- [monitoring.md](monitoring.md): alert rules, mail routing and the Grafana
  dashboard.

Running the app on your own machine is described in the
[README](../README.md#running-locally).

---

## 1. Overview

PGR-Atlas is one container image. It holds the app's code and no data. All data
is read from S3 object storage at runtime.

Bedag runs the app in two **stages**. A stage is a deployment environment with
its own cluster, namespace and settings.

| | Test | Prod |
|---|---|---|
| Cluster | `kb-common-test` | `kb-common-prod` |
| Namespace | `aw3-pgr-atlas-test-apps` | `aw3-pgr-atlas-prod-apps` |
| Public URL | https://pgr-atlas-test.apps.be.ch | https://pgr-atlas.apps.be.ch |
| Configuration in this repo | `deploy/stages/test` | `deploy/stages/prod` |
| Spill volumes | 2 × 30Gi | 3 × 100Gi |
| Data | Bedag bucket `aw3-pgr-atlas-test`, a copy of Hosttech's `adelboden-test` (one region) | Bedag bucket `aw3-pgr-atlas-prod`, a copy of Hosttech's `maxi` (the whole canton) |
| Alert rules | yes | yes ([monitoring.md](monitoring.md)) |

Both URLs are public, reachable from anywhere. The stages have no other host.

Two rules shape everything below:

- **`main` is the deployed state.** Flux, a tool that runs inside Bedag's
  clusters, reads the `main` branch of this repository and applies what it
  finds under `deploy/stages/`. This way of working is called GitOps: the Git
  repository describes what should run, and the cluster follows it. A change
  reaches a cluster by being merged into `main`.
- **Nobody deploys by hand.** There is no `kubectl apply` and no
  `helm install`. Flux owns the objects, so a manual change would be
  overwritten or would drift away from Git unnoticed. Reading, logs, `exec`
  and throwaway test pods are fine.

Terms used in this document:

| Term | Meaning |
|---|---|
| Pod | one running instance of the app |
| Deployment | the Kubernetes object that keeps the pod alive and replaces it on a new version |
| StatefulSet | like a Deployment, but each pod has a fixed name (`pgr-atlas-app-0`, …) and a volume of its own; the app runs as one |
| Service | a stable address inside the cluster that points to the pod |
| Ingress | the routing rules for HTTP requests coming from outside the cluster |
| PVC | PersistentVolumeClaim: a request for a disk that outlives the pod |
| emptyDir | a scratch folder that is deleted together with the pod |
| Helm chart | a template for Kubernetes objects; `values.yaml` holds the inputs for it |
| HelmRelease | the Flux object that says which chart to render, in which version, with which values |
| Kustomize | assembles the YAML files of a stage and wraps the values files into ConfigMaps and Secrets |
| SOPS | encrypts secrets so that they can be stored in Git |

---

## 2. Architecture and request path

### Ports and processes

Each pod runs two containers. The `app` container has three processes;
`app/run_app.py` starts the two helper servers first and Streamlit last. The
`proxy` container is an nginx that is the pod's only entry port.

| Port | Process | Role |
|---|---|---|
| `8501` | `streamlit` running `app.py` | the app itself, including its WebSocket (`/_stcore/stream`) |
| `8505` | `pmtiles_server.py` (Tornado) | streams the overview map tiles (a PMTiles archive) from S3 with HTTP Range support, which Streamlit's own static file handler does not offer |
| `8503` | `derivate_bbox_server.py` (Tornado) | crops raster mosaics from S3 to the area the map asks for |
| `8080` | nginx in the `proxy` container | the pod's entry port: forwards `/pmtiles-data/` to 8505 and `/derivate-bbox/` to 8503 with the prefix removed, everything else to 8501 ([tools/proxy/README.md](../tools/proxy/README.md)) |

Only 8080 has a Service. The three app ports are reached inside the pod, and
by the kubelet's probes.

### The path of a request

```
Browser   https://pgr-atlas-test.apps.be.ch and https://pgr-atlas.apps.be.ch
   │      (public)
   ▼
the canton's Apache front proxy
   │
   ▼
Ingress "pgr-atlas-ingress"    class kb-ka (ingress-nginx)
   /   -> Service pgr-atlas-app-http :8080
          the cookie pgr-atlas-affinity pins a browser to one pod
   │
   ▼
Pod pgr-atlas-app-<n> of StatefulSet "pgr-atlas-app"
          2 pods on test, 3 on prod, replaced one at a time
   container proxy   nginx :8080, UID 101, read-only
      /pmtiles-data/   -> 127.0.0.1:8505   prefix removed
      /derivate-bbox/  -> 127.0.0.1:8503   prefix removed
      everything else  -> 127.0.0.1:8501   including the WebSocket
   container app     UID 10001
      test: requests 1 CPU / 2Gi · limits 4 CPU / 8Gi
      prod: requests 4 CPU / 8Gi · limits 8 CPU / 16Gi
      /tmp         the pod's own PVC "pgr-atlas-spill-pgr-atlas-app-<n>"
                   (storage class "block"): DuckDB spill, 30Gi test / 100Gi prod
      /data/cache  emptyDir, 5Gi
      /data/work   emptyDir, 5Gi
   │
   ▼
S3 target "bedag" (the only one on both stages):
          x7ba-s3-kakbfe.infra.be.ch:10443, direct,
          allowed by the CiliumNetworkPolicy allow-egress-s3
```

Bedag's platform provides the entry point, the DNS record and the certificate:

- **DNS and TLS.** The public hosts' DNS records and certificates are Bedag's
  and the canton's; this repo holds only the Ingress rules, with
  `tls.type: existing`, and no `DNSEndpoint` or cert-manager annotation.
  Test's rule names its certificate Secret, `pgr-atlas-test-apps-be-ch-tls`;
  prod's names none. The Ingress must keep the name
  `pgr-atlas-ingress`, which the chart builds from the key `ingress` in the
  stage's `values.yaml`.
- **Session affinity.** The Ingress sets the cookie `pgr-atlas-affinity`,
  which pins a browser to one pod. Streamlit keeps a session in the pod's
  memory, and the files of a finished Raster-Karten job and the download ZIPs
  exist only in the pod that made them.
- **Why one Service and the proxy.** ingress-nginx pins per Service. With one
  Service per app port, a session's `/derivate-bbox/` requests could land on
  another pod than its Streamlit session and answer 404 for a job's files.
  One entry port per pod means one Service and one pin for all paths
  (checked: 8 sessions on test and 12 on prod each stayed on
  one pod for the tile and the raster server).
- **WebSocket.** The read and send timeouts are set to 24 hours, so that
  Streamlit's WebSocket is not cut off.

The app reads one S3 **target**: Bedag's own S3. `PGR_ATLAS_S3_TARGET` in the
stage's `values.yaml` is `bedag` on both stages, and the `PGR_ATLAS_S3_BEDAG_*`
variables next to it take endpoint, bucket and key from Bedag's Secret. The
app at Bedag has no Hosttech target, no Hosttech key and no proxy variables;
only the s3-toolbox reaches Hosttech, to copy new data.
The sidebar footer shows the running version, the S3 source and the bucket.
Details: [s3.md](s3.md) and [app/README.md](../app/README.md#configuration).

### What the platform enforces

Bedag's cluster rejects objects that break these rules. They explain most of
the settings in the stage files.

| Rule | Effect on the project's configuration |
|---|---|
| Image registry policy (Kyverno policy `restrict-image-registries`, rule `validate-registries`): only images from `artifacts.bedag.cloud/*` are admitted (a `ghcr.io` image is refused on both clusters) | the stages reference Bedag's mirror `artifacts.bedag.cloud/ghcr/skerlakanalytics/pgr-atlas`, which serves the public image from `ghcr.io` |
| Namespace quota (table below): it counts **requests** for CPU, memory and PVC storage. Limits and ephemeral storage are not part of the quota | the spill volumes take most of the PVC budget (all of prod's); CPU and memory requests leave room on prod, little on test |
| No direct internet access from pods. DNS and the proxy `proxy.kb-bedag.ch:8080` are allowed for every pod. The proxy only lets listed hosts through (checked from the test toolbox: without the proxy the network is unreachable; through it `f712.gos3.io` and `github.com` answer, `example.com` gets `403 Forbidden`) | only the s3-toolbox sets `http_proxy`, `https_proxy` and `no_proxy`, to reach Hosttech S3 through the proxy; the app's pods set none and reach nothing outside the cluster except Bedag's S3 |
| Bedag's S3 is reachable only from pods that a network policy allows | `networkpolicies/` holds a `CiliumNetworkPolicy` for the app pods, `s3-toolbox/` one for the toolbox |
| Containers run as a non-root user | the image runs as UID 10001, and the stage values set the matching security context (all capabilities dropped, seccomp `RuntimeDefault`, `fsGroup: 10001` so that the PVC is writable) |

The quota per namespace (requested by the stage files / hard), from Bedag's
admin and confirmed with a server-side dry run (see "Testing a change without
deploying it"):

| | test | prod |
|---|---|---|
| `requests.cpu` | 2350m / 4 | 12400m / 32 |
| `requests.memory` | 4672Mi / 8Gi | 25184Mi / 64Gi |
| `requests.storage` (PVCs) | 60Gi / 100Gi | 300Gi / 300Gi |

The requested figures add up the app pods (both containers), the s3-toolbox
(250m, 512Mi) and the spill volumes. The project's cluster role cannot read the quota (`resourcequotas` is
forbidden), but a dry run of a request that is too large is refused with a
message that names it:

```bash
# a Pod asking for 100Gi of memory; nothing is created
kubectl -n aw3-pgr-atlas-<stage>-apps create --dry-run=server -f pod.yaml
# ... exceeded quota: capsule-aw3-pgr-atlas-<stage>-0, requested: requests.memory=100Gi,
#     used: requests.memory=<used>, limited: requests.memory=64Gi
```

The same works for `requests.cpu`, and for `requests.storage` with a 1Gi
PersistentVolumeClaim (storage class `block`). The Pod has to pass the other
admission checks first: an image from `artifacts.bedag.cloud/*` and the
security context of the app's containers.

### Storage and sizing

| | test | prod |
|---|---|---|
| Pods | 2 | 3 |
| CPU per pod (reserved / limit) | 1 / 4 | 4 / 8 |
| Memory per pod (reserved / limit) | 2Gi / 8Gi | 8Gi / 16Gi |
| Spill volume per pod | 30Gi | 100Gi |
| `PROBE_DUCKDB_MAX_TEMP_SIZE` | 27GiB | 90GiB |

The proxy container adds 50m CPU and 32Mi of reservations per pod.

- **Why a StatefulSet.** The spill volume is `ReadWriteOnce`: it attaches to
  one pod. So each pod gets its own, from `extraVolumeClaimTemplates`, named
  `pgr-atlas-spill-pgr-atlas-app-<n>`. The size of a claim template cannot be
  changed later without deleting the StatefulSet, and a StatefulSet never
  deletes its claims: after scaling down, remove the leftover claim by hand.
- **Deployments keep the app up.** Pods are replaced one at a time, highest
  number first. The browsers of the pod being replaced are pinned to another
  pod and start a fresh session.
- **What is per pod and not shared:** sessions, running raster jobs, the cache
  and work folders, and the spill.
- **Why not more pods on test.** Its quota is 4 CPU and 8Gi of requests and
  100Gi of PVC storage; two pods and the s3-toolbox use 2350m, 4672Mi and 60Gi.
  Prod has 32 CPU, 64Gi and 300Gi, of which the three spill volumes take all
  of the storage.
- **Why the spill is a PVC.** DuckDB writes intermediate data to disk when a
  query does not fit into its memory budget. This is called spilling, and a
  raster job spills tens of gigabytes. Bedag's disk budget is PVC storage. An
  emptyDir would land on the node's shared disk.
- **`PROBE_DUCKDB_MAX_TEMP_SIZE`** caps the spill at about 90 % of the pod's
  volume (`27GiB` on test, `90GiB` on prod). DuckDB cannot see the size of the
  volume, and the raster job's work database lies in the same folder. Write
  `GiB`: DuckDB reads `GB` as 10^9 bytes. With the cap, a job that needs more
  space fails with an error instead of filling the volume.
- **Leftovers on the spill volume.** `/tmp` outlives the pod. Each raster job
  spills into a folder of its own, and the first step of every job deletes
  folders older than 7 days (`sweep_raster_temp` in probe-core).
- **Work folder.** Uploads, raster results and the cached exceedance curves of
  raster jobs live in `/data/work`. Entries older than 7 days are deleted at
  startup and whenever a new folder is made (`app/work_dirs.py`). A pod restart
  empties `/data/work` and `/data/cache`.
- **One raster job at a time** (`MAX_RUNNING` in `app/raster_jobs.py`). A job
  gets DuckDB's full memory budget and uses every CPU. A second job waits in a
  queue and can be cancelled.
- **Size limits of a raster job.** The number of map tiles ("Kacheln") per job
  is capped from the container's memory limit, about 81 at 8Gi. A selection
  may also read at most `PROBE_RASTER_MAX_ROWS` rows (default 900 million).
- **Memory and CPU are read from the container's limits**, not from the node,
  so the app sizes itself correctly when the limits in `values.yaml` change.

`run_app.py` starts both helper servers before Streamlit accepts connections,
so every pod serves all three paths from its first request.

### Measured resource use

These values were measured once, on the test stage with one pod and limits of
4 CPU and 8Gi, for the largest raster a job may compute at
8Gi (81 Kacheln). The raster computation has changed since, so treat them as
an order of magnitude. They are the basis for the alert thresholds in
[monitoring.md](monitoring.md).

| | Observed |
|---|---|
| Duration | about 1 h 56 min |
| Memory | working set about 5 GiB, peak 6.6 GiB of 8 GiB, no out-of-memory kill |
| CPU | 1 to 2.8 of 4 cores |
| Spill in `/tmp` | 8 to 41 GB most of the time, peak 64.7 GB; empty again after the job |
| Network | about 8 MB/s from S3 on average |

The limit was DuckDB's memory budget, which is a fraction of the container's
memory. It forces DuckDB to spill and read back while the CPUs wait. A job
keeps running when the browser disconnects.

They were not measured again for the current layout. Prod's pods have twice
the memory (16Gi) and a spill volume of 100Gi each, so the spill cap is 90GiB
per pod. That cap was accepted without a test run: the one measured peak,
64.7 GB, is below it, and more memory per pod means less spilling. If a raster
job ever fails with DuckDB's error about the temp directory size on prod,
this is the assumption to revisit.

---

## 3. GitOps: from a merge to a running pod

### What is in `deploy/stages/`

```
deploy/stages/
  base/pgr-atlas/     HelmRelease and the values shared by every stage
  base/monitoring/    alert rules, the same on every stage
  test/               everything specific to test
  prod/               everything specific to prod
    pgr-atlas/
      values.yaml       the app on this stage: image tag, resources, env, Ingresses
      secrets/          secret-values.yaml, SOPS-encrypted
      networkpolicies/  egress to Bedag's S3
      s3/               Bedag's S3Tenant and S3Bucket (s3.md)
    s3-toolbox/         the toolbox pod (s3.md)
    monitoring/         takes in base/monitoring/ for this stage
```

The app itself is rendered by Bedag's Helm chart `common`, version `12.6.0`.
`base/pgr-atlas/values.yaml` says which kinds of objects the chart renders. The
stage's `values.yaml` describes the app. Both stages use the same base and the
same chart, and a stage file contains only what differs.

Kustomize turns a stage folder into these objects:

| Object | Source | Purpose |
|---|---|---|
| ConfigMap `pgr-atlas-values` | `base/pgr-atlas/values.yaml` | Helm values for all stages |
| ConfigMap `pgr-atlas-stage-values` | `<stage>/pgr-atlas/values.yaml` | Helm values of this stage; they win over the base |
| Secret `pgr-atlas-stage-secrets` | `<stage>/pgr-atlas/secrets/secret-values.yaml` | secret Helm values, decrypted by Flux |
| HelmRelease `pgr-atlas` | `base/pgr-atlas/helmrelease.yaml` | tells Flux to render the chart with the three sources above |
| CiliumNetworkPolicy, S3Tenant, S3Bucket | the stage's subfolders | applied as they are |
| Deployment `s3-toolbox` and its network policy | `<stage>/s3-toolbox/` | a plain manifest, not part of the HelmRelease, so it does not restart with the app |
| PrometheusRule, ServiceMonitor | `base/monitoring/`, through `<stage>/monitoring/` | alerting; where alerts go is applied by Bedag from `deploy/applied-by-bedag/` |

The ConfigMaps and the Secret only carry values. The HelmRelease is what makes
Helm run. From it Helm creates the StatefulSet `pgr-atlas-app`, the Service
`pgr-atlas-app-http`, the Ingress `pgr-atlas-ingress` and the Secret
`pgr-atlas-app-app` with the app's secret environment variables. The spill
volume claims are created by the StatefulSet, one per pod.

### The chain

```
   merge into main
          │
          ▼
┌──────────────────────┐
│ GitRepository        │  Flux fetches branch main
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ Kustomization        │  path deploy/stages/<stage>
│                      │  - decrypts the secrets (SOPS)
│                      │  - replaces ${stage} with test or prod
│                      │  - applies the objects in the table above
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ HelmRelease          │  chart "common" 12.6.0, checked every 5 minutes
│                      │  values: base + stage + secrets
└──────────┬───────────┘
           ▼
  StatefulSet (and its pods' PVCs), Service, Ingress, Secret
```

The GitRepository and the Kustomization are Bedag's objects. They live in the project's
namespace, but their definitions are not in this repository. Read from both
clusters:

| Object | Name | Settings |
|---|---|---|
| GitRepository | `aw3-pgr-atlas-<stage>-source` | this repository, branch `main`, fetched every 5 minutes |
| Kustomization | `aw3-pgr-atlas-<stage>` | path `deploy/stages/<stage>`, every 5 minutes and when the source changes, `prune: false`, SOPS decryption, `${stage}` substituted |
| HelmRelease | `pgr-atlas` | chart `common` 12.6.0, every 5 minutes |

Four things to know:

1. **A merge takes up to about ten minutes to become a running pod.** Up to 5
   minutes until Flux fetches `main`, then up to 5 more for Helm (measured:
   4 minutes to the Kustomization, 8 to the new pod). Flux
   applies the new values ConfigMap first. The HelmRelease only refers to that
   ConfigMap and does not change itself, so Helm notices on its next
   5-minute check. `flux reconcile helmrelease` skips that wait (section 5).
2. **Objects removed from Git stay in the cluster.** Bedag's Kustomization
   runs with `prune: false`. To remove such an object, delete it by hand or
   ask Bedag. Objects that Helm renders are different: a Helm upgrade removes
   what the chart no longer renders.
3. **Pushing a branch deploys nothing.** Only `main` is read.
4. **A stage is applied all or nothing.** Flux checks every object of the
   stage first, and if the cluster refuses one of them, it applies none.
   The merged pull request is green and the old pods keep running, so
   nothing shows it except the Kustomization's status, and a stage can stay
   behind for weeks: one object Flux's service account may not apply (such
   as an `AlertmanagerConfig`, which is why those are in
   `deploy/applied-by-bedag/`) blocks every later commit. After a merge that changes a stage,
   check that Flux applied it (section 6, "Is the deployment through?").

### Secrets

Two files per stage are encrypted with SOPS: the app's secret Helm values in
`deploy/stages/<stage>/pgr-atlas/secrets/secret-values.yaml` (empty, see
below) and the s3-toolbox's Hosttech key in
`deploy/stages/<stage>/s3-toolbox/hosttech-key-secret.yaml`. They are
encrypted for Bedag's PGP key (`.sops.yaml`, public key in
`aw3-gitops-sops.asc`). The private key is in Bedag's cluster, as the Secret
`sops-gpg` in each of the project's namespaces, which Flux decrypts with. So the files
cannot be decrypted from the repository alone. Whoever has the project's
access to the cluster can read that Secret and with it decrypt them.
Access to the cluster needs the VPN and two layers of multi-factor
authentication (section 7), which is
what protects the key. No copy of it is kept outside the cluster, and none is
needed: to change a credential, the file is written again and
encrypted with the public key
([app/README.md, Configuration](../app/README.md#configuration)).

`secret-values.yaml` sets the app container's `envSecret`. It is empty, so
the chart renders no Secret `pgr-atlas-app-app`: the app needs
no secret of its own. The file stays, because Flux does not prune and the old
Secret would otherwise keep its content. The keys for Bedag's S3 are not in
Git: Bedag's operator creates them as Secrets in the namespace
([s3.md](s3.md), section 2).

---

## 4. CI and images

CI (continuous integration) runs on GitHub Actions. The workflows are in
`.github/workflows/`.

| Workflow | Trigger | Result |
|---|---|---|
| **CI** (`ci.yml`) | every pull request that changes more than docs; called by Build and push for a tag | hooks, secrets scan, stage build, workflow audit, Python lint |
| **Unit tests** (`unit.yml`) | pull request that changes what the unit tests read; called by Build and push for a tag | `pytest` without the component tests |
| **Frontend** (`frontend.yml`) | pull request that changes `frontend/` or what the component tests read; called by Build and push for a tag | `frontend/` lint, type check, Vitest and build; the map-component tests |
| **Build and push** (`build-and-push.yml`) | push to `main` that changes what the image contains | image `:main` |
| | tag `vX.Y.Z` | image `:vX.Y.Z` and `:latest` |
| | manual run on a branch (Actions tab) | image `:<branch>` |
| **E2E** (`e2e.yml`) | tag `vX.Y.Z`, label `e2e` on a pull request, manual | browser tests against the `adelboden-test` bucket |
| **AppTest** (`apptest.yml`) | tag `vX.Y.Z`, label `apptest` on a pull request, manual | Streamlit's `AppTest`, view by view, against the `adelboden-test` bucket |
| **Build and push s3tools** (`build-s3tools.yml`) | tag `s3tools-vX.Y.Z`, manual | the toolbox image ([tools/s3/README.md](../tools/s3/README.md#releasing)) |
| **Build and push proxy** (`build-proxy.yml`) | tag `proxy-vX.Y.Z`, manual | the nginx proxy image ([tools/proxy/README.md](../tools/proxy/README.md)) |
| **Clean up old images** (`cleanup-images.yml`) | daily at 03:00 UTC, manual | deletes untagged image versions older than 1 day |
| **Scan images** (`scan-images.yml`) | Mondays at 05:00 UTC, manual | Trivy re-scan of the images the stages run |

Scan images opens an issue when red and closes it when green
(`.github/scripts/alert-issue.sh`).

CI is three workflows with one job each, so a pull request gets its results
in parallel. GitHub bills each job rounded up to a full minute, so the quick
checks share one:

- **CI** (`ci.yml`), job `checks`: the pre-commit hooks and a `gitleaks` scan
  for secrets; `kustomize build` of `deploy/stages/test` and `prod`, and a
  check that every `secret-values.yaml` is SOPS-encrypted; `actionlint` and
  `zizmor` on the workflow files; `ruff check` and `ruff format --check`. Under
  a minute.
- **Unit tests** (`unit.yml`): `pytest` without the component tests, about a
  minute. These tests mock S3 and need no credentials.
- **Frontend** (`frontend.yml`): ESLint, Prettier, type check, Vitest and a
  build of `frontend/`, then the map-component tests (`tests/components`) in
  Chromium, in the Playwright container, about four minutes.

CI runs on every pull request that changes more than Markdown and `docs/`
(Markdown under `app/legal/` counts). Unit tests run only when it changes
`app/`, `tests/` (not `tests/components/`), `packages/` or `tools/`, and
Frontend only when it changes `frontend/`, `tests/components/` or
`app/styles/tokens.css`. A change to `pyproject.toml` or `uv.lock` runs both,
and a change to a workflow file runs that workflow. Markdown files count for
Unit tests only under `app/legal/`, and never for Frontend. The three start at
the same time and don't wait for each other: a failed lint doesn't stop the
tests. For a release all three run.

**A green pull request** means every workflow that started on it passed. A
workflow whose paths the pull request doesn't touch doesn't start and isn't
listed among its checks, so it doesn't count: a Python-only pull request is
green with CI and Unit tests, a `frontend/` change with CI and Frontend. The
rule for merging is in [CONTRIBUTING.md](../CONTRIBUTING.md#code-reviews).

To run the same checks before opening a pull request: the commands in
[AGENTS.md](../AGENTS.md#commands).

To have the two ruff checks run on every commit, turn on the repo's git hook
once per clone: `git config core.hooksPath .githooks`. It checks the staged
Python files and stops a commit that CI would reject. It is a plain git hook
(`.githooks/pre-commit`), because `.pre-commit-config.yaml` starts with Bedag's
hook repository, which is reachable only from Bedag's network.

**CI gates a release.** For a version tag, Build and push calls all three CI
workflows first and builds only when all three pass. A push to `main` builds
`:main` without running CI again, because its pull request ran it.

**E2E and AppTest run per release, not per pull request.** Both need the
Hosttech S3 key from the repository secrets (an account-wide key, see
[s3.md](s3.md), section 6) and take about 8 and 20 minutes on CI. They start when a
version tag is pushed. For a branch that changes the app's behaviour, start
them with the label `e2e` or `apptest` on its pull request (one run per label
added; remove and add it again for another), or by hand:
`gh workflow run e2e.yml --ref <branch>`. When each is needed:
[tests/README.md](../tests/README.md#test-scope). They don't gate the image,
so an outage of the test bucket can't block a release.

**Pushes to `main` that change nothing in the image build no image**: only
Markdown, `docs/`, `tests/`, `deploy/` or `.github/` (the `paths-ignore` of
`build-and-push.yml`). Release tags always build.

GitHub Actions and base images are pinned to commit SHAs and digests.
Dependabot (`.github/dependabot.yml`) proposes updates weekly.
Dependabot alerts and security updates are on for the repository: a known vulnerability in a Python or npm dependency raises an
alert and, where a fixed version exists, a pull request.

**Every image is scanned before it is pushed.** The three build workflows run
Trivy on the freshly built image: its OS packages, Python packages and the
binaries copied in (rclone, AWS CLI). The build fails, and nothing is pushed,
for a HIGH or CRITICAL finding that has a fixed version. A finding the maintainers accept
goes into `.trivyignore` at the repo root, with its reason. Trivy runs as an
image pinned by digest in the workflow files, like gitleaks; Dependabot does
not update that pin.

**The images that run are scanned again every week.** A CVE published after a
build goes unnoticed while that release keeps running, and nobody else scans
these images for the project. `scan-images.yml` reads the tags the stages run from Git
(the app and proxy `image.tag` in each stage's `values.yaml`, the toolbox
image in `s3-toolbox/deployment.yaml`) and scans each one on ghcr.io with the
same Trivy, flags and `.trivyignore`, on Mondays and on demand. Its job
summary lists each image's findings; a red run means a running image needs a
new release and a stage bump, or the finding a reasoned `.trivyignore` entry.
On `main`, a red run also opens an issue labelled `alert: image scan` with the
findings, assigned to `ALERT_ASSIGNEE` in the workflow (GitHub mails the
assignee and the repo's watchers); a later run comments only when the findings
change, and the first clean run closes it (`.github/scripts/alert-issue.sh`).

The app and toolbox Dockerfiles run `apt-get upgrade`, and the proxy's (Alpine)
`apk upgrade`, so an image carries the security fixes of its build day and not
only those of the pinned base image. The proxy needs it because the upstream
nginx image can lag behind Alpine's fixes.

### Image tags

| Trigger | Tags | Used by |
|---|---|---|
| git tag `vX.Y.Z` | `:vX.Y.Z`, `:latest` | the Bedag stages pin a release; `:latest` for a quick local run of the newest release |
| push to `main` | `:main` | quick local checks of the newest `main` |
| manual run on a branch | `:<branch>` | trying an unmerged branch at Bedag in a throwaway pod |

A **release tag** (`:vX.Y.Z`) never moves. It is what the stages run and what
you roll back to. A **rolling tag** (`:main`, `:latest`, `:<branch>`) always
points to the newest build of its kind.

There are no per-commit tags. Tagged images are never deleted automatically, so
they would pile up with every push. When a rolling tag moves, the image it
pointed to before becomes untagged, and the cleanup workflow deletes it after
one day. Tags of manually built branches stay until someone deletes them on the
package page.

To find out which commit a rolling image was built from:

```bash
docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' <image>
```

### The image is public

The image is on `ghcr.io/skerlakanalytics/pgr-atlas`, and anyone can pull it
without logging in. That is why the stages need no image pull secret
(`registry.pullSecret.enabled: false`). The alternative would be a GitHub token
per stage, encrypted in the repository and renewed whenever it expires.

This is safe because the image holds no secrets and no data. Credentials reach
the app only at runtime, from the Secrets described in section 3. CI pushes
with the job's own `GITHUB_TOKEN`.

**Everything under `app/` ends up in a public image**, and so does the
`probe-core` package. Never add credentials, `.env` files or infrastructure
configuration there, and never pass secrets into `docker build`
([app/README.md](../app/README.md#the-image-is-public)).

Bedag's clusters pull the same image under a different address:
`artifacts.bedag.cloud/ghcr/skerlakanalytics/pgr-atlas:<tag>`. On your own
machine, use `ghcr.io` directly.

---

## 5. Releasing a version

Test and prod each run exactly the version set as `image.tag` in their
`values.yaml`. Pushing to `main` builds an image but does not change what runs.
Only changing that value does. This is the gate between test and prod: each
stage moves when someone changes its line.

Version numbers follow `vMAJOR.MINOR.PATCH`. A fix raises the patch number
(`v0.1.0` to `v0.1.1`), a new feature the minor number (`v0.1.1` to `v0.2.0`).
From `v1.0.0` on, the major number goes up (`v1.4.2` to `v2.0.0`) when a release
breaks something users or other systems rely on: a URL or view is removed or
changed so that links and bookmarks stop working, probe-core's API changes so the
pipeline has to change too, or the data the app reads or exports changes its
format. The release notes then say what breaks and what to do.

Release notes are published as a GitHub Release of the version tag (on GitHub,
*Releases* → *Draft a new release*, choose the tag).

**1. Tag the release on `main`**, once the change is merged:

```bash
git switch main && git pull
git tag -a v0.2.0 -m "short description of what changed"
git push origin v0.2.0
```

Always tag a commit on `main`, never a work branch, so that every release is
reviewed code.

**2. Wait for the image.** On GitHub, under Actions, the "Build and push" run
for `v0.2.0` must be green. If the stage is changed before the image exists,
the pod cannot start (`ImagePullBackOff`).

The tag also starts the "E2E" and "AppTest" runs, which test the release
against the test bucket. The pull requests of step 3 do not run them again,
so look at those two runs and merge only when they are green.

**3. Deploy to test.** Once the image is pushed, the "Build and push" run opens
two pull requests, "Test stage: image v0.2.0" and "Prod stage: image v0.2.0",
assigned to whoever pushed the tag. Each changes one line of its stage's
`values.yaml`:

```yaml
            image:
              repository: artifacts.bedag.cloud/ghcr/skerlakanalytics/pgr-atlas
              tag: "v0.2.0"     # the only line that changes
```

CI does not start on them by itself: they are opened by a workflow, so GitHub
holds their CI run until a maintainer clicks "Approve workflows to run" on the
pull request. Then CI (`ci.yml`) runs, as on any change to `deploy/`. The
release itself was checked before the image was built. If the run could not
open them, make the same change by hand on a branch.

Merge the test stage's pull request into `main`. Flux deploys it within about
ten minutes. With cluster access (section 7) you can watch it:

```bash
# READY True and "Applied revision: main@sha1:<the merge commit>"; if it says
# False, the stage is stuck and nothing was applied (section 3, point 4)
kubectl -n aw3-pgr-atlas-test-apps get kustomizations.kustomize.toolkit.fluxcd.io
kubectl -n aw3-pgr-atlas-test-apps get helmrelease pgr-atlas     # READY True, new revision
kubectl -n aw3-pgr-atlas-test-apps get pods -o jsonpath='{..image}'; echo
flux reconcile helmrelease pgr-atlas -n aw3-pgr-atlas-test-apps  # skips the wait
```

**4. Check the app on test.** Open it in the browser. The sidebar footer shows
the running version. Run a raster job if the change touches computation.

**5. Deploy to prod.** Merge the prod stage's pull request from step 3.
Prod is moved by the project owner, who merges this pull request. Only after step
4: prod gets what test has run, and the footer on test is the proof that test
really runs it. Every other change to a stage (resources, Secrets, the layout
of the pods) keeps the stricter order: test's pull request is merged and
checked first, prod's is opened after that.

**Rolling back.** Set `tag:` back to the previous version and merge. The old
image is still in the registry, because cleanup never deletes tagged images.

**Never move or push a version tag again.** If `v0.2.0` turns out to be broken,
fix it and release `v0.2.1`. A moved tag would mean two different images under
one name, and nodes that already pulled `v0.2.0` would keep running the old
one.

---

## 6. Operating and debugging

The commands below need cluster access (section 7). They use the test
namespace. For prod, use the prod context and `aw3-pgr-atlas-prod-apps`.

### Is the deployment through?

```bash
flux get all -n aw3-pgr-atlas-test-apps          # Git source, Kustomization, HelmRelease
kubectl -n aw3-pgr-atlas-test-apps get helmrelease pgr-atlas
kubectl -n aw3-pgr-atlas-test-apps get pods -o wide
```

An error in the stage files shows up in the Kustomization's status. An error
in the Helm values shows up in the HelmRelease's status.

The one line that says whether a merge has arrived:

```bash
kubectl -n aw3-pgr-atlas-test-apps get kustomizations.kustomize.toolkit.fluxcd.io
# READY True, STATUS "Applied revision: main@sha1:<commit>"  -> applied
# READY False, STATUS "<object> dry-run failed (Forbidden) ..." -> nothing of this
#   and of no later commit is applied until that object is fixed or removed
```

Compare the commit with `git log -1 origin/main`. A stage can be behind for
days without any other sign (section 3, point 4).

**A suspended HelmRelease looks healthy.** It keeps showing `Ready=True` with
the result of its last upgrade, and ignores every change and reconcile request
until it is resumed. Check it, and resume it without the `flux` CLI:

```bash
kubectl -n aw3-pgr-atlas-test-apps get helmrelease pgr-atlas -o jsonpath='{.spec.suspend}{"\n"}'
kubectl -n aw3-pgr-atlas-test-apps patch helmrelease pgr-atlas --type=merge -p '{"spec":{"suspend":false}}'
```

Before resuming, check that nothing was changed by hand in the meantime that
Git doesn't have: Helm resets those objects to `values.yaml`.

The project's cluster role may control the Flux objects in the namespace:

```bash
# apply main now instead of waiting (prod: aw3-pgr-atlas-prod)
flux reconcile kustomization aw3-pgr-atlas-test -n aw3-pgr-atlas-test-apps --with-source
flux reconcile helmrelease pgr-atlas -n aw3-pgr-atlas-test-apps

# pause and continue deployments, for example while a release image is still building
flux suspend helmrelease pgr-atlas -n aw3-pgr-atlas-test-apps
flux resume helmrelease pgr-atlas -n aw3-pgr-atlas-test-apps
```

### Is the app healthy?

| URL path | Answers `ok` when |
|---|---|
| `/pmtiles-data/healthz` | the tile server answers |
| `/derivate-bbox/healthz` | the crop server answers |
| `/pmtiles-data/readyz` | Streamlit, the tile server and the crop server all answer |

The startup, readiness and liveness probes of the pod all use `/readyz` on the
tile server's port, so a dead helper server makes the pod not ready. The
startup probe allows five minutes for a cold start. If one of the helper
servers stops inside the process, a watchdog ends the process and Kubernetes
restarts the container.

A passing health check does not prove that the app works: Streamlit runs
`app.py` only when a browser session opens. After a deployment, open the app
in a browser.

### Looking into the pod

```bash
kubectl -n aw3-pgr-atlas-test-apps logs sts/pgr-atlas-app --tail 200 -f
kubectl -n aw3-pgr-atlas-test-apps logs sts/pgr-atlas-app --previous    # the container before the last restart
kubectl -n aw3-pgr-atlas-test-apps describe pod <pod>
kubectl -n aw3-pgr-atlas-test-apps top pod
kubectl -n aw3-pgr-atlas-test-apps exec sts/pgr-atlas-app -- df -h /tmp /data/work /data/cache
kubectl -n aw3-pgr-atlas-test-apps exec -it sts/pgr-atlas-app -- bash
```

- **Events are not readable with the project's cluster role**, so `describe` shows none.
  Diagnose from the pod status and the logs.
- The progress of a raster job ("Kachel i/n") appears in the pod logs
  (`PYTHONUNBUFFERED=1` in the stage values).
- k9s works too, including a shell in the pod.

### Common failures

| Symptom | Likely cause | What to do |
|---|---|---|
| Pod in `ImagePullBackOff` | the tag in `values.yaml` does not exist yet, or has a typo | check the "Build and push" run for the tag; correct the tag through a pull request |
| A pod shows `1/2` | one of its two containers is not ready: `app` until `/readyz` answers (up to 5 minutes after a start), or `proxy` | `kubectl describe pod`; `kubectl logs <pod> -c app` or `-c proxy` |
| A deployment stops after the first pod | the new pod does not become ready, so the StatefulSet does not touch the others; they keep serving | fix the cause or revert; the rollout continues by itself |
| Pod restarted, last state `OOMKilled` | memory use reached the pod's limit (8Gi on test, 16Gi on prod) | check the logs of the previous container; see [monitoring.md](monitoring.md), section 3 |
| Pod evicted | an emptyDir grew beyond its 5Gi limit | the new pod starts empty; find out what filled the folder |
| Raster job fails with a DuckDB error about the temp directory size | the spill reached `PROBE_DUCKDB_MAX_TEMP_SIZE` | check `/tmp` for leftovers; a smaller area needs less |
| HelmRelease not ready after a change to `values.yaml` | the chart rejected the values, or an admission rule rejected an object | read the HelmRelease status; test the object with a server-side dry-run |
| S3 errors in the app | the sidebar footer shows which target and bucket are in use | [s3.md](s3.md) |

### Restarting the app

Deleting a pod is allowed. The StatefulSet creates a new one with the same
name and the same spill volume.

```bash
kubectl -n aw3-pgr-atlas-test-apps delete pod <pod>
```

The other pods keep serving. The sessions and running raster jobs of the
deleted pod are lost, and its `/data/work` and `/data/cache` start empty. Its
spill volume keeps its content.

### Testing a change without deploying it

A server-side dry-run runs every admission check (image policy, quota, Ingress
webhook) and names the rule that would reject the object. It creates nothing.

```bash
kubectl apply --dry-run=server -f <manifest.yaml>
```

This also shows limits that the project's cluster role cannot read, such as the quota.

To try an unmerged branch, build its image with a manual run of "Build and
push" and start it in a throwaway pod. Delete the pod afterwards.

---

## 7. Cluster access

Access needs the Citrix VPN and Teleport, Bedag's access gateway. Install
`tsh`, the Teleport client, in the same major version as the server. Keep a
separate kubeconfig file for Bedag, so that other cluster configurations stay
untouched.

```bash
export KUBECONFIG=~/.kube/bedag.yaml
tsh login --proxy=teleport.ci-bedag.ch:443 teleport.ci-bedag.ch
tsh kube login kb-common-test        # or kb-common-prod
kubectl config set-context --current --namespace=aw3-pgr-atlas-test-apps
```

The kubectl contexts are then named `teleport.ci-bedag.ch-kb-common-test` and
`teleport.ci-bedag.ch-kb-common-prod`.

**What the project's cluster role may do** in the two namespaces:

| Allowed | Not readable |
|---|---|
| pods (including `exec`, logs, port-forward, delete), deployments, services, ingresses, jobs, PVCs, secrets | resource quotas, limit ranges |
| list and patch the Flux objects, so `flux get`, `reconcile`, `suspend` and `resume` work | ConfigMaps, events |
| `kubectl top` | network policies, S3Tenant, S3Bucket and S3Access |
| create `PrometheusRule`, `ServiceMonitor`, `PodMonitor`, `Probe` | `AlertmanagerConfig` |

The same on test and prod (`kubectl auth can-i`). What the role
cannot read can often still be found out with a server-side dry run, which
names the rule that refuses an object (section 6).

`kubectl get secret … -o yaml` shows secrets base64-encoded. Treat the output
as a password.

### kubectl basics

```bash
# Which cluster am I pointed at?
kubectl config get-contexts
kubectl config use-context <context-name>
kubectl config current-context

# Set the default namespace, so that -n is not needed every time
kubectl config set-context --current --namespace=aw3-pgr-atlas-test-apps

# What may I do here?
kubectl auth can-i --list
kubectl auth can-i delete pods -n aw3-pgr-atlas-test-apps

# What runs in the namespace
kubectl get all
kubectl get ingress
kubectl get pvc
kubectl get pods -o wide
kubectl describe pod <name>
kubectl logs <name> [-c <container>] [--previous]
```

---

## 8. Related documents

| Document | Content |
|---|---|
| [s3.md](s3.md) | object stores, tenants, buckets, keys, the s3-toolbox and `s3m` |
| [monitoring.md](monitoring.md) | alert rules, mail routing, Grafana dashboard |
| [tools/s3/README.md](../tools/s3/README.md) | the `s3m` reference and the toolbox image |
| [README](../README.md) | repository layout, running locally, configuration variables |
| [app/README.md](../app/README.md) | the app's code, S3 target switching, verifying a change |
