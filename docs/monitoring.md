# Monitoring at Bedag

What Bedag's platform offers for watching the app, what is worth watching,
and the setup.

**Live on test and prod:** twelve alert rules per stage
([prometheusrule.yaml](../deploy/stages/base/monitoring/prometheusrule.yaml),
applied by Flux, section 4), mailed to the alert mailbox through Bedag's AlertmanagerConfig
([deploy/applied-by-bedag/](../deploy/applied-by-bedag/README.md), applied by
Bedag), the app's own S3 check (section 9),
and one Grafana dashboard per stage folder
([monitoring/grafana/](../monitoring/grafana/README.md)). How to check the
setup: section 6. What Bedag confirmed: section 7.

---

## 1. What the platform offers

What the project's cluster role may do (`kubectl auth can-i`, test and prod):

| Object (`monitoring.coreos.com`) | The project's role (test and prod) |
|---|---|
| `PrometheusRule` | get, create |
| `ServiceMonitor`, `PodMonitor` | get, create |
| `Probe` | get, create |
| `AlertmanagerConfig` | **neither get nor create** |

- Bedag runs the Prometheus Operator and a Grafana the maintainers can build dashboards in.
  Bedag's sysadmin offered two ways to alert: `AlertmanagerConfig` and
  `PrometheusRule` (section 5).
- The HelmRelease carries `prometheus.alerting.bedag.ch: "true"`, from Bedag's
  template ([helmrelease.yaml](../deploy/stages/base/pgr-atlas/helmrelease.yaml)).
  What it triggers, and who receives it, is Bedag's setup.
- The app has `/healthz` per server and `/readyz` on the tile proxy (all three
  servers answer). The startup, readiness and liveness probes use `/readyz`.
  Its only Prometheus metrics are those of the S3 check (section 9).
- External reachability is not monitored from outside the clusters. Bedag's
  monitoring checks the stages from inside, so it misses a break in front of
  the pods, such as the canton's Apache front proxy and the Ingress rule
  disagreeing about the host name: the public URLs then answer 404 while every
  pod is healthy, and no rule fires.

Object names the queries below depend on (test, same on prod): StatefulSet
`pgr-atlas-app`, containers `app` and `proxy`, one PVC per pod named
`pgr-atlas-spill-pgr-atlas-app-<n>`, Ingress `pgr-atlas-ingress`, namespace
`aw3-pgr-atlas-<stage>-apps`.

---

## 2. The options

