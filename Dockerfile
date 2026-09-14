# NovelForge（novel_dl_convert）—— 多阶段构建镜像
#
# 三个阶段，各司其职：
#   1) builder  : 带编译工具链，把 requirements.txt 装进独立 venv /opt/venv
#   2) nodejs   : 官方 Node 镜像，只借它的 node 可执行文件（书源字体加密 / 内容混淆的 JS eval 用）
#   3) runtime  : python-slim，只搬「venv + node + 源码」，最终镜像不含 gcc / pip / apt 缓存
#
# 相比旧版单阶段（apt install nodejs + pip install 全塞在同一镜像里）的体积优化：
#   - 编译工具链（build-essential，含 gcc/g++/make）只活在 builder 阶段，不进最终镜像
#   - 只取官方 Node 二进制，不拉 Debian nodejs 的 npm / 文档 / libicu 等连带依赖
#   - venv 内剔除 pip / wheel，native .so 去符号表，且全程 --no-cache-dir
#   - 按路径精确 COPY + .dockerignore：venv/、_test/、.git/、本地 input/output 不进构建上下文
#
# 构建：docker build -t novelforge .
# 极致瘦身（不需要 JS 解密时）：删掉 runtime 阶段 `COPY --from=nodejs` 与 ENV 里的 NODE_BIN 即可，
# 那是最终镜像里最大的单个文件（约 90~110MB）。

ARG PY_VERSION=3.12
ARG NODE_VERSION=22
ARG APP_VERSION=0.5.0

# ============================ 阶段 1：依赖构建 ============================
FROM python:${PY_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100

# 顶层 ARG 只作用于 FROM 行，阶段内使用需重新声明
ARG INSTALL_BUILD_TOOLS=1

# 部分依赖在 arm64（很多 NAS 是 ARM）上可能没有现成 wheel，留一套构建工具兜底。
# 这些工具只存在于本阶段，不会进入最终镜像。
#
# 本地网络受限（deb.debian.org 不稳定、502）时可跳过：
#   docker build --build-arg INSTALL_BUILD_TOOLS=0 .
# amd64 上本项目依赖均有现成 wheel，无需编译工具链；默认 1，CI 行为不变。
RUN if [ "${INSTALL_BUILD_TOOLS}" = "0" ]; then \
        echo "[builder] 跳过 build-essential（假定依赖均有现成 wheel）"; \
    else \
        apt-get -o Acquire::Retries=5 update \
        && apt-get -o Acquire::Retries=5 install -y --no-install-recommends build-essential \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# 装进独立 venv：最终镜像整棵树拷过去即可，天然与系统 Python 隔离，也方便统一裁剪
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# 单独 COPY requirements.txt：依赖不变时复用缓存层，改源码不会触发重装
COPY requirements.txt /tmp/requirements.txt

# 允许替换 PyPI 源（国内网络 / 私有源），默认仍是官方源，CI 行为不变：
#   docker build --build-arg PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX=https://pypi.org/simple
RUN pip install --no-cache-dir --upgrade pip --index-url "${PIP_INDEX}" \
    && pip install --no-cache-dir --index-url "${PIP_INDEX}" -r /tmp/requirements.txt

# 裁剪 venv：运行时不再需要装包，pip / wheel 连同 native .so 的符号表一起去掉。
# 说明：保留 setuptools / pkg_resources —— 少数库会在运行时 import 它们，为这几 MB 冒
# 「启动即 ImportError」的风险不划算；若确认依赖树用不到，把 rm -rf 里再加两行即可：
#   /opt/venv/lib/python*/site-packages/setuptools \
#   /opt/venv/lib/python*/site-packages/setuptools-* \
RUN rm -rf /opt/venv/lib/python*/site-packages/pip \
           /opt/venv/lib/python*/site-packages/pip-* \
           /opt/venv/lib/python*/site-packages/wheel \
           /opt/venv/lib/python*/site-packages/wheel-* \
    && find /opt/venv -type f -name '*.a' -delete \
    && find /opt/venv -type f -name '*.so*' -exec sh -c 'for f; do strip --strip-unneeded "$f" 2>/dev/null || true; done' _ {} +

# ============================ 阶段 2：Node 源 ============================
# 与 python:${PY_VERSION}-slim 同为 Debian bookworm 基线，glibc 版本一致，二进制可直接搬
FROM node:${NODE_VERSION}-bookworm-slim AS nodejs

# ============================ 阶段 2.5：前端构建 ============================
# 构建 Vue 3 + Vite + Tailwind v4 前端，产物落 /web/dist。
# node_modules 与源码都只活在本阶段，不会进入最终镜像。
# 国内网络可换源：--build-arg NPM_REGISTRY=https://registry.npmmirror.com
FROM node:${NODE_VERSION}-bookworm-slim AS frontend

ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /web

# 先 COPY 清单再装依赖：源码变动不会让依赖层失效
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc /web/
RUN npm config set registry "${NPM_REGISTRY}" \
    && npm ci --no-audit --no-fund

COPY frontend/ /web/
RUN npm run build

# ============================ 阶段 3：运行镜像 ============================
FROM python:${PY_VERSION}-slim AS runtime

# 顶层 ARG 只作用于 FROM 行；阶段内使用需重新声明，否则 LABEL 里的 ${APP_VERSION} 会被展开成空
ARG APP_VERSION

LABEL org.opencontainers.image.title="NovelForge" \
      org.opencontainers.image.description="TXT 小说转 EPUB：FastAPI 服务 + CLI，支持可插拔书源" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/735876214/novel_dl_convert" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    TZ=Asia/Shanghai \
    INPUT_DIR=/app/input \
    OUTPUT_DIR=/app/output \
    CONFIG_DIR=/app/config \
    COOKIE_DIR=/app/config/cookies \
    CACHE_DIR=/app/config/cache \
    NODE_BIN=/usr/local/bin/node

# 运行期仅保留两类系统包：
#   tzdata     —— 让 TZ=Asia/Shanghai 真正生效（slim 基线默认不带时区库）
#   libstdc++6 —— Node 二进制的动态依赖；已存在时 apt 直接跳过，几乎不增加体积
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends tzdata libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# 只搬构建产物：venv 与 node 二进制，编译工具链 / apt 缓存自然被丢弃
COPY --from=builder /opt/venv /opt/venv
COPY --from=nodejs  /usr/local/bin/node /usr/local/bin/node

WORKDIR /app

# 精确 COPY，避免把本地 venv/、_test/、input/ 等目录带进镜像
COPY start.sh requirements.txt config.yaml /app/
COPY novelforge/ /app/novelforge/

# 前端构建产物覆盖 static/v2（v2 已进 .dockerignore，镜像里只有这一份）。
# 必须排在 COPY novelforge/ 之后，否则会被旧产物盖回去。
COPY --from=frontend /web/dist/ /app/novelforge/static/v2/

# 预建目录：保证配置文件以单文件方式挂载时挂载点一定存在
RUN chmod +x /app/start.sh \
    && mkdir -p /app/input /app/output /app/config /app/config/cookies /app/config/cache

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

STOPSIGNAL SIGTERM

CMD ["uvicorn", "novelforge.server:app", "--host", "0.0.0.0", "--port", "8000"]
