# bufferutil（@lookingglass/bridge の依存）は prebuild の無い環境で node-gyp を回すので、
# 依存のインストールだけビルドツール入りの段で済ませ、実行する段には持ち込まない
FROM node:24-slim AS deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-slim
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

EXPOSE 5173
# ホストのブラウザから届かせるので 0.0.0.0 で待つ
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
