# proxy -- the image of the app pod's second container: nginx with one config
# file, which gives the pod a single entry port (default.conf, README.md).
#
# Public on ghcr.io like the app image; it holds no credentials and no data.
#
# Build: docker build -t pgr-atlas-proxy:local tools/proxy
# CI: .github/workflows/build-proxy.yml

# nginx's own unprivileged image: runs as UID 101, listens on 8080, keeps its
# pid and temp files under /tmp. From Docker Hub and pinned by digest. nginx
# publishes it as nginx/nginx-unprivileged since 1.30.6 (stable) and 1.31.7
# (mainline); the old name nginxinc/nginx-unprivileged gets no new releases.
# The stable branch (even minor version: 1.30, 1.32, ...), not mainline:
# Dependabot proposes patch releases only, the next stable is a manual step.
FROM nginx/nginx-unprivileged:1.30.7-alpine@sha256:0c53a1f2890c3526bfd201440f0fd3970e5b78f80630f58284aad0d34b5ec7bd

# apk upgrade: Alpine's security fixes since the base image was built (the
# image scans fail on a package with a known fix, and the upstream image is
# rebuilt irregularly). So the OS packages are those of the build day, not
# only of the digest above -- the same rule as apt-get upgrade in the app's
# and the toolbox's Dockerfiles. It does not move nginx itself: the base
# image pins nginx and its modules to nginx.org's build, so an nginx fix
# needs a new base image. Back to nginx's unprivileged user afterwards.
USER root
RUN apk upgrade --no-cache
USER 101
COPY default.conf /etc/nginx/conf.d/default.conf

# Fail the build on a config nginx would refuse to start with.
RUN nginx -t

# Which build this is, set by CI (release tag or <branch>-<short sha>).
ARG PROXY_VERSION=local
ENV PROXY_VERSION=${PROXY_VERSION}
