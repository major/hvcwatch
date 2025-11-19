FROM docker.io/library/python:3.14-slim@sha256:119fd5bd9c01a9283d0be29d31218fb04f4575c67b3e89151417d61f6e1a6f58
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:29bd45092ea8902c0bbb7f0a338f0494a382b1f4b18355df5be270ade679ff1d /uv /uvx /bin/

# Capture git commit info at build time
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV GIT_BRANCH=${GIT_BRANCH}

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
