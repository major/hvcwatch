FROM docker.io/library/python:3.14-slim@sha256:1e7c3510ceb3d6ebb499c86e1c418b95cb4e5e2f682f8e195069f470135f8d51
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:3b368e735c0227077902233a73c5ba17a3c2097ecdd83049cbaf2aa83adc8a20 /uv /uvx /bin/

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
