import http.client
import json
import yaml
import os
import requests
import time
import schedule
import threading
from croniter import croniter
from datetime import datetime
import aiohttp
import aiofiles
import asyncio
import uvicorn
from fastapi import FastAPI
from fastapi import Query
from fastapi.responses import RedirectResponse
from dataclasses import dataclass


@dataclass
class CacheItem:
    file_id: int
    url: str
    expire_time: float


# 添加时区设置
import pytz


# 全局配置变量
config = None
configFolder = "/config/"
# 全局网盘文件列表
cloud_files = set()

# 文件下载URL缓存 (存储格式: {file_id: {'url': url, 'expire_time': timestamp}})
download_url_cache = set()


def add_cache_url(file_id, url, expire_time):
    """
    添加文件下载URL到缓存
    :param file_id: 文件ID
    :param url: 下载URL
    :param expire_time: 过期时间
    """
    # 防止重复添加
    temp_url_item = get_cache_url(file_id)
    if temp_url_item is not None:
        # 存在则更新
        return
    download_url_cache.add(CacheItem(file_id=file_id, url=url, expire_time=expire_time))


def get_cache_url(file_id):
    """
    获取文件下载URL缓存
    :param file_id: 文件ID
    :return: url
    """
    for item in list(download_url_cache):
        if item.file_id == file_id:
            return item.url
    return None


# 读取配置文件
def load_config():
    """
    从config.yml加载配置信息并保存到全局变量
    :return: 包含clientID和clientSecret的字典
    """
    global config
    config_path = os.path.join(configFolder, "config.yml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def get_config_val(key, job_id=None):
    """
    从config.yml读取配置信息
    :param key: 配置项key
    :param job_id: 任务ID，可选
    :return: 配置项value
    """
    if job_id is not None:
        for job in config["JobList"]:
            if job is None:
                print("job任务配置异常")

            if job is not None and job["id"] == job_id:
                if key not in job:
                    return config[key]
                else:
                    return job[key]
    if key not in config:
        raise ValueError(f"配置项 {key} 不存在")
    return config[key]


def get_access_token(job_id):
    """
    获取123云盘API访问令牌
    优先使用本地缓存，根据过期时间判断是否需要重新获取
    :return: accessToken字符串
    """
    clientId = get_config_val("clientID", job_id)
    # 根据clientID生成缓存文件名
    cache_file = os.path.join(configFolder, f"token_cache_{clientId}.json")

    # 尝试从缓存文件读取token信息
    try:
        with open(cache_file, "r") as f:
            cache = json.load(f)
            if datetime.fromisoformat(cache["expiredAt"]).replace(
                tzinfo=None
            ) > datetime.now().replace(tzinfo=None):
                return cache["accessToken"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    clientSecret = get_config_val("clientSecret", job_id)
    # 获取新token
    conn = http.client.HTTPSConnection("open-api.123pan.com")
    payload = json.dumps({"clientID": clientId, "clientSecret": clientSecret})
    headers = {"Platform": "open_platform", "Content-Type": "application/json"}
    conn.request("POST", "/api/v1/access_token", payload, headers)
    res = conn.getresponse()
    data = res.read()
    response = json.loads(data.decode("utf-8"))

    # 保存token到缓存文件
    with open(cache_file, "w") as f:
        json.dump(
            {
                "accessToken": response["data"]["accessToken"],
                "expiredAt": response["data"]["expiredAt"],
            },
            f,
        )

    return response["data"]["accessToken"]


def get_file_download_info(file_id, job_id, access_token=None):
    """
    获取文件下载信息
    :param file_id: 文件ID
    :param access_token: 访问令牌，如果未提供则自动获取
    :return: 下载信息JSON数据
    """
    conn = http.client.HTTPSConnection("open-api.123pan.com")
    if not access_token:
        access_token = get_access_token(job_id)
    payload = ""
    headers = {
        "Content-Type": "application/json",
        "Platform": "open_platform",
        "Authorization": f"Bearer {access_token}",
    }
    conn.request(
        "GET", f"/api/v1/file/download_info?fileId={file_id}", payload, headers
    )
    res = conn.getresponse()
    data = res.read()
    response = json.loads(data.decode("utf-8"))
    return response["data"]["downloadUrl"]


def should_download_file(file_type, job_id):
    """
    判断是否应该下载指定类型的文件
    :param file_type: 文件类型配置名
    :return: bool 是否下载
    """
    return (
        get_config_val(file_type, job_id)
        and get_config_val("flatten_mode", job_id) == False
    )


def download_with_log(file_type, target_path, file_info, job_id, access_token):
    """
    下载文件并打印日志
    :param file_type: 文件类型名称(用于日志)
    :param target_path: 生成路径
    :param file_info: 文件详情
    :param access_token: token
    """
    target_file = os.path.join(target_path, file_info.get("filename", ""))
    cloud_files.add(target_file)
    # 判断文件是否存在
    if not os.path.exists(target_file):
        download_url = get_file_download_info(file_info["fileId"], job_id, access_token)
        download_file(download_url, target_file)
        print(f"下载成功: {target_file}")


def download_file(url, save_path):
    """
    根据指定的URL下载文件并保存到指定路径。
    :param url: 文件的下载URL
    :param save_path: 文件保存的本地路径
    :return: 若下载成功返回True，否则返回False
    """
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            # 检查保存路径的文件夹是否存在，如果不存在则创建
            if not os.path.exists(os.path.dirname(save_path)):
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            return True
        except requests.RequestException as e:
            retry_count += 1
            if retry_count == max_retries:
                print(f"下载文件失败，已达最大重试次数{max_retries}: {e}")
                return False
            print(f"下载文件出错(第{retry_count}次重试): {e}")
            time.sleep(1)  # 重试前等待1秒


def get_file_list(
    job_id, parent_file_id=0, limit=100, lastFileId=None, access_token=None
):
    """
    获取文件列表
    :param parent_file_id: 父文件夹ID，默认为0（根目录）
    :param limit: 返回的文件数量限制，默认为100
    :param access_token: 访问令牌，如果未提供则自动获取
    :return: 文件列表JSON数据
    """
    if not access_token:
        access_token = get_access_token(job_id)

    conn = http.client.HTTPSConnection("open-api.123pan.com")
    payload = ""
    headers = {
        "Content-Type": "application/json",
        "Platform": "open_platform",
        "Authorization": f"Bearer {access_token}",
    }
    conn.request(
        "GET",
        f"/api/v2/file/list?parentFileId={parent_file_id}&limit={limit}"
        + (f"&lastFileId={lastFileId}" if lastFileId else ""),
        payload,
        headers,
    )
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))


