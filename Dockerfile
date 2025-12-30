FROM docker.io/library/python:3.14-slim@sha256:aa5be1196770ff8c5896e3da0848332cd73663a99a69fc7a2b6772e53111793c
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:81f1a183fbdd9cec1498b066a32f0da043d4a9dda12b8372c7bfd183665e485d /uv /uvx /bin/

# Capture git commit info at build time
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV GIT_BRANCH=${GIT_BRANCH}

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
