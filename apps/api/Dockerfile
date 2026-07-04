# Multi-stage build, non-root user.
#
# Previously used a distroless final stage (gcr.io/distroless/python3-debian12),
# which broke on the first real deploy: that image actually ships Python 3.11,
# while the builder stage installed packages for 3.12 into a
# python3.12/site-packages path the 3.11 interpreter never looks in -- container
# crash-looped with "No module named uvicorn" on every start (found via Railway
# deploy logs, 2026-07-03). Even fixed, distroless's floating (untagged) base
# would silently re-break the same way any time Google bumps its bundled Python
# version, and distroless has no shell -- makes production debugging by a solo
# maintainer much harder. Switched to a single pinned python-slim image for both
# stages: one Python version everywhere, reproducible builds, and a shell
# available if we ever need to exec into a running container to debug.
FROM python:3.12.7-slim-bookworm AS builder

WORKDIR /build
COPY requirements.txt .
# --target (not --user) installs into a plain directory we control, independent
# of any $HOME/version-specific site-packages path -- avoids this whole class of
# bug regardless of which Python patch version ends up in the final image.
RUN pip install --no-cache-dir --target=/install -r requirements.txt

FROM python:3.12.7-slim-bookworm AS final

# Explicit non-root user with a fixed UID/GID, rather than relying on a base
# image to already define one (distroless did; python-slim does not).
RUN groupadd --gid 65532 nonroot && \
    useradd --uid 65532 --gid nonroot --no-create-home --shell /usr/sbin/nologin nonroot

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /install /app/.deps
# Railway's Root Directory for this service is apps/api/, so the build
# context here is apps/api/'s own contents, not the repo root -- confirmed
# via the real build log ("COPY requirements.txt ." only succeeds if the
# context starts inside apps/api/). Code throughout imports as apps.api.*
# (absolute from the real repo root), so the container has to reconstruct
# that same layout even though the build context itself starts one level
# deeper. Copying flatly into /app left no `apps` package at all --
# ModuleNotFoundError: No module named 'apps' at container start (found
# via Railway deploy logs, 2026-07-04). apps/__init__.py can't be COPYed
# in from this context since it lives outside apps/api/ (sibling of api/,
# not under it) -- created by hand instead.
COPY --chown=nonroot:nonroot . /app/apps/api/
RUN touch /app/apps/__init__.py && chown nonroot:nonroot /app/apps/__init__.py

ENV PYTHONPATH=/app/.deps:/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER nonroot

EXPOSE 8000

ENTRYPOINT ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
