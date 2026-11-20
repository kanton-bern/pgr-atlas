# s3tools: managing the S3 buckets at Hosttech and Bedag

`s3m` lists buckets, switches versioning, downloads, deletes, restores old
versions and copies buckets from Hosttech to Bedag. The image
`ghcr.io/skerlakanalytics/pgr-atlas-s3tools` bundles it with **rclone** (does
the copying) and the **AWS CLI**.

It is made for a toolbox pod on Bedag's cluster. **Bedag's S3 endpoint
(`x7ba-s3-kakbfe.infra.be.ch:10443`) can only be reached from inside that
cluster**. Hosttech is reachable from anywhere, and from Bedag's cluster through
its egress proxy, which allows every `*.f712.gos3.io` host.

| File | What |
|---|---|
| `s3m.py` | the CLI, one file; installed as `/usr/local/bin/s3m` |
| `Dockerfile` | Python 3.12 slim + boto3 + rclone 1.76.0 + AWS CLI 2.39.2, UID 10001, `tini` as PID 1 |
| `../../.github/workflows/build-s3tools.yml` | builds and pushes the image |
| `../../deploy/stages/test/s3-toolbox/` | the toolbox pod on Bedag test and its egress policy |
| `../../deploy/stages/prod/s3-toolbox/` | the same on Bedag prod, with prod's S3 tenant keypair |

## On Bedag test

The pod `s3-toolbox` in `aw3-pgr-atlas-test-apps` idles until you open a shell
in it (Teleport session, `KUBECONFIG=~/.kube/bedag.yaml`):

```bash
kubectl -n aw3-pgr-atlas-test-apps exec -it deploy/s3-toolbox -- bash
s3m buckets
```

What it runs with (`deploy/stages/test/s3-toolbox/deployment.yaml`):
- **Bedag key:** the S3 tenant's admin keypair
  (`aw3-pgr-atlas-s3-test-s3-admin-keypair`, created by Bedag's operator). It
  sees every bucket in the tenant, may switch versioning, and may also delete
  anything.
- **Hosttech key:** the toolbox's own Secret `s3-toolbox-hosttech`
  (`hosttech-key-secret.yaml` next to the deployment, SOPS-encrypted). The key
  is the toolbox's alone: the key `pgr-atlas-s3m-toolbox` in Hosttech's UI, one
  key for test and prod. No other place uses it, so it can be withdrawn on its
  own. Like every Hosttech key it has full access to
  every bucket (`docs/s3.md` §6), so the toolbox can copy e.g. `maxi` with it.
  To change the key, write the Secret again in plaintext, run
  `sops --encrypt --in-place` on it from the repo root, **and bump** the
  `pgr-atlas/hosttech-key-rotated` annotation in `deployment.yaml`. The pod reads the key only when it starts, so a changed
  Secret alone leaves the old key in use.
- **Egress:** the policy `allow-egress-s3-toolbox` allows Bedag's S3. Hosttech
  goes through Bedag's proxy.
- **Resources:** 250m CPU / 512Mi requested, up to 2 CPU / 2Gi for copies.
  `/work` (downloads, job logs) is scratch space of up to 20Gi that is emptied
  whenever the pod restarts.

A pod restart kills running copies. Merging a change to `deployment.yaml`
restarts it, so run `s3m jobs` first; a change to the other files doesn't.
To get a downloaded file onto your machine:
`kubectl -n aw3-pgr-atlas-test-apps cp <pod>:/work/<file> ./<file>`.

## On Bedag prod

The same pod in `aw3-pgr-atlas-prod-apps` on `kb-common-prod`
(`deploy/stages/prod/s3-toolbox/`), with the prod S3 tenant's admin keypair
(`aw3-pgr-atlas-s3-prod-s3-admin-keypair`; tenant and bucket are in
`deploy/stages/prod/pgr-atlas/s3/`) and its own Hosttech key Secret, as on test. Keep the two deployments in step.

```bash
kubectl --context teleport.ci-bedag.ch-kb-common-prod -n aw3-pgr-atlas-prod-apps \
  exec -it deploy/s3-toolbox -- bash
```

## Commands

Paths look like rclone's: `<remote>:<bucket>/<key or prefix>`.

```
s3m remotes                                  what is configured (keys are never shown)
s3m buckets [remote…]                        buckets and their versioning status
s3m ls bedag_admin:aw3-pgr-atlas-test/some/  one level; -r for everything below
s3m du bedag_admin:aw3-pgr-atlas-test/some/  objects and size of each folder below
s3m versioning bedag_admin:aw3-pgr-atlas-test  status; add "on" or "off" to switch
s3m versions bedag_admin:aw3-pgr-atlas-test/f.txt  every version and delete marker
s3m download bedag_admin:aw3-pgr-atlas-test/f.txt [dest] [--version-id ID]   (-r: a prefix)
s3m delete   bedag_admin:aw3-pgr-atlas-test/f.txt [--version-id ID]    (-r: a prefix)
s3m undelete bedag_admin:aw3-pgr-atlas-test/f.txt  removes the delete marker
s3m restore  bedag_admin:aw3-pgr-atlas-test/f.txt --version-id ID      old version on top
s3m copy hosttech:maxi bedag_admin:maxi      dry run
s3m copy hosttech:maxi bedag_admin:maxi --run  copies in the background
s3m jobs | s3m logs <job> [-f] | s3m stop <job>
s3m rclone <args>                            plain rclone, every configured remote set up
s3m aws <remote> <args>                      plain AWS CLI against that remote
```

`s3m <command> -h` explains the options.

**Safety:**
- Anything that changes a bucket asks first. Deleting a whole bucket's content,
  or anything permanent under a prefix, asks you to type the bucket name. `-y`
  skips the question.
- s3m **won't write** to Hosttech (`S3M_READONLY_REMOTES`, default
  `hosttech`), and `s3m remotes` shows such a remote as "s3m won't write".
  That is s3m's own guard, not a limit of the key: every Hosttech key can
  write and delete, and the rclone/aws pass-throughs don't check the guard.
