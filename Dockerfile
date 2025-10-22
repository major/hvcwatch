FROM docker.io/library/python:3.14-slim@sha256:79eaa9622e4daa24b775ac2c9b6dc49b4f302ce925e3dcf1851782b9c93cf5f5
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:c4089b0085cf4d38e38d5cdaa5e57752c1878a6f41f2e3a3a234dc5f23942cb4 /uv /uvx /bin/

# Capture git commit info at build time
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV GIT_BRANCH=${GIT_BRANCH}

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
