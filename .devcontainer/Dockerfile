FROM python:3.14-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash vscode

# Keep Linux dependencies separate from the host-mounted source tree.
ENV UV_PROJECT_ENVIRONMENT=/home/vscode/.local/share/json-to-schema/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/home/vscode/.local/share/json-to-schema/venv/bin:/home/vscode/.local/bin:$PATH"

USER vscode
