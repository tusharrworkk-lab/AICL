# Build this file with the controlled target repository as the Docker build context.
# The image must be reviewed before enabling ACIL's isolated runner.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /workspace
COPY --chown=65532:65532 . /workspace

# The runtime runner uses /tmp for the virtual environment and cache. This build
# check makes a missing/invalid lockfile fail before an image is approved.
RUN uv lock --check

USER 65532:65532