- `copy` is `rclone copy`, never `sync`: nothing at the target gets deleted.
  It never creates a missing target bucket (`--s3-no-check-bucket`); buckets
  are created on purpose, as `S3Bucket` in Git.
- `copy` passes `--list-cutoff 100000` to rclone: a folder with more entries
  than that is listed to disk and sorted there instead of in memory. rclone's
  default of 1,000,000 took more than 2Gi for `maxi`, which has flat folders
  with over a million objects on both sides. Another value after `--` wins.
- `copy` copies only the **current** version of each object. Hosttech's `maxi`
  has versioning on; its older versions stay behind.

**Versioning, in S3 terms:**
- "off" means *Suspended*. Once enabled, a bucket can never be unversioned
  again.
- A plain `delete` in a versioned bucket only adds a delete marker; `undelete`
  removes it again.
- `restore` copies an old version on top as a new version, so nothing is lost.
- Bedag's `S3Bucket` resource has no versioning field (checked with
  `kubectl explain`), so versioning is switched through the S3 API,
  i.e. with s3m. Its `lifecycleManagement.expirationInDays` deletes *current*
  objects after N days; don't use it for data.

## Copy jobs

`copy --run` starts rclone in the background and returns. The job keeps running
when you close the shell or the `kubectl exec` session. It stops only if the pod
restarts; then run the same command again. rclone skips every file that is
already there with the same size and modification time, so a repeated copy only
copies what is missing.

```
s3m copy hosttech:maxi bedag_admin:maxi             # 1. dry run: what would be copied
s3m copy hosttech:maxi bedag_admin:maxi --run       # 2. copy
s3m jobs                                             #    status + latest progress line
s3m logs 20260927-133553 -f                          #    follow (Ctrl-C stops watching only)
s3m rclone check hosttech:maxi bedag_admin:maxi --one-way --size-only   # 3. verify
```

Anything after `--` goes to rclone, e.g. `-- --include "Data-Lake-Gold/**"` or
`-- --bwlimit 50M`. `--transfers` (default 16) sets how many files are copied
in parallel; rclone compares twice as many at a time. Many small files copy
faster with more, large files need more memory per transfer. Job logs live in `$S3M_STATE_DIR/jobs/<id>/`.

## Configuration

Only environment variables; s3m writes no keys to disk, and rclone runs without
a config file.

| Variable | Default |
|---|---|
| `S3M_REMOTES` | `hosttech,bedag_admin` |
| `S3M_<NAME>_ENDPOINT` | hosttech `https://f712.gos3.io`, bedag_admin `https://x7ba-s3-kakbfe.infra.be.ch:10443` |
| `S3M_<NAME>_REGION` | hosttech `f712`, bedag_admin `ch-bern-1`: the store's own region name, used for signing. Where the data lives is decided by the endpoint |
| `S3M_<NAME>_ACCESS_KEY` / `_SECRET_KEY` | none |
| `S3M_READONLY_REMOTES` | `hosttech` |
| `S3M_STATE_DIR` | `~/.local/state/s3m` (image: `/work/.s3m`) |

Any number of remotes works: `S3M_REMOTES=hosttech,test` plus `S3M_TEST_*`.

Settings that matter for Bedag, set by s3m for boto3, rclone and the AWS CLI:
path-style addressing (Bedag's network policy allows exactly the endpoint's host
name, not `<bucket>.<host>`), and checksums only where required (current AWS SDKs
add checksums that several S3-compatible stores reject). Bedag's certificate is
from SwissSign, a public CA, so no extra CA is needed.

## Running it locally

For Hosttech only (Bedag isn't reachable from outside the cluster):

```bash
docker build -t pgr-atlas-s3tools:local tools/s3
set -a; source .env; set +a          # the repo's .env with the PROBE_S3_* keys
docker run --rm -it -e S3M_HOSTTECH_ACCESS_KEY="$PROBE_S3_ACCESS_KEY_ID" \
  -e S3M_HOSTTECH_SECRET_KEY="$PROBE_S3_SECRET_ACCESS_KEY" -e S3M_REMOTES=hosttech \
  pgr-atlas-s3tools:local bash
```

To try the commands that change things without touching real buckets, run a
local S3 server (RustFS; the MinIO image is not published) and add
it as a remote:

```bash
docker network create s3m-test
docker run -d --name s3-local --network s3m-test \
  -e RUSTFS_ACCESS_KEY=testkey -e RUSTFS_SECRET_KEY=testsecret123 rustfs/rustfs:latest
docker run --rm -it --network s3m-test -e S3M_REMOTES=local \
  -e S3M_LOCAL_ENDPOINT=http://s3-local:9000 -e S3M_LOCAL_ACCESS_KEY=testkey \
  -e S3M_LOCAL_SECRET_KEY=testsecret123 pgr-atlas-s3tools:local bash
# inside: s3m rclone mkdir local:test; s3m versioning local:test on; ...
```

## Releasing

```bash
git switch main && git pull
git tag -a s3tools-v0.1.0 -m "short description"
git push origin s3tools-v0.1.0      # CI builds :v0.1.0 and :latest
```

Then set the new version in `deploy/stages/{test,prod}/s3-toolbox/deployment.yaml`
(`image:`), open a PR and merge it; Flux restarts the pod with it.

The package `pgr-atlas-s3tools` is public, so
Bedag's mirror (`artifacts.bedag.cloud/ghcr/…`) can serve it like the app image.
Like the app image, it must never contain credentials.
