FROM docker.io/library/python:3.13-slim@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:1d31be550ff927957472b2a491dc3de1ea9b5c2d319a9cea5b6a48021e2990a6 /uv /uvx /bin/

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
