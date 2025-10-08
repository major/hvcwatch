FROM docker.io/library/python:3.13-slim@sha256:8d4ea9d6915221b2d78e39e0dea0c714a4affb73ba74e839dbf6f76c524f78e4
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:8f926a80debadba6f18442030df316c0e2b28d6af62d1292fb44b1c874173dc0 /uv /uvx /bin/

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
