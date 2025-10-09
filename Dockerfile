FROM docker.io/library/python:3.14-slim@sha256:7bea65ece84b6f78689e6f2caa60d386452ef5db9361484523b18fb84f95389c
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:8f926a80debadba6f18442030df316c0e2b28d6af62d1292fb44b1c874173dc0 /uv /uvx /bin/

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