def get_file_info(fileId, job_id, access_token=None):
    if not access_token:
        access_token = get_access_token(job_id)
    conn = http.client.HTTPSConnection("open-api.123pan.com")
    payload = ""
    headers = {
        "Content-Type": "application/json",
        "Platform": "open_platform",
        "Authorization": f"Bearer {access_token}",
    }
    conn.request("GET", f"/api/v1/file/detail?fileID={fileId}", payload, headers)
    res = conn.getresponse()
    data = res.read()
    response = json.loads(data.decode("utf-8"))
    return response["data"]["filename"]


def traverse_folders(job_id, parent_id=0, access_token=None, indent=0, parent_path=""):
    """
    递归遍历所有文件夹
    优化点：
    1. 预先加载配置避免重复检查
    2. 减少重复获取access_token
    3. 优化分页处理逻辑

    :param parent_id: 起始文件夹ID，默认为0（根目录）
    :param access_token: 访问令牌，如果未提供则自动获取
    :param indent: 缩进级别，用于格式化输出
    """
    # 一次性加载配置和token
    if config is None:
        load_config()
    if not access_token:
        access_token = get_access_token(job_id)
    if parent_id == 0:
        parent_id = get_config_val("rootFolderId", job_id=job_id)
    # 兼容同账号多文件夹配置
    if "," in str(parent_id):
        parent_id_list = parent_id.split(",")
        for parent_id in parent_id_list:
            # 多文件夹保留当前文件夹目录
            parent_path = get_file_info(parent_id, job_id, access_token)
            traverse_folders(job_id, parent_id, access_token, indent, parent_path)
    # 处理当前页和所有分页数据
    last_file_id = None
    while True:
        file_list = get_file_list(
            job_id,
            parent_file_id=parent_id,
            limit=100,
            lastFileId=last_file_id,
            access_token=access_token,
        )
        process_file_list(
            job_id, file_list, parent_id, parent_path, indent, access_token
        )

        if file_list["data"]["lastFileId"] == -1:
            break
        last_file_id = file_list["data"]["lastFileId"]


