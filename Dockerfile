# ②B 拍板：Playwright 内置主镜像（容器内 login 子命令后台控制浏览器）
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app
COPY app/ app/

ENV PYTHONPATH=/app \
    TZ=Asia/Shanghai \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1

RUN useradd -m appuser && mkdir -p /data && chown -R appuser:appuser /data
USER appuser

VOLUME /data
ENTRYPOINT ["python", "-m", "app.main"]
CMD ["daemon"]
