# 🏗️ Stage 1: build the virtual environment with uv
FROM docker.io/library/python:3.15-slim@sha256:08a4c22c92b79ec821a7ad49768480039ee5b7accac3955228e75366e30abc8e AS builder
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f /uv /uvx /bin/

# ⚙️ Compile bytecode, copy files instead of linking, and never download a Python
# The venv links to the base image's Python, so the runtime stage must use the same image
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 📦 Install dependencies first so this layer stays cached until the lock file changes
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# 🔨 Add the source and install the project non-editable so the venv is self-contained
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# 🚀 Stage 2: runtime image with no uv and no build tools
FROM docker.io/library/python:3.15-slim@sha256:08a4c22c92b79ec821a7ad49768480039ee5b7accac3955228e75366e30abc8e

# 🏷️ Capture git commit info at build time (final stage only, so it does not bust the cache)
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV GIT_BRANCH=${GIT_BRANCH}

# 🛤️ Run hvcwatch and its dependencies from the venv
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# 📥 Copy only the venv; the project is installed inside it, so no source or data is needed
COPY --from=builder /app/.venv ./.venv

CMD ["hvcwatch"]
