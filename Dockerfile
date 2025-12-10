FROM docker.io/library/python:3.14-slim@sha256:fd2aff39e5a3ed23098108786a9966fb036fdeeedd487d5360e466bb2a84377b
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:5cb6b54d2bc3fe2eb9a8483db958a0b9eebf9edff68adedb369df8e7b98711a2 /uv /uvx /bin/

# Capture git commit info at build time
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV GIT_BRANCH=${GIT_BRANCH}

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
