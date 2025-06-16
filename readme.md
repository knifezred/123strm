# 123strm 项目

## 项目简介
123strm 是一个用于管理和生成网盘文件strm的工具。

## 功能特性
- 使用123云盘官方api，安全可靠，不依赖第三方
- 单线程下载，不会触发风控
- 可配置海报、字幕、nfo文件是否下载
- 自动清理本地不存在于123云盘的文件

## 安装指南

```bash
# 1. 克隆仓库
git clone <仓库地址>
# 2. 安装依赖
pip install -r requirements.txt
# 3. 运行脚本
python app/amin.py
```

### 自行构建docker镜像

```bash
# 生成docker镜像
docker build -t 123strm .
# 生成本地镜像包
docker save -o 123strm.tar 123strm
# 压缩镜像包减小体积
gzip 123strm.tar
```

### 使用教程

#### compose部署

```yml
services:
  autofilm:
    image: 123strm:latest
    container_name: 123strm
    network_mode: host
    volumes:
      - /volume1/docker/123strm/config:/config
      - /volume1/docker/123strm/media:/media
    restart: always
    working_dir: /app
    environment:
        PUID: "0"
        PGID: "0"
```

#### config配置


```yml
# https://www.123pan.com/developer 注册获取
clientID: ""
clientSecret: ""
# 123盘文件夹的ID
# 浏览器打开对应文件夹https://www.123pan.com/?homeFilePath=1312389
# homeFilePath后的最后一串数字就是该文件夹的ID。如要配置根目录，直接设置为0
rootFolderId: "0"
# 输出路径
targetDir: "/media/"
# 定时任务cron表达式，不配置则默认为每天凌晨1点执行
cron: "0 10 * * *"
# 平铺模式，开启后 subtitle、image、nfo 强制关闭(可选，默认 False)
flatten_mode: False
# strm路径前缀，可设置为cd2挂载的目录或者123盘webdav挂载的路径，需要加上对应设置的rootFolder的文件夹目录
# 如：选择的rootFolder为 /影视剧/电视剧，cd2映射的路径为 /volume1/docker/cloud_nas/123云盘
# 则pathPrefix为 /volume1/docker/cloud_nas/123云盘/影视剧/电视剧
pathPrefix: "/volume1/docker/cloud_nas/123云盘/影视剧"
# 是否下载字幕文件（可选，默认 False）
subtitle: True
# 是否下载图片文件（可选，默认 False）
image: True
# 是否下载 .nfo 文件（可选，默认 False）
nfo: True
# 视频文件最小限制，低于该大小的视频不处理，默认为100Mb
minFileSize: 104857600
# strm地址使用官方下载链接
use302Url: False
# 覆盖模式，本地路径存在同名文件时是否重新生成/下载该文件，仅支持strm文件（可选，默认 False）
overwrite: False
```
