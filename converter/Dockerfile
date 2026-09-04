# Python 本体は uv が管理する方針をそのまま持ち込む（.claude/rules/converter-python.md）
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

# 動画の入出力は ffmpeg の外部プロセスに任せているので、イメージ側に実体が要る
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存だけ先に解決してレイヤを分ける。src を触るたびに再ダウンロードさせない
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# 入出力はリポジトリを /work にマウントして受け渡す。相対パスがホストと同じ意味になる
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /work
ENTRYPOINT ["lkg-quilt-converter"]
