FROM docker.io/library/python:3.14-slim@sha256:b823ded4377ebb5ff1af5926702df2284e53cecbc6e3549e93a19d8632a1897e
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:ae9ff79d095a61faf534a882ad6378e8159d2ce322691153d68d2afac7422840 /uv /uvx /bin/

# Capture git commit info at build time
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV GIT_BRANCH=${GIT_BRANCH}

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
