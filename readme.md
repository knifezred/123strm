# 123strm 项目

## 项目简介

123strm 是一个用于管理和生成网盘文件 strm 的工具。

## 功能特性

- 使用 123 云盘官方 api，安全可靠，不依赖第三方
- 单线程下载，不会触发风控
- 可配置海报、字幕、nfo 文件是否下载
- 自动清理本地不存在于 123 云盘的文件
- 支持 302 链接，观看时自动获取最新的文件链接，绿联影视中心支持外网访问
- 1.8版本之后支持可视化配置，地址为ip:1236

## 生成速度

生成 strm 的速度与网盘目录文件夹内包含的子文件夹数量成正相关，简略计算方式为

> 生成时间=刮削目录子文件夹数量/3/60 （分钟）

以我的网盘为例，500+的子文件夹生成时间稳定在 3 分钟出头，即 556/3/60=3.08 分钟

如果选择下载 nfo、图片等文件，在第一次生成时会极大影响生成速度，耐心等待即可，也可以按照网盘目录结构从已有的刮削数据迁移过来节省时间，当本地存在文件时不会重新下载。

## 安装指南

```bash
# 1. 克隆仓库
git clone <仓库地址>
# 2. 安装依赖
pip install -r requirements.txt
# 3. 运行脚本
python app/amin.py
```

### 自行构建 docker 镜像

```bash
# 生成docker镜像
docker build -t 123strm .
# 生成本地镜像包
docker save -o 123strm.tar 123strm
# 压缩镜像包减小体积
gzip 123strm.tar
```

### 使用教程

#### compose 部署

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
      PUID: '0'
      PGID: '0'
```

#### config 配置

cron 配置示例。不建议配置时间间隔特别短如分钟执行，容易生成时间超过定时时间导致一直生成。仅支持以下几种格式

```
*/15 * * * *  # 每15分钟执行

0 */2 * * *  # 每2小时执行

0 0 * * *    # 每天0:00执行
0 1 */3 * *  # 每3天的1:00执行
45 23 * * *  # 每天23:45执行

0 0 * * 1    # 每周一0:00执行
0 9 * * 5    # 每周五9:00执行
30 15 * * 0  # 每周日15:30执行

0 0 1 * *    # 每月1日0:00执行
0 9 15 * *   # 每月15日9:00执行
30 12 28 * * # 每月28日12:30执行
```

```yml
# 定时任务cron表达式，不配置则默认为每天凌晨1点执行
# 为防止冲突，所有job都使用一个corn，依次生成直到全部结束
cron: '0 02 * * *'
# strm地址使用官方下载链接
use_302_url: True
# 不配置则默认不使用代理
proxy: 'http://nas_ip:1236'
# 302链接缓存过期时间(秒)，默认5分钟
cache_expire_time: 300
# strm路径前缀，可设置为cd2挂载的目录或者123盘webdav挂载的路径，需要加上对应设置的rootFolder的文件夹目录
# 如：选择的rootFolder为 /影视剧/电视剧，cd2映射的路径为 /volume1/docker/cloud_nas/123云盘
# 则path_prefix为 /volume1/docker/cloud_nas/123云盘/影视剧/电视剧、
# use_302_url=True时该设置无效
path_prefix: '/volume1/docker/cloud_nas/123云盘/影视剧/'
# 平铺模式，开启后 subtitle、image、nfo 强制关闭(可选，默认 False)
flatten_mode: False
# 视频文件后缀 （可选，默认 ['.mp4', '.mkv', '.ts', '.iso'] ）
video_extensions:
  ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.m2ts', '.ts', '.iso']
# 是否下载字幕文件（可选，默认 False）
subtitle: True
# 字幕文件后缀（可选，默认 ['.srt', '.ass', '.sub']）
subtitle_extensions: ['.srt', '.ass', '.sub']
# 是否下载图片文件（可选，默认 False）
image: True
# 图片文件后缀 （可选，默认 [".jpg", ".jpeg", ".png", ".webp"] ）
image_extensions: ['.jpg', '.jpeg', '.png', '.webp']
# 下载图片名后缀 （可选，默认下载全部 [] ）
download_image_suffix: ['poster', 'fanart']
# 是否下载 .nfo 文件（可选，默认 False）
nfo: True
# 覆盖模式，本地路径存在同名文件时是否重新生成/下载该文件，仅支持strm文件（可选，默认 False）
overwrite: False
# 视频文件最小限制，低于该大小的视频不处理，默认为100Mb
min_file_size: 104857600
# 程序启动后立即执行任务
running_on_start: True
# https://www.123pan.com/developer 注册获取
client_id: '123123'
client_secret: '123123'
# 输出路径
target_dir: '/media/'
# 以上所有设置均可在job_list中单独设置，优先使用job_list中的配置，没有的再使用默认值
# target_dir 为最终输出路径，job_list 中可以配置多个账号，每个账号可以配置多个文件夹，该配置必须为每个Job配置独立的文件夹，不能嵌套，不能相互包含，否则生成后会清空非Job配置获取的文件
job_list:
  - id: '账号1'
    # 123盘文件夹的ID
    # 浏览器打开对应文件夹,如：https://www.123pan.com/?homeFilePath=111111,222222
    # homeFilePath后的最后一串数字就是该文件夹的ID
    root_folder_id: '0'
    # 输出路径
    target_dir: '/media/账号1'
  - id: '账号2'
    # 文件夹1 文件夹2 文件夹3
    root_folder_id: '12312301,12312302,12312303'
    client_id: '234'
    client_secret: '234'
    target_dir: '/media/账号2'
```
