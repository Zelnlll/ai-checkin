# ②B 拍板：Playwright 内置主镜像（容器内 login 子命令后台控制浏览器）
# 国内直连 mcr.microsoft.com 被重置，走 DaoCloud 公共镜像（内容与官方一致）
# 原镜像：mcr.microsoft.com/playwright/python:v1.49.0-noble
FROM mcr.m.daocloud.io/playwright/python:v1.49.0-noble

WORKDIR /app
COPY app/ app/
# fnOS 上 git 写出的文件权限会是 000，构建期兜底修正（与源端 chmod 无关）
RUN chmod -R a+rX app/

# daocloud 转发的 playwright/python 基座缺 python 包本体，自装（版本对齐 /ms-playwright 浏览器）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com playwright==1.49.0

ENV PYTHONPATH=/app \
    TZ=Asia/Shanghai \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1

RUN useradd -m appuser && mkdir -p /data && chown -R appuser:appuser /data
USER appuser

VOLUME /data
ENTRYPOINT ["python", "-m", "app.main"]
CMD ["daemon"]
