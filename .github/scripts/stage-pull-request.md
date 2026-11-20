## What

Sets the ${STAGE} stage's image to `${TAG}`.

## Why

`${TAG}` is released and its image is pushed. A stage runs it only once its `image.tag` says so.

## Changes

- `deploy/stages/${STAGE}/pgr-atlas/values.yaml`: `image.tag` `${PREVIOUS}` to `${TAG}`

## Risk and rollout

- **Rollout:** merge only when the "E2E" and "AppTest" runs of tag `${TAG}` are green. Test first: merge prod's pull request after the test stage is checked on `${TAG}`. Flux applies a merge within about ten minutes.
- **Rollout:** what `${TAG}` carries: https://github.com/${GITHUB_REPOSITORY}/compare/${PREVIOUS}...${TAG}
- **Rollback:** set the tag back to `${PREVIOUS}` and merge.

Opened by the "Build and push" run of `${TAG}`. CI on this pull request waits for "Approve workflows to run".
