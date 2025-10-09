FROM docker.io/library/python:3.14-slim@sha256:1e7c3510ceb3d6ebb499c86e1c418b95cb4e5e2f682f8e195069f470135f8d51
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:8f926a80debadba6f18442030df316c0e2b28d6af62d1292fb44b1c874173dc0 /uv /uvx /bin/

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