| Option | What it does | Who makes it | In Git? | Needs |
|---|---|---|---|---|
| **Grafana dashboard** | graphs of what Prometheus already collects | the maintainers, in Grafana's UI | no; export the JSON into the repo by hand | read access to Grafana |
| **Grafana alerting** | alert rules clicked together in Grafana | the maintainers, in Grafana's UI | no | a contact point in Grafana |
| **`PrometheusRule`** | alert rules (PromQL + duration) evaluated by Bedag's Prometheus | the maintainers, through Flux | yes | the metrics exist (section 3) |
| **`AlertmanagerConfig`** | where alerts go: route + receiver (email) | Bedag, from this repo (neither Flux nor the project's role may write it); Bedag's own type, not the operator's (section 5) | yes, outside Flux's path | SMTP relay details from Bedag |
| **`ServiceMonitor` / `PodMonitor`** | Prometheus scrapes the app's own `/metrics` | the maintainers, through Flux | yes | the app's `/metrics`: the S3 check (section 9) |
| **`Probe`** | a blackbox exporter calls a URL, e.g. `/pmtiles-data/readyz` through the Ingress | the maintainers, through Flux | yes | a blackbox exporter run by Bedag; not used |

How rules and mail fit together:

```
PrometheusRule (app namespace)         AlertmanagerConfig (Bedag's tenant)
  expr true for "for:" duration  ──►     route: matchers email="true"
  alert gets labels                      receiver: email → mail relay
    severity, email="true",       ──►
    namespace (from the metric)
```

- A rule only **fires**; an AlertmanagerConfig decides **who gets mail**.
  Both are needed: rules without a route fire silently, a route without rules never
  sends.
- Every rule keeps `namespace` in its result: filter on it, and never
  aggregate it away (`sum by (namespace, …)`, not `sum(…)`). The mail names the
  stage by it, and a route that matches on namespace (the Prometheus
  Operator's default) needs it.
- The route matches `email="true"`. That label is set in the rule, so each
  rule decides whether it sends mail.

Why not Grafana alerting: rules clicked in a UI are not reviewed, not
versioned, and would have to be clicked twice (test and prod). A
`PrometheusRule` in `deploy/stages/base/` goes through the same PR and Flux
chain as the app and is identical on both stages.

---

## 3. What is worth watching

From what went wrong or nearly went wrong so far:

| Failure | Seen / expected | Signal | Metric source |
|---|---|---|---|
| App down (no Ready pod) | no pod of the StatefulSet is Ready (a wrong image tag alone doesn't do it: a rollout stops at the first pod that fails) | StatefulSet has 0 ready pods | kube-state-metrics |
| Pod can't start | `ImagePullBackOff` (tag not built yet), `CrashLoopBackOff`, missing secret, PVC not attaching | container waiting reason | kube-state-metrics |
| Out of memory | a large raster or area IFK; the limit is 8 GiB on test, 16 GiB on prod | `OOMKilled` as last termination reason | kube-state-metrics |
| Memory close to the limit | large rasters: 6.6 GiB of 8 GiB | working set / limit | cAdvisor + kube-state-metrics |
| Restarts | watchdog exits when a server thread dies; liveness probe | restart counter | kube-state-metrics |
| Evicted | an `emptyDir` over its 5Gi `sizeLimit` | pod phase `Failed` (the reason `Evicted` isn't collected) | kube-state-metrics |
| Spill volume full | a raster job at DuckDB's cap (90% of the PVC), or leftovers in `/tmp` | PVC used / capacity | kubelet volume stats |
| Some pods not Ready | a pod that runs but fails its readiness probe: no restart, nothing waiting | StatefulSet has fewer ready pods than desired | kube-state-metrics |
| Proxy container down | nginx is the pod's one entry port; without it the pod serves nothing | waiting reason and restart counter of container `proxy` | kube-state-metrics |
| A copy killed | the s3-toolbox restarts while a bucket copy runs | restart counter of container `toolbox` | kube-state-metrics |
| A metric disappears | Bedag's allowlist changes, or the app's objects are gone: a rule without data never fires | `absent()` on the metrics the rules read | all of the above |
| Deployment stuck | HelmRelease not Ready after a merge | Flux metrics | Flux (if Bedag scrapes it) |
| Users get errors | 5xx on the Ingress | request rate by status | ingress-nginx (if Bedag scrapes it) |

Not visible without work in the app:

- **S3 unreachable or credentials wrong.** `/readyz` doesn't touch S3, and the
  probes must not: a short S3 outage would take every pod out of service at
  once. The app measures it itself, and two rules alert on it (section 9).
- **The app script is broken while the servers are healthy.** Streamlit's health
  passing proves nothing (README, "Running locally"). Only a real session
  (`AppTest`, a browser) catches it.

**What Bedag collects** (checked in Grafana, data source
`aw3-pgr-atlas-test-r8fpkg4c-kb-metrics`):

- kube-state-metrics goes through an **allowlist**. For the app's namespace, over one
  hour: `kube_deployment_{metadata_generation, spec_replicas, status_condition,
  status_observed_generation, status_replicas_available, status_replicas_updated}`,
  `kube_namespace_status_phase`, `kube_persistentvolumeclaim_access_mode`,
  `kube_pod_container_resource_{limits,requests}`,
  `kube_pod_container_status_{ready, restarts_total, running, terminated, waiting}`,
  `kube_pod_{info, owner, status_phase}`, `kube_replicaset_owner`,
  `kube_resourcequota`. It is not Grafana's k8s-monitoring default list.
- `kube_statefulset_replicas` and `kube_statefulset_status_replicas_ready` are
  collected too: the dashboard's *app pods ready* tile divides one by the other.
  `PgrAtlasUnavailable` and `PgrAtlasPodsNotAllReady` depend on them.
- **Missing**, although kube-state-metrics always emits them:
  `kube_pod_status_ready`, `kube_pod_container_info`, `kube_pod_status_reason`.
  The rules and the dashboard avoid them.
- `kube_pod_container_status_waiting_reason` exists only while a container
  waits: **collected**.
- `kube_pod_container_status_last_terminated_reason` exists only after a
  container restarted: **collected** (shown after a deliberate restart on
  test, section 6). `PgrAtlasOOMKilled` and the
  dashboard's *Last termination* depend on it.
- cAdvisor (memory, CPU, throttling, network, with an `image` label), kubelet
  volume stats for the `block` PVC and ingress-nginx (Ingress namespace in
  `exported_namespace`) are there.

---

## 4. The setup

**Alerts in Git, dashboard in Grafana.**

1. **`PrometheusRule` in `deploy/stages/base/monitoring/`**, identical on test
   and prod through `${stage}`. Twelve rules (table below). Unavailable, pod
   stuck and S3 unreachable are `critical`, the rest `warning`. Everything sets `email="true"`.
2. **`AlertmanagerConfig` per stage** in `deploy/applied-by-bedag/<stage>/`
   (applied by Bedag, section 5). Both stages mail the alert mailbox; each can
   get its own recipients there.
3. **One Grafana dashboard**, made by hand, for looking into things. Not for
   alerting. Its source is `monitoring/grafana/pgr-atlas-test.json`: edit the file,
   then paste it into the dashboard's *Edit as code* (section 8).
4. **The app's S3 check**, scraped through a `ServiceMonitor` in
   `deploy/stages/base/monitoring/` (section 9).

The rules:

| Rule | Fires when | Severity |
|---|---|---|
| `PgrAtlasUnavailable` | no ready pod for 10 min | critical |
| `PgrAtlasPodStuck` | the app or proxy container waits (any reason) for 10 min | critical |
| `PgrAtlasOOMKilled` | the app container restarted, last reason `OOMKilled` | warning |
| `PgrAtlasRestarted` | the app or proxy container restarted in the last 15 min | warning |
| `PgrAtlasMemoryHigh` | working set above 90% of the limit for 10 min | warning |
| `PgrAtlasSpillVolumeFull` | spill volume above 85% for 30 min | warning |
| `PgrAtlasPodFailed` | pod phase `Failed` (usually an eviction) | warning |
| `PgrAtlasPodsNotAllReady` | fewer ready pods than desired for 30 min (a rollout stays below that) | warning |
| `PgrAtlasToolboxRestarted` | the s3-toolbox restarted in the last 15 min: a running copy has stopped | warning |
| `PgrAtlasMetricsMissing` | one of four metrics the other rules read has had no series for 30 min; the mail names it | warning |
| `PgrAtlasS3Unreachable` | a pod's own S3 check (section 9) failed or stood still for 5 min | critical |
| `PgrAtlasS3MetricMissing` | no S3 check metric for 30 min | warning |

No rule on the namespace quota (`kube_resourcequota`): the spill volumes take
the whole PVC budget by design, so it would fire all the time.

Settings that differ from Bedag's template, and why:

- **`repeatInterval: 12h`** instead of 20m. Email is not a pager; a 20-minute
  repeat of a known problem gets filtered out within a day.
- **`groupWait: 1m`, `groupInterval: 5m`** instead of 5m/10m, so the first mail
  comes quickly. The rules' `for:` already absorbs short blips.
- **`groupBy: [namespace]`**: an outage usually fires several rules at once
  (unavailable + stuck + restarted). One mail per stage lists them together.
- **Recipients**: a shared mailbox rather than personal addresses. The repo is
  public, and a mailbox survives team changes.

---

## 5. Manifests

Layout. Flux applies what each stage's `kustomization.yaml` lists; Bedag
applies `deploy/applied-by-bedag/` by hand:

```
deploy/stages/base/monitoring/                       Flux
  kustomization.yaml           resources: [prometheusrule.yaml, servicemonitor.yaml]
  prometheusrule.yaml
  servicemonitor.yaml
deploy/stages/<stage>/monitoring/                    Flux
  kustomization.yaml           resources: [../../base/monitoring]
deploy/stages/<stage>/kustomization.yaml   resources: + monitoring
deploy/applied-by-bedag/<stage>/                     Bedag, kubectl apply
  alertmanagerconfig.yaml
```

Why the split: neither Flux's service account nor the project's users may write
AlertmanagerConfigs (`cannot patch resource "alertmanagerconfigs"`), and Flux
applies a stage all or nothing, so one such object in Flux's path blocks every
change to the stage. Bedag applies the AlertmanagerConfigs themselves from the
repo ([README](../deploy/applied-by-bedag/README.md)); Flux never reads that
folder.

**Rules**: [prometheusrule.yaml](../deploy/stages/base/monitoring/prometheusrule.yaml),
the rules described in section 4. `${stage}` is replaced by Flux;
`{{ $labels.x }}` belongs to Prometheus. Checked:

- `flux build kustomization` (Flux 2.9.5, `stage=test`) replaces `${stage}` and
  leaves `{{ $labels.pod }}` and `{{ $value }}` alone.
- `promtool check rules` (Prometheus 3.15) on the rendered rule: valid.
- `kubectl apply --dry-run=server` on test: admitted. The cluster's webhook
  parses PromQL (a rule with a syntax error was rejected), so a broken rule
  can't slip through Flux unnoticed: the Kustomization would turn not-Ready.
- `promtool test rules` with synthetic series: each rule fires after its `for:`,
  not before, and the alert carries `namespace`, `severity` and `email="true"`,
  with the annotations filled in.

**Mail**: [test](../deploy/applied-by-bedag/test/alertmanagerconfig.yaml) and
[prod](../deploy/applied-by-bedag/prod/alertmanagerconfig.yaml), written and
applied by Bedag ([README](../deploy/applied-by-bedag/README.md)):

- It is **Bedag's own type**, `observability.bedag.crossplane.io/v1alpha1`
  `AlertmanagerConfig` in their tenant namespace `bedag-cloud-aw3-pgr`, not the
  Prometheus Operator's `monitoring.coreos.com` one. It carries a
  plain Alertmanager configuration (snake_case keys) for the tenant. The rule
  list in Grafana (rule path `kb-common-test/<namespace>/<name>/<uid>`, Mimir
  logo) suggests Grafana Mimir behind it: one Alertmanager per tenant, not per
  namespace, so the operator's "own namespace only" matcher never applies.
- Routing: the root route discards (receiver `"null"`), a child route mails
  `email="true"` to `alert@skerlak.ch` (every rule sets the label, critical and warning alike). No cluster or namespace matcher: test and
  prod configs differ only in their names. Different recipients per stage would
  need a `k8s_cluster_name` matcher in the child route.
- Relay `mailrelay.svc.kb-bedag.ch:25` and sender `k8s-monitoring@kb-bedag.ch`, as Bedag
  set them.
- Every alert gets `cluster` and `k8s_cluster_name` (`kb-common-<stage>`) from
  Bedag's setup, on top of the metric's labels and the rule's.
- The project's role can't read either object; only Bedag can confirm what is applied.

**Test alert**, to prove mail delivery (e.g. after a recipient change):
`PgrAtlasAlertingTest`, always true
(`kube_deployment_spec_replicas{…, deployment="s3-toolbox"} > 0`, a real metric,
so the alert keeps the `namespace` label). Add it as a kustomize patch in
`deploy/stages/<stage>/monitoring/kustomization.yaml` that adds the rule to the
shared PrometheusRule, not as a PrometheusRule of its own: with Flux's
`prune: false`, a deleted object would stay in the cluster and keep firing,
while removing the patch changes the object and the rule is gone. Its mail comes roughly 15 minutes after the merge,
and removing it sends exactly one "resolved" mail.

---

## 6. Checking the setup

After a change to the rules or the ServiceMonitor:

- `flux get kustomization -n aw3-pgr-atlas-<stage>-apps` is Ready. If not, the
  message names the object the cluster refused.
- `kubectl get prometheusrule pgr-atlas -o yaml` still contains
  `{{ $labels.pod }}` (section 5).
- Grafana, *Alerting → Alert rules* (data-source-managed): group
  `pgr-atlas-<stage>` lists the twelve rules, *Normal*. If the group is
  missing, Prometheus doesn't select the rule.
- If a rule is *Firing* but no mail comes after ~30 minutes, the problem is
  between Alertmanager and the relay, which the maintainers can't see: ask Bedag. One route
  sends one mail and then waits `repeat_interval` (12h).

**Restart test** (test only; the pod is down for ~1 minute, the other pod
keeps serving):

```bash
kubectl --context teleport.ci-bedag.ch-kb-common-test -n aw3-pgr-atlas-test-apps \
  exec pgr-atlas-app-0 -c app -- python -c "import os, signal; os.kill(1, signal.SIGTERM)"
```

PID 1 of the `app` container is `run_app.py`, and Streamlit in that process
stops on SIGTERM; Kubernetes restarts the container in the same pod. Expected:
a `PgrAtlasRestarted` mail, and the dashboard's *Last termination* shows
`Completed` (exit code 0: SIGTERM is a clean shutdown; a crash shows `Error`,
an OOM kill `OOMKilled`).

**Dashboard**: section 8 and
[monitoring/grafana/README.md](../monitoring/grafana/README.md).

---

## 7. What Bedag confirmed

- The mail relay and its settings (section 5).
- Bedag's Prometheus picks up the PrometheusRule and the ServiceMonitor in the
  project's namespaces on both clusters, without an extra label.
- Flux may write `PrometheusRule`s and `ServiceMonitor`s but not
  `AlertmanagerConfig`s, and neither may the project's own role (Teleport,
  groups incl. `alertmanager-editor`), so Bedag applies those (section 5).

Not used, because nothing confirms it is available: rules on Flux (`gotk_*`) or
ingress-nginx metrics, a blackbox exporter for `Probe` objects, logs in Grafana
(Loki), and dashboards deployed from Git.

---

## 8. Grafana dashboard

[monitoring/grafana/](../monitoring/grafana/README.md): one dashboard in two
copies, because Bedag's Grafana only lets the project create dashboards in one folder per
stage: **PGR Atlas (test)** (`pgr-atlas-test.json`, folder
`aw3-pgr-atlas-test-r8fpkg4c`) and **PGR Atlas (prod)** (`pgr-atlas-prod.json`,
folder `aw3-pgr-atlas-prod-mmtqvldq`). The test file is the source: it is edited
in the repo, and `make_prod.py` generates the prod file from it. Each file is
pasted into its dashboard's *Edit → Edit as code* (dashboard format v2; steps in
the README there).
Variables: `datasource` (the `…-kb-metrics` data sources, one per cluster;
each copy opens on its own stage's) and `namespace` (*Stage*, read from the
selected data source: the `aw3-pgr-atlas-*-apps` namespaces with metrics
there). One switch: pick the data source, the stage follows.

| Row | Panels |
|---|---|
| Status | app pods ready (ready pods out of desired, e.g. "2/2": all green, some orange, none red), restarts in range, memory of limit, spill volume used (tiles with the alert thresholds); running image and tag (cAdvisor's `image` label); last termination reason |
| Resources | memory (working set, limit, request), CPU (used, limit, request), CPU throttled |
| Storage and network | spill volume used vs capacity; bytes received (S3 through the proxy) |
| Traffic (ingress-nginx) | requests by Ingress and status (`499` = the browser cancelled a tile request while panning); p95 latency of all requests |
| s3-toolbox (copies), collapsed | toolbox restarts in range (a restart kills running copies), bytes received and sent in range (roughly what a copy moved), copy throughput in/out, memory and CPU against the toolbox's 2 GiB / 2 CPU limits. Its `/work` emptyDir has no usage metric at Bedag |

`container="app"` keeps the s3-toolbox (container `toolbox`) out of every other
row; of the alert rules, only `PgrAtlasToolboxRestarted` looks at it. Limits, requests and capacity are drawn as
dashed grey lines. Every query parses (`promtool`) and returns data on test.

The JSON file is the source: edit it in the repo and paste it into Grafana,
as [monitoring/grafana/README.md](../monitoring/grafana/README.md) describes.

Measured values, to set thresholds by
([deployment-process.md](deployment-process.md#measured-resource-use)): working set ~5 GiB
while a large raster runs (peak 6.6 GiB of 8), CPU 1–2.8 of 4 cores, spill up
to 64.7 GB, ~8 MB/s from S3.

---

## 9. S3 check

The tile server (`app/pmtiles_server.py`) asks S3 for the app's bucket once a
minute with the app's key (`HeadBucket`; an answer later than 15 s counts as a
failure) and reports the last result in two places, without an S3 call per
request:
- `/readyz-s3`: `200 ok` or `503`, for `curl` and people. Through the
  Ingress: `/pmtiles-data/readyz-s3`. No probe uses it.
- `/metrics` (`/pmtiles-data/metrics`), Prometheus text format:
  `pgr_atlas_s3_reachable` (1 or 0) and
  `pgr_atlas_s3_last_check_timestamp_seconds` (stops moving if the check
  itself dies).

**Alerting on both stages** (`deploy/stages/base/monitoring/`):
- `servicemonitor.yaml`: Bedag's Prometheus reads `/pmtiles-data/metrics`
  through the app's Service, one target per pod, every 60 s.
- `PgrAtlasS3Unreachable` (critical): a pod's last check failed, or its check
  has not run for 5 minutes, for 5 minutes.
- `PgrAtlasS3MetricMissing` (warning): no `pgr_atlas_s3_reachable` series for
  30 minutes. Without it the first rule could never fire.

Proven on both stages with two temporary rules: an always-firing
`PgrAtlasAlertingTest` (Flux may write ServiceMonitors) and
`PgrAtlasS3CheckSeen` (`pgr_atlas_s3_reachable == 1`), whose mail listed
every pod: Bedag's Prometheus selects the ServiceMonitor without an extra
label and keeps the metric, and `HeadBucket` works with the read-only key.
Silence from the two real rules alone would only show that nothing failed.
To repeat it (e.g. after a change to the ServiceMonitor), add both rules
again as temporary patches, like the test alert. Rules checked with
`promtool test rules`.
