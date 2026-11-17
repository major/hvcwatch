# hvcwatch

A bot that watches my inbox to find alerts from ThinkOrSwim.

## Logging

Logs go to stderr as JSON lines: one object per line with `timestamp` (UTC), `level`, `logger`, and `message`. Extra fields, such as ticker symbols, are top-level keys, and tracebacks appear under `exception`.

Read them with [hl](https://github.com/pamburus/hl):

```sh
# Running in a container (replace <container-name> with your container's name)
podman logs -f <container-name> 2>&1 | hl -F

# Running locally
uv run hvcwatch 2>&1 | hl
```
