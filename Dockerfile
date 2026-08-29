# ---- 前端构建 ----
FROM node:20-alpine AS web
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY src ./src
COPY public ./public
COPY views ./views
RUN npm run build

# ---- 运行时（API + SPA 静态托管）----
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
COPY pipeline ./pipeline
COPY public ./public
COPY studio_paths.py ./
COPY --from=web /build/dist ./dist
RUN mkdir -p /app/data /root/.ssh && chmod 700 /root/.ssh
EXPOSE 8000
CMD ["python","-m","uvicorn","server.main:app","--host","0.0.0.0","--port","8000"]
