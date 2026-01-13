FROM docker.io/library/python:3.14-slim@sha256:38b6cc0b45b13563b14615a9b51dd07ac519b9d3cbd945df114477fe0cc988f1
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:816fdce3387ed2142e37d2e56e1b1b97ccc1ea87731ba199dc8a25c04e4997c5 /uv /uvx /bin/

# Capture git commit info at build time
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV GIT_BRANCH=${GIT_BRANCH}

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
