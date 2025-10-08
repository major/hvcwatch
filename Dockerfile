FROM docker.io/library/python:3.13-slim@sha256:8d4ea9d6915221b2d78e39e0dea0c714a4affb73ba74e839dbf6f76c524f78e4
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:1d31be550ff927957472b2a491dc3de1ea9b5c2d319a9cea5b6a48021e2990a6 /uv /uvx /bin/

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
