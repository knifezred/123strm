FROM python:3.12.7-alpine AS builder
WORKDIR /builder

RUN apk update && \
    apk add --no-cache \
    build-base \
    linux-headers

# 安装构建依赖
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/  --upgrade pip

COPY app ./app

FROM python:3.12.7-alpine

ENV TZ=Asia/Shanghai
VOLUME ["/config", "/media"]


COPY requirements.txt requirements.txt
# 修改pip安装命令部分，添加清华镜像源
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt && \
    rm requirements.txt

COPY --from=builder /builder/app /app

ENTRYPOINT ["python", "-u", "/app/main.py"]