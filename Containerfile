# 🏗️ Stage 1: build the virtual environment with uv
FROM docker.io/library/python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS builder
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /uvx /bin/

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
FROM docker.io/library/python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

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
