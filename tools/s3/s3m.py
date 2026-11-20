#!/usr/bin/env python3
"""s3m -- look after the S3 buckets at Hosttech and Bedag, and copy between them.

Made for the s3-toolbox pod on Bedag's cluster: Bedag's S3 endpoint can only be
reached from inside that cluster, Hosttech's through Bedag's egress proxy.
Locally it works for Hosttech and for any other remote you configure.

Paths are written like rclone's:  <remote>:<bucket>/<key or prefix>

    s3m remotes                                  what is configured
    s3m buckets                                  buckets of every remote, with versioning
    s3m ls bedag_admin:aw3-pgr-atlas-test/some/  one level; -r for everything below
    s3m du bedag_admin:aw3-pgr-atlas-test/some/  objects and size of each folder below
    s3m versioning bedag_admin:aw3-pgr-atlas-test on   status without on/off
    s3m versions bedag_admin:aw3-pgr-atlas-test/file.txt
    s3m download bedag_admin:aw3-pgr-atlas-test/file.txt [dest] [--version-id ID]
    s3m delete bedag_admin:aw3-pgr-atlas-test/file.txt [--version-id ID]
    s3m undelete bedag_admin:aw3-pgr-atlas-test/file.txt
    s3m restore bedag_admin:aw3-pgr-atlas-test/file.txt --version-id ID
    s3m copy hosttech:maxi bedag_admin:maxi      dry run: shows what would be copied
    s3m copy hosttech:maxi bedag_admin:maxi --run  copies in the background
    s3m jobs | s3m logs <job> -f | s3m stop <job>
    s3m rclone lsd bedag_admin:                  plain rclone, remotes set up
    s3m aws bedag_admin s3api get-bucket-policy --bucket aw3-pgr-atlas-test

Remotes come from the environment only, so no keys are ever written to disk:

    S3M_REMOTES               which remotes exist (default "hosttech,bedag_admin");
                              names are letters, digits and underscores
    S3M_<NAME>_ENDPOINT       default for hosttech and bedag_admin: see DEFAULTS
    S3M_<NAME>_REGION         default for hosttech and bedag_admin: see DEFAULTS, else us-east-1
    S3M_<NAME>_ACCESS_KEY     the remote's key; no default
    S3M_<NAME>_SECRET_KEY
    S3M_READONLY_REMOTES      remotes s3m refuses to change (default "hosttech", the
                              source of the data; set it to "" to allow changes).
                              The rclone/aws pass-throughs do not check it.
    S3M_STATE_DIR             where copy jobs keep their logs (default ~/.local/state/s3m)
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

DEFAULTS = {
    # Hosttech runs Ceph; every bucket reports LocationConstraint "f712".
    # It accepts any signing region, but a CreateBucket
    # must name its own.
    "hosttech": {"endpoint": "https://f712.gos3.io", "region": "f712"},
    # As in the Secret s3bucket-aw3-pgr-atlas-test-connection-details that
    # Bedag's operator created.
    "bedag_admin": {"endpoint": "https://x7ba-s3-kakbfe.infra.be.ch:10443", "region": "ch-bern-1"},
}


class UsageError(Exception):
    """A mistake in what was asked for; printed without a traceback."""


def _names(var: str, default: str) -> list[str]:
    return [name.strip() for name in os.getenv(var, default).split(",") if name.strip()]


@dataclass
class Remote:
    name: str
    endpoint: str
    region: str
    access_key: str | None
    secret_key: str | None

    @property
    def usable(self) -> bool:
        return bool(self.endpoint and self.access_key and self.secret_key)

    @property
    def readonly(self) -> bool:
        return self.name in _names("S3M_READONLY_REMOTES", "hosttech")

    def need_keys(self):
        if not self.usable:
            prefix = f"S3M_{self.name.upper()}"
            raise UsageError(
                f"remote '{self.name}' is not set up: needs {prefix}_ENDPOINT, "
                f"{prefix}_ACCESS_KEY, {prefix}_SECRET_KEY"
            )

    def need_writable(self):
        if self.readonly:
            raise UsageError(f"remote '{self.name}' is read-only for s3m (S3M_READONLY_REMOTES)")

    def client(self):
        self.need_keys()
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=self.region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(
                # Bedag's network policy allows exactly the endpoint's host name;
                # virtual-host style (<bucket>.<endpoint>) would be blocked.
                s3={"addressing_style": "path"},
                # boto3 >= 1.36 adds CRC checksums to every request by default,
                # which several S3-compatible stores reject.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"mode": "standard", "max_attempts": 5},
            ),
        )


def remotes() -> dict[str, Remote]:
    configured = {}
    for name in _names("S3M_REMOTES", "hosttech,bedag_admin"):
        prefix = f"S3M_{name.upper()}_"
        defaults = DEFAULTS.get(name, {})
        configured[name] = Remote(
            name=name,
            endpoint=os.getenv(prefix + "ENDPOINT", defaults.get("endpoint", "")),
            region=os.getenv(prefix + "REGION", defaults.get("region", "us-east-1")),
            access_key=os.getenv(prefix + "ACCESS_KEY"),
            secret_key=os.getenv(prefix + "SECRET_KEY"),
        )
    return configured


def remote(name: str) -> Remote:
    all_remotes = remotes()
    if name not in all_remotes:
        raise UsageError(f"unknown remote '{name}' (configured: {', '.join(all_remotes)})")
    return all_remotes[name]


@dataclass
class Location:
    remote: Remote
    bucket: str
    key: str  # object key or prefix; "" for the whole bucket

    def need_bucket(self):
        if not self.bucket:
            raise UsageError(f"no bucket given: expected {self.remote.name}:<bucket>[/<key>]")
        return self

    def need_object(self):
        self.need_bucket()
        if not self.key or self.key.endswith("/"):
            raise UsageError(
                f"'{self}' is a prefix, not an object (use -r for everything under it)"
            )
        return self

    def __str__(self):
        return f"{self.remote.name}:{self.bucket}" + (f"/{self.key}" if self.key else "")


def parse(path: str) -> Location:
    name, sep, rest = path.partition(":")
    if not sep:
        raise UsageError(f"'{path}': expected <remote>:<bucket>[/<key>]")
    bucket, _, key = rest.partition("/")
    return Location(remote(name), bucket, key)


def rclone_env() -> dict:
    """The environment for rclone: every usable remote becomes an rclone remote
    of the same name, through RCLONE_CONFIG_* variables instead of a config file."""
    # In-memory config only: no rclone.conf is read or written.
    env = dict(os.environ, RCLONE_CONFIG="/dev/null")
    for configured in remotes().values():
        if not configured.usable:
            continue
        prefix = f"RCLONE_CONFIG_{configured.name.upper()}_"
        env.update(
            {
                prefix + "TYPE": "s3",
                prefix + "PROVIDER": "Other",
                prefix + "ENDPOINT": configured.endpoint,
                prefix + "REGION": configured.region,
                prefix + "ACCESS_KEY_ID": configured.access_key,
                prefix + "SECRET_ACCESS_KEY": configured.secret_key,
                prefix + "FORCE_PATH_STYLE": "true",
            }
        )
    return env


def human(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def confirm(question: str, yes: bool, typed: str | None = None):
    """Ask before changing anything. `typed`: the answer must be this word
    (for the worst cases) instead of y."""
    if yes:
        return
    if not sys.stdin.isatty():
        raise UsageError(
            "this needs a confirmation: run it in a terminal (kubectl exec -it) or add --yes"
        )
    if typed:
        confirmed = input(f"{question}\nType '{typed}' to confirm: ").strip() == typed
    else:
        confirmed = input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    if not confirmed:
        raise UsageError("not confirmed, nothing changed")


def _error_text(error: ClientError) -> str:
    details = error.response.get("Error", {})
    return f"{details.get('Code', '?')}: {details.get('Message', str(error))}"


def _versioning(client, bucket: str) -> str:
    try:
        return client.get_bucket_versioning(Bucket=bucket).get("Status", "never enabled")
    except ClientError as error:
        return f"? ({_error_text(error)})"


# --- inspecting -------------------------------------------------------------


def cmd_remotes(args):
    # REGION is the name requests are signed with (the store's own region name),
    # not where the data is: that is decided by the endpoint.
    print(f"{'REMOTE':12} {'ENDPOINT':45} {'REGION':12} KEYS")
    for configured in remotes().values():
        keys = "keys set" if configured.usable else "not set up"
        # s3m's own guard, not the key's rights: a guarded remote's key may
        # well be able to write (every Hosttech key can).
        guard = ", s3m won't write" if configured.readonly else ""
        print(
            f"{configured.name:12} {configured.endpoint or '-':45} {configured.region:12} "
            f"{keys}{guard}"
        )
    if any(configured.readonly for configured in remotes().values()):
        print(
            '\n"s3m won\'t write": s3m refuses to change that remote (S3M_READONLY_REMOTES). '
            "It says nothing\nabout the key, which may be able to write and delete; "
            "`s3m rclone` and `s3m aws` don't check it."
        )


def cmd_buckets(args):
    names = args.remotes or [name for name, each in remotes().items() if each.usable]
    if not names:
        raise UsageError("no remote has keys; see `s3m remotes`")
    for name in names:
        target = remote(name)
        client = target.client()
        print(f"{name} ({target.endpoint})")
        try:
            buckets = client.list_buckets()["Buckets"]
        except ClientError as error:
            # Bedag's per-bucket keys may not list buckets; the tenant admin key may.
            print(f"  cannot list buckets with this key: {_error_text(error)}")
            continue
        for bucket in buckets:
            versioning = _versioning(client, bucket["Name"])
            print(
                f"  {bucket['Name']:40} created {bucket['CreationDate']:%Y-%m-%d}  "
                f"versioning: {versioning}"
            )
        if not buckets:
            print("  (no buckets)")


def cmd_ls(args):
    loc = parse(args.path).need_bucket()
    client = loc.remote.client()
    list_args = {"Bucket": loc.bucket, "Prefix": loc.key}
    if not args.recursive:
        list_args["Delimiter"] = "/"
    count = size = 0
    for page in client.get_paginator("list_objects_v2").paginate(**list_args):
        for folder in page.get("CommonPrefixes", []):
            print(f"{'DIR':>10}  {'':16}  {folder['Prefix']}")
        for item in page.get("Contents", []):
            count += 1
            size += item["Size"]
            print(
                f"{human(item['Size']):>10}  {item['LastModified']:%Y-%m-%d %H:%M}  {item['Key']}"
            )
    print(
        f"{count} objects, {human(size)}"
        + ("" if args.recursive else " (this level only; -r for all)")
    )


def cmd_du(args):
    loc = parse(args.path).need_bucket()
    client = loc.remote.client()
    here = "(objects at this level)"
    folders: dict[str, list[int]] = {}  # folder -> [objects, bytes]
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=loc.bucket, Prefix=loc.key):
        for item in page.get("Contents", []):
            # Group by the next path component after the prefix, like `ls` shows it.
            head, slash, _ = item["Key"][len(loc.key) :].partition("/")
            row = folders.setdefault(f"{loc.key}{head}/" if slash else here, [0, 0])
            row[0] += 1
            row[1] += item["Size"]
    at_level = folders.pop(here, None)
    for name, (count, size) in sorted(folders.items()):
        print(f"{count:>10}  {human(size):>10}  {name}")
    if at_level:
        print(f"{at_level[0]:>10}  {human(at_level[1]):>10}  {here}")
    count = sum(row[0] for row in folders.values()) + (at_level[0] if at_level else 0)
    size = sum(row[1] for row in folders.values()) + (at_level[1] if at_level else 0)
    print(f"{count} objects, {human(size)} under {loc} (current versions only)")


def cmd_versions(args):
    loc = parse(args.path).need_bucket()
    client = loc.remote.client()
    rows = []
    for page in client.get_paginator("list_object_versions").paginate(
        Bucket=loc.bucket, Prefix=loc.key
    ):
        for version in page.get("Versions", []):
            rows.append(
                (
                    version["Key"],
                    version["LastModified"],
                    version["IsLatest"],
                    human(version["Size"]),
                    version["VersionId"],
                )
            )
        for marker in page.get("DeleteMarkers", []):
            rows.append(
                (
                    marker["Key"],
                    marker["LastModified"],
                    marker["IsLatest"],
                    "delete marker",
                    marker["VersionId"],
                )
            )
    # By key, newest first.
    rows.sort(key=lambda row: (row[0], -row[1].timestamp()))
    for key, modified, latest, what, version_id in rows:
        print(
            f"{'*' if latest else ' '} {modified:%Y-%m-%d %H:%M:%S}  {what:>13}  {version_id:34}  {key}"
        )
    print(f"{len(rows)} versions (* = current). An unversioned object shows version 'null'.")


def cmd_download(args):
    loc = parse(args.path).need_bucket()
    if args.recursive:
        if args.version_id:
            raise UsageError("--version-id works for a single object only")
        sys.exit(
            subprocess.call(
                ["rclone", "copy", str(loc), args.dest or ".", "--progress"], env=rclone_env()
            )
        )
    loc.need_object()
    dest = Path(args.dest or ".")
    if dest.is_dir():
        dest = dest / Path(loc.key).name
    extra = {"VersionId": args.version_id} if args.version_id else None
    loc.remote.client().download_file(loc.bucket, loc.key, str(dest), ExtraArgs=extra)
    version = f" (version {args.version_id})" if args.version_id else ""
    print(f"{loc}{version} -> {dest} ({human(dest.stat().st_size)})")


# --- changing ---------------------------------------------------------------


def cmd_versioning(args):
    loc = parse(args.path).need_bucket()
    client = loc.remote.client()
    if args.state:
        loc.remote.need_writable()
        status, note = {
            "on": (
                "Enabled",
                "Once enabled, a bucket can never go back to unversioned, only to Suspended.",
            ),
            "off": (
                "Suspended",
                (
                    "Existing versions stay; new writes then replace the 'null' version "
                    "instead of adding versions."
                ),
            ),
        }[args.state]
        confirm(f"Set versioning of {loc.remote.name}:{loc.bucket} to {status}? {note}", args.yes)
        client.put_bucket_versioning(Bucket=loc.bucket, VersioningConfiguration={"Status": status})
    print(f"{loc.remote.name}:{loc.bucket} versioning: {_versioning(client, loc.bucket)}")


def cmd_delete(args):
    loc = parse(args.path).need_bucket()
    loc.remote.need_writable()
    client = loc.remote.client()

    if not args.recursive:
        loc.need_object()
        if args.all_versions:
            raise UsageError("--all-versions goes with -r; for one version use --version-id")
        if args.version_id:
            confirm(f"PERMANENTLY delete version {args.version_id} of {loc}?", args.yes)
            client.delete_object(Bucket=loc.bucket, Key=loc.key, VersionId=args.version_id)
            print(f"deleted version {args.version_id} of {loc} for good")
            return
        confirm(f"Delete {loc}?", args.yes)
        response = client.delete_object(Bucket=loc.bucket, Key=loc.key)
        if response.get("DeleteMarker"):
            print(
                f"delete marker {response['VersionId']} added, older versions are kept; "
                f"`s3m undelete {loc}` brings it back"
            )
        else:
            print(f"deleted {loc} (the bucket is not versioned: it is gone for good)")
        return

    if args.version_id:
        raise UsageError("--version-id works for a single object only")
    targets, size = [], 0
    if args.all_versions:
        for page in client.get_paginator("list_object_versions").paginate(
            Bucket=loc.bucket, Prefix=loc.key
        ):
            for version in page.get("Versions", []) + page.get("DeleteMarkers", []):
                targets.append({"Key": version["Key"], "VersionId": version["VersionId"]})
                size += version.get("Size", 0)
        question = f"PERMANENTLY delete {len(targets)} versions and delete markers ({human(size)}) under {loc}?"
    else:
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=loc.bucket, Prefix=loc.key
        ):
            for item in page.get("Contents", []):
                targets.append({"Key": item["Key"]})
                size += item["Size"]
        question = f"Delete {len(targets)} objects ({human(size)}) under {loc}? In a versioned bucket this adds delete markers."
    if not targets:
        print(f"nothing under {loc}")
        return
    # The whole bucket, or anything permanent: the bucket's name has to be typed.
    confirm(question, args.yes, typed=loc.bucket if (args.all_versions or not loc.key) else None)
    _delete_many(client, loc.bucket, targets)
    print(f"deleted {len(targets)} entries under {loc}")


# The most keys one DeleteObjects request takes (an S3 limit).
_DELETE_BATCH_SIZE = 1000


def _delete_many(client, bucket: str, targets: list[dict]):
    """DeleteObjects in batches of 1000. Some S3-compatible stores want a
    Content-MD5 on it that current boto3 no longer sends; fall back to one
    request per object then."""
    batched = True
    for start in range(0, len(targets), _DELETE_BATCH_SIZE):
        batch = targets[start : start + _DELETE_BATCH_SIZE]
        if batched:
            try:
                response = client.delete_objects(
                    Bucket=bucket, Delete={"Objects": batch, "Quiet": True}
                )
                for failure in response.get("Errors", []):
                    print(
                        f"  failed: {failure['Key']} {failure.get('VersionId', '')}: "
                        f"{failure.get('Code')} {failure.get('Message')}"
                    )
                continue
            except ClientError as error:
                print(f"  DeleteObjects not accepted ({_error_text(error)}), deleting one by one")
                batched = False
        for target in batch:
            client.delete_object(Bucket=bucket, **target)


def cmd_undelete(args):
    loc = parse(args.path).need_object()
    loc.remote.need_writable()
    client = loc.remote.client()
    removed = []
    # A key deleted twice has two delete markers on top; remove them all.
    while True:
        listing = client.list_object_versions(Bucket=loc.bucket, Prefix=loc.key, MaxKeys=50)
        marker = next(
            (
                each
                for each in listing.get("DeleteMarkers", [])
                if each["Key"] == loc.key and each["IsLatest"]
            ),
            None,
        )
        if not marker:
            break
        client.delete_object(Bucket=loc.bucket, Key=loc.key, VersionId=marker["VersionId"])
        removed.append(marker["VersionId"])
    if not removed:
        print(f"{loc} is not deleted (its current version is not a delete marker)")
        return
    try:
        current = client.head_object(Bucket=loc.bucket, Key=loc.key)["VersionId"]
        print(
            f"undeleted {loc}: removed delete marker(s) {', '.join(removed)}; current version {current}"
        )
    except ClientError:
        print(
            f"removed delete marker(s) {', '.join(removed)}, but {loc} has no older version to come back"
        )


def cmd_restore(args):
    loc = parse(args.path).need_object()
    loc.remote.need_writable()
    client = loc.remote.client()
    confirm(
        f"Make version {args.version_id} the current version of {loc}? "
        "It is copied on top as a new version; nothing is deleted.",
        args.yes,
    )
    # client.copy (not copy_object): uses multipart copy above 5 GB.
    client.copy(
        {"Bucket": loc.bucket, "Key": loc.key, "VersionId": args.version_id}, loc.bucket, loc.key
    )
    current = client.head_object(Bucket=loc.bucket, Key=loc.key).get("VersionId", "null")
    print(f"restored {loc}: new current version {current}, a copy of {args.version_id}")


# --- copying ----------------------------------------------------------------


def jobs_dir() -> Path:
    return Path(os.getenv("S3M_STATE_DIR", Path.home() / ".local/state/s3m")) / "jobs"


def cmd_copy(args):
    src, dst = parse(args.src).need_bucket(), parse(args.dst).need_bucket()
    src.remote.need_keys()
    dst.remote.need_keys()
    dst.remote.need_writable()
    # `copy`, never `sync`: sync would delete what exists only at the target.
    # rclone skips files that are already there with the same size and
    # modification time, so running a copy again only copies what is missing.
    cmd = [
        "rclone",
        "copy",
        str(src),
        str(dst),
        # A missing target bucket is an error, not something to create on
        # the way: buckets are created on purpose (S3Bucket in Git).
        "--s3-no-check-bucket",
        # rclone holds a folder's listing in memory up to this many entries
        # (its default is 1,000,000, about 1 GB) and sorts larger ones on
        # disk. With a million-object folder on both sides (maxi's
        # Data-Lake-Silver/, locks/) the default takes more than the
        # toolbox's 2Gi and the container is OOM-killed.
        "--list-cutoff",
        "100000",
        "--transfers",
        str(args.transfers),
        "--checkers",
        str(2 * args.transfers),
        "--stats",
        "30s",
        "--stats-one-line",
        "--stats-log-level",
        "NOTICE",
        "-v",
        *args.rclone_args,
    ]
    if not args.run:
        print(f"dry run, nothing is copied (add --run to copy): {' '.join(cmd)}", flush=True)
        sys.exit(subprocess.call(cmd + ["--dry-run"], env=rclone_env()))
    if args.foreground:
        sys.exit(subprocess.call(cmd, env=rclone_env()))

    job_id = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    job = jobs_dir() / job_id
    job.mkdir(parents=True)
    (job / "job.json").write_text(
        json.dumps(
            {"id": job_id, "src": str(src), "dst": str(dst), "cmd": cmd, "started": _now()},
            indent=2,
        )
    )
    # A runner in its own session: it outlives this shell and the kubectl exec
    # connection, waits for rclone and records its exit code.
    runner = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_run-job", str(job)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    (job / "pid").write_text(str(runner.pid))
    print(f"started job {job_id}: {src} -> {dst}")
    print(f"  s3m logs {job_id} -f     s3m jobs     s3m stop {job_id}")


def cmd_run_job(args):
    """The background runner started by `copy --run` (hidden subcommand)."""
    job = Path(args.job_dir)
    cmd = json.loads((job / "job.json").read_text())["cmd"]
    with open(job / "job.log", "ab", buffering=0) as log:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=rclone_env()
        )
        signal.signal(signal.SIGTERM, lambda *_: proc.terminate())
        code = proc.wait()
    (job / "exit").write_text(json.dumps({"code": code, "finished": _now()}))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # In the pod: after a container restart the PID may belong to something else.
    cmdline = Path(f"/proc/{pid}/cmdline")
    if cmdline.parent.exists():
        try:
            return b"_run-job" in cmdline.read_bytes()
        except OSError:
            return False
    return True


def _job_status(job: Path) -> str:
    if (job / "exit").exists():
        code = json.loads((job / "exit").read_text())["code"]
        return {0: "done", -signal.SIGTERM: "stopped"}.get(code, f"failed (exit {code})")
    pid_file = job / "pid"
    if pid_file.exists() and _alive(int(pid_file.read_text())):
        return "running"
    return "died (pod restarted?)"


def _find_job(job_id: str) -> Path:
    job = jobs_dir() / job_id
    if not (job / "job.json").exists():
        raise UsageError(f"no job '{job_id}'; see `s3m jobs`")
    return job


def _last_progress(job: Path) -> str:
    log = job / "job.log"
    if not log.exists():
        return ""
    with open(log, "rb") as log_file:
        # The last 16 KiB hold the latest stats lines.
        log_file.seek(max(0, log.stat().st_size - 16384))
        lines = log_file.read().decode(errors="replace").splitlines()
    for line in reversed(lines):
        if "ETA" in line or "Transferred" in line:
            return line.strip()
    return lines[-1].strip() if lines else ""


def cmd_jobs(args):
    jobs = sorted(jobs_dir().glob("*/job.json")) if jobs_dir().exists() else []
    if not jobs:
        print("no copy jobs yet")
        return
    for meta_file in jobs:
        job = meta_file.parent
        meta = json.loads(meta_file.read_text())
        print(f"{meta['id']}  {_job_status(job):22} {meta['src']} -> {meta['dst']}")
        progress = _last_progress(job)
        if progress:
            print(f"    {progress}")


def cmd_logs(args):
    job = _find_job(args.job)
    log = job / "job.log"
    while not log.exists() and _job_status(job) == "running":
        time.sleep(1)
    if not log.exists():
        print("(no log)")
        return
    with open(log, "rb") as log_file:
        lines = log_file.read().decode(errors="replace").splitlines()
        print("\n".join(lines[-args.lines :]))
        if not args.follow:
            return
        try:
            while True:
                chunk = log_file.read()
                if chunk:
                    sys.stdout.write(chunk.decode(errors="replace"))
                    sys.stdout.flush()
                elif _job_status(job) != "running":
                    break
                else:
                    time.sleep(2)
        except KeyboardInterrupt:
            return  # stop following; the job keeps running
    print(f"-- job {args.job}: {_job_status(job)}")


def cmd_stop(args):
    job = _find_job(args.job)
    if _job_status(job) != "running":
        print(f"job {args.job} is not running ({_job_status(job)})")
        return
    os.kill(int((job / "pid").read_text()), signal.SIGTERM)
    print(f"stopping job {args.job}; running the same copy again continues where it stopped")


# --- pass-throughs ----------------------------------------------------------


def run_rclone(argv: list[str]):
    os.execvpe("rclone", ["rclone", *argv], rclone_env())


def run_aws(argv: list[str]):
    if not argv:
        raise UsageError("usage: s3m aws <remote> <aws arguments...>")
    target = remote(argv[0])
    target.need_keys()
    # Path-style addressing (see Remote.client) can only be set in a config file.
    config = jobs_dir().parent / "aws-config"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[default]\ns3 =\n    addressing_style = path\n")
    env = dict(
        os.environ,
        AWS_ACCESS_KEY_ID=target.access_key,
        AWS_SECRET_ACCESS_KEY=target.secret_key,
        AWS_ENDPOINT_URL=target.endpoint,
        AWS_DEFAULT_REGION=target.region,
        AWS_CONFIG_FILE=str(config),
        AWS_REQUEST_CHECKSUM_CALCULATION="when_required",
        AWS_RESPONSE_CHECKSUM_VALIDATION="when_required",
    )
    env.pop("AWS_PROFILE", None)
    os.execvpe("aws", ["aws", *argv[1:]], env)


# --- command line -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="s3m",
        description=__doc__.split("\n\n")[0],
        epilog="Pass-throughs: `s3m rclone <args>` and `s3m aws <remote> <args>` run the plain "
        "tools with the remotes set up. See the module docstring for the environment.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    def add(name, func, help_text):
        sp = sub.add_parser(name, help=help_text, description=help_text)
        sp.set_defaults(func=func)
        return sp

    def yes(sp):
        sp.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    add("remotes", cmd_remotes, "show the configured remotes")

    sp = add("buckets", cmd_buckets, "list buckets and their versioning status")
    sp.add_argument("remotes", nargs="*", help="remotes to ask (default: all with keys)")

    sp = add("ls", cmd_ls, "list objects")
    sp.add_argument("path", help="remote:bucket[/prefix]")
    sp.add_argument(
        "-r", "--recursive", action="store_true", help="everything below, not just one level"
    )

    sp = add("du", cmd_du, "count the objects and add up the sizes, per folder one level down")
    sp.add_argument("path", help="remote:bucket[/prefix]")

    sp = add("versioning", cmd_versioning, "show, or switch on/off, a bucket's versioning")
    sp.add_argument("path", help="remote:bucket")
    sp.add_argument("state", nargs="?", choices=["on", "off"], help="off = Suspended")
    yes(sp)

    sp = add("versions", cmd_versions, "list all versions and delete markers")
    sp.add_argument("path", help="remote:bucket[/key or prefix]")

    sp = add("download", cmd_download, "download an object (or, with -r, a prefix)")
    sp.add_argument("path", help="remote:bucket/key")
    sp.add_argument("dest", nargs="?", help="file or directory (default: current directory)")
    sp.add_argument("--version-id", help="download this version instead of the current one")
    sp.add_argument(
        "-r", "--recursive", action="store_true", help="everything under the prefix (uses rclone)"
    )

    sp = add("delete", cmd_delete, "delete an object, one version of it, or (with -r) a prefix")
    sp.add_argument("path", help="remote:bucket/key or, with -r, remote:bucket[/prefix]")
    sp.add_argument("--version-id", help="permanently delete this one version")
    sp.add_argument("-r", "--recursive", action="store_true", help="everything under the prefix")
    sp.add_argument(
        "--all-versions",
        action="store_true",
        help="with -r: permanently delete every version and delete marker, not just the current objects",
    )
    yes(sp)

    sp = add("undelete", cmd_undelete, "bring back a deleted object (removes its delete marker)")
    sp.add_argument("path", help="remote:bucket/key")

    sp = add("restore", cmd_restore, "make an older version the current one")
    sp.add_argument("path", help="remote:bucket/key")
    sp.add_argument(
        "--version-id", required=True, help="the version to bring back (see `s3m versions`)"
    )
    yes(sp)

    sp = add(
        "copy", cmd_copy, "copy with rclone (dry run unless --run); arguments after -- go to rclone"
    )
    sp.add_argument("src", help="remote:bucket[/prefix]")
    sp.add_argument("dst", help="remote:bucket[/prefix]")
    sp.add_argument("--run", action="store_true", help="really copy, in the background")
    sp.add_argument("--foreground", action="store_true", help="with --run: stay attached instead")
    sp.add_argument(
        "--transfers", type=int, default=16, help="parallel file transfers (default 16)"
    )
    sp.add_argument(
        "rclone_args", nargs="*", help="extra rclone flags, after --, e.g. -- --exclude '*.tmp'"
    )

    add("jobs", cmd_jobs, "list copy jobs")

    sp = add("logs", cmd_logs, "show a copy job's log")
    sp.add_argument("job")
    sp.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="keep printing until the job ends (Ctrl-C only stops watching)",
    )
    sp.add_argument("-n", "--lines", type=int, default=40, help="lines to show (default 40)")

    sp = add("stop", cmd_stop, "stop a running copy job")
    sp.add_argument("job")

    sp = sub.add_parser("_run-job")  # internal, see cmd_copy
    sp.add_argument("job_dir")
    sp.set_defaults(func=cmd_run_job)
    return p


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        # Handled before argparse so every argument, flags included, is passed on as-is.
        if argv[:1] == ["rclone"]:
            return run_rclone(argv[1:])
        if argv[:1] == ["aws"]:
            return run_aws(argv[1:])
        args = build_parser().parse_args(argv)
        args.func(args)
    except UsageError as e:
        sys.exit(f"s3m: {e}")
    except ClientError as e:
        sys.exit(f"s3m: {_error_text(e)}")
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        # Output piped into `head` & co., which stopped reading: end quietly
        # (and keep Python from complaining again when it flushes stdout).
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)


if __name__ == "__main__":
    main()
