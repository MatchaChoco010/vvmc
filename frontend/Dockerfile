# syntax=docker/dockerfile:1

# --- build: Node で dist を生成 ------------------------------------------
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

# --- dist: 成果物を volume に配るだけの軽量イメージ --------------------
# compose の frontend-builder で起動され、/shared に dist を吐き出して終了する。
FROM busybox:stable AS dist
COPY --from=build /app/dist /dist
CMD ["sh", "-c", "mkdir -p /shared && cp -a /dist/. /shared/"]
