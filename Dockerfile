FROM docker.io/library/python:3.13-slim@sha256:6cbc4355e9cff50d6ae679b08435b355d388b62d32aa701d08ac9f77bd7c287c
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 /uv /uvx /bin/

ADD . /app
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "hvcwatch"]
