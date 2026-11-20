# s3tools -- the image of the s3-toolbox pod: s3m (this folder), rclone and the
# AWS CLI, for managing the S3 buckets at Hosttech and Bedag and copying
# between them. See README.md.
#
# Public on ghcr.io like the app image, so it must never contain credentials:
# the keys arrive at runtime as environment variables (S3M_*).
#
# Build: docker build -t pgr-atlas-s3tools:local tools/s3
# CI: .github/workflows/build-s3tools.yml

# Pinned tools, taken from their official images (both multi-arch).
FROM rclone/rclone:1.76.0@sha256:7cbeec24a44f206067597c0368be4de90ae19a64d5113c7d1938bd737a81e466 AS rclone
FROM amazon/aws-cli:2.40.3@sha256:33a16c53ea442e918b58df67301ad76a8fb57082c39f7e78753b898c3f3e87c2 AS awscli

FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# tini as PID 1: copy jobs run detached from the shell that started them, and
# something has to reap them when they end (`sleep` as PID 1 does not).
# apt-get upgrade: Debian's security fixes since the base image was built
# (the image scan in the build workflow fails on a package with a known fix).
# So the OS packages are those of the build day, not only of the digest above.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends tini less \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash --uid 10001 --user-group toolbox \
    && mkdir /work && chown toolbox:toolbox /work

COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone
COPY --from=awscli /usr/local/aws-cli /usr/local/aws-cli
RUN ln -s /usr/local/aws-cli/v2/current/bin/aws /usr/local/bin/aws \
    && rclone version && aws --version

# Python dependencies: exactly this folder's uv.lock, with hashes (as the app image).
COPY --from=ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /tmp/s3tools/
RUN cd /tmp/s3tools \
    && uv export --frozen --no-emit-project -o requirements.lock.txt \
    && uv pip install --system --no-cache -r requirements.lock.txt \
    && rm -rf /tmp/s3tools

COPY --chmod=755 s3m.py /usr/local/bin/s3m

USER 10001
ENV HOME=/home/toolbox \
    S3M_STATE_DIR=/work/.s3m \
    PYTHONUNBUFFERED=1
WORKDIR /work

# Which build this is, set by CI (release tag or <branch>-<short sha>);
# in the pod: echo $S3TOOLS_VERSION
ARG S3TOOLS_VERSION=local
ENV S3TOOLS_VERSION=${S3TOOLS_VERSION}

# Nothing to serve: the pod idles until someone runs `kubectl exec -it … -- bash`.
ENTRYPOINT ["tini", "--"]
CMD ["sleep", "infinity"]