def process_file_list(job_id, file_list, parent_id, parent_path, indent, access_token):
    """处理文件列表中的每个项目
    优化点：
    1. 预先计算target_dir路径避免重复计算
    2. 使用更快的路径拼接方式
    3. 减少不必要的变量创建
    """
    target_dir = get_config_val("targetDir", job_id=job_id)
    file_list_data = file_list["data"]["fileList"]

    for item in file_list_data:
        item_type = item["type"]
        filename = item["filename"]
        full_path = f"{parent_path}/{filename}" if parent_path else filename

        if item_type == 1:  # 文件夹
            cloud_files.add(os.path.join(target_dir, full_path))
            traverse_folders(
                job_id, item["fileId"], access_token, indent + 1, full_path
            )
        elif item_type == 0:  # 文件
            process_file(item, access_token, parent_path, job_id)


def process_file(file_info, access_token, parent_path, job_id):
    """
    处理单个文件
    :param file_info: 文件信息字典
    :param access_token: 访问令牌
    """
    # 视频文件扩展名
    video_extensions = [".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".m2ts"]
    # 图片文件扩展名
    image_extensions = [".jpg", ".jpeg", ".png"]
    # 字幕文件扩展名
    subtitle_extensions = [".srt", ".ass", ".ssa", ".sub"]

    file_name = file_info.get("filename", "")
    file_base_name, file_extension = os.path.splitext(file_name)
    target_path = os.path.join(get_config_val("targetDir", job_id), parent_path)
    if file_extension in video_extensions:
        # 只处理大于最小文件大小的文件
        if int(file_info["size"]) <= int(get_config_val("minFileSize", job_id)):
            return
        # 生成strm文件
        video_url = os.path.join(
            get_config_val("pathPrefix", job_id), parent_path, file_name
        )
        if get_config_val("use302Url", job_id):
            video_url = f"{get_config_val("proxy",job_id)}/get_file_url/{file_info["fileId"]}?job_id={job_id}"
        if get_config_val("flatten_mode", job_id):
            # 平铺模式
            target_path = get_config_val("targetDir", job_id)
            strm_path = os.path.join(target_path, file_base_name + ".strm")
        else:
            strm_path = os.path.join(target_path, file_base_name + ".strm")

        if not os.path.exists(os.path.dirname(strm_path)):
            os.makedirs(os.path.dirname(strm_path), exist_ok=True)
        # 检查文件是否存在，文件不存在或者覆写为True时写入文件
        if not os.path.exists(strm_path) or get_config_val("overwrite", job_id):
            with open(strm_path, "w", encoding="utf-8") as f:
                f.write(video_url)
            print(strm_path)
        cloud_files.add(strm_path)
    elif file_extension in image_extensions and should_download_file("image", job_id):
        download_with_log("图片", target_path, file_info, job_id, access_token)
    elif file_extension in subtitle_extensions and should_download_file(
        "subtitle", job_id
    ):
        download_with_log("字幕", target_path, file_info, job_id, access_token)
    elif file_extension == ".nfo" and should_download_file("nfo", job_id):
        download_with_log("nfo", target_path, file_info, job_id, access_token)


# 初始化网盘文件列表
def clean_cloud_files():
    global cloud_files
    cloud_files.clear()


def clean_local_files(local_dir):
    """
    清理本地目录中不在网盘文件列表中的文件和空文件夹
    :param local_dir: 要清理的本地目录路径
    """
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始清理空目录和失效文件")
    for root, dirs, files in os.walk(local_dir, topdown=False):
        # 删除不在网盘列表中的文件
        for file in files:
            file_path = os.path.join(root, file)
            if file_path not in cloud_files:
                os.remove(file_path)
                print(f"删除文件: {file_path}")

        # 删除空文件夹
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    print(f"删除空文件夹: {dir_path}")
            except OSError:
                pass


def job():
    # 确保使用正确时区
    now = datetime.now(pytz.timezone("Asia/Shanghai"))
    print(f"任务执行时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始执行定时任务")
    # 加载最新config配置
    config = load_config()
    # 检查配置中是否存在 JobList
    if "JobList" in config:
        # 遍历 JobList 中的每个任务
        for job in config["JobList"]:
            job_id = job["id"]
            print(f"正在处理任务: {job_id}")
            # 清空云盘文件列表
            clean_cloud_files()
            # 这里可以根据具体需求添加对每个任务的处理逻辑
            traverse_folders(job_id)
            # 遍历完成后清理过期文件和空文件夹
            clean_local_files(get_config_val("targetDir", job_id=job_id))
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 定时任务执行完成")


print("123strm v1.0 已启动...", flush=True)
config = load_config()
if config is not None:
    print("config加载成功")
else:
    # 抛出一个自定义异常，这里以 ValueError 为例
    raise ValueError("config加载失败，程序执行异常")
# 计算下次执行时间
if "cron" in config:
    cron = croniter(config["cron"], datetime.now())
    next_time = cron.get_next(datetime)
    print(f"下次执行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
    schedule.every().day.at(next_time.strftime("%H:%M")).do(job)
else:
    # 默认定时任务
    schedule.every().day.at("01:00").do(job)  # 每天凌晨1点执行


# 启动api
app = FastAPI()


@app.get("/")
async def index():
    return "123strm已启动"


@app.get("/get_file_url/{file_id}")
async def get_file_url(file_id: int, job_id: str = Query(..., min_length=1)):
    """
    获取文件下载链接
    :param file_id: 文件ID (必须为正整数)
    :param job_id: 任务ID (必须为非空字符串)
    :return: 文件下载链接或错误信息
    :raises HTTPException 400: 当参数验证失败时
    """
    # 参数验证
    if file_id <= 0:
        raise HTTPException(status_code=400, detail="文件ID必须为正整数")
    if not job_id:
        raise HTTPException(status_code=400, detail="任务ID不能为空")
    # 检查缓存
    cache_item = get_cache_url(file_id)
    if cache_item is not None:
        print(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 从缓存获取302跳转URL: {cache_item['url']}"
        )
        return RedirectResponse(cache_item["url"], 302)

    # 获取下载URL并存入缓存
    try:
        download_url = get_file_download_info(file_id, job_id)
        if not download_url:
            raise HTTPException(status_code=404, detail="文件未找到")

        # 存储URL和过期时间
        add_cache_url(
            file_id,
            download_url,
            time.time() + get_config_val("cacheExpireTime", job_id),
        )
        print(f"[{time.strftime('%m-%d %H:%M:%S')}] 302跳转成功: {download_url}")
        return RedirectResponse(download_url, 302)
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 获取文件下载链接失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取文件下载链接失败")
    raise HTTPException(status_code=404, detail="文件未找到")


async def run_scheduler():
    """
    运行定时任务调度器
    """
    # 开启即运行
    if config.get("runningOnStart", False):
        job()
    while True:
        schedule.run_pending()
        for item in list(download_url_cache):
            if time.time() > item.expire_time:
                download_url_cache.remove(item)
        await asyncio.sleep(60)


async def main():
    """
    主函数，同时启动API服务和定时任务
    """
    server = uvicorn.Server(config=uvicorn.Config(app=app, host="0.0.0.0", port=1236))
    await asyncio.gather(server.serve(), run_scheduler())


if __name__ == "__main__":
    asyncio.run(main())
