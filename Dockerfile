FROM docker.io/library/python:3.13-slim@sha256:3a6ead7603d322b80dd718d3834dcab86977c73b066028226afd8d0cdf1b0b12
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 /uv /uvx /bin/

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
