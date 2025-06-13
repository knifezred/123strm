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

# 添加时区设置
import pytz


# 全局配置变量
config = None

# 全局网盘文件列表
cloud_files = set()


# 初始化网盘文件列表
def clean_cloud_files():
    global cloud_files
    cloud_files.clear()


# 读取配置文件
def load_config():
    """
    从config.yml加载配置信息并保存到全局变量
    :return: 包含clientID和clientSecret的字典
    """
    global config
    with open("/config/config.yml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def get_access_token():
    """
    获取123云盘API访问令牌
    优先使用本地缓存，根据过期时间判断是否需要重新获取
    :return: accessToken字符串
    """
    # 尝试从缓存文件读取token信息
    try:
        with open("token_cache.json", "r") as f:
            cache = json.load(f)
            if datetime.fromisoformat(cache["expiredAt"]).replace(
                tzinfo=None
            ) > datetime.now().replace(tzinfo=None):
                return cache["accessToken"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # 获取新token
    config = load_config()
    conn = http.client.HTTPSConnection("open-api.123pan.com")
    payload = json.dumps(
        {"clientID": config["clientID"], "clientSecret": config["clientSecret"]}
    )
    headers = {"Platform": "open_platform", "Content-Type": "application/json"}
    conn.request("POST", "/api/v1/access_token", payload, headers)
    res = conn.getresponse()
    data = res.read()
    response = json.loads(data.decode("utf-8"))

    # 保存token到缓存文件
    with open("token_cache.json", "w") as f:
        json.dump(
            {
                "accessToken": response["data"]["accessToken"],
                "expiredAt": response["data"]["expiredAt"],
            },
            f,
        )

    return response["data"]["accessToken"]


def get_file_download_info(file_id, access_token=None):
    """
    获取文件下载信息
    :param file_id: 文件ID
    :param access_token: 访问令牌，如果未提供则自动获取
    :return: 下载信息JSON数据
    """
    conn = http.client.HTTPSConnection("open-api.123pan.com")
    if not access_token:
        access_token = get_access_token()
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


def download_file(url, save_path):
    """
    根据指定的URL下载文件并保存到指定路径。

    :param url: 文件的下载URL
    :param save_path: 文件保存的本地路径
    :return: 若下载成功返回True，否则返回False
    """
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
        print(f"下载文件时出错: {e}")
        return False


def get_file_list(parent_file_id=0, limit=100, access_token=None):
    """
    获取文件列表
    :param parent_file_id: 父文件夹ID，默认为0（根目录）
    :param limit: 返回的文件数量限制，默认为100
    :param access_token: 访问令牌，如果未提供则自动获取
    :return: 文件列表JSON数据
    """
    if not access_token:
        access_token = get_access_token()

    conn = http.client.HTTPSConnection("open-api.123pan.com")
    payload = ""
    headers = {
        "Content-Type": "application/json",
        "Platform": "open_platform",
        "Authorization": f"Bearer {access_token}",
    }
    conn.request(
        "GET",
        f"/api/v2/file/list?parentFileId={parent_file_id}&limit={limit}",
        payload,
        headers,
    )
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))


def process_file(file_info, config, access_token, parent_path):
    """
    处理单个文件
    :param file_info: 文件信息字典
    :param config: 配置信息
    :param access_token: 访问令牌
    """
    # 视频文件扩展名
    video_extensions = [".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".m2ts"]
    # 图片文件扩展名
    image_extensions = [".jpg", ".jpeg", ".png"]
    # 字幕文件扩展名
    subtitle_extensions = [".srt", ".ass", ".ssa", ".sub"]

    file_name = file_info.get("filename", "")
    file_extension = os.path.splitext(file_name)[1].lower()
    target_path = os.path.join(config["targetDir"], parent_path)
    if file_extension in video_extensions:
        # 只处理大于最小文件大小的文件
        if int(file_info["size"]) <= int(config["minFileSize"]):
            return
        # 生成strm文件
        video_url = os.path.join(config["pathPrefix"], parent_path, file_name)
        if config.get("flatten_mode", False):
            # 平铺模式
            target_path = config["targetDir"]
            strm_path = os.path.join(target_path, file_name + ".strm")
        else:
            strm_path = os.path.join(target_path, file_name + ".strm")

        if not os.path.exists(os.path.dirname(strm_path)):
            os.makedirs(os.path.dirname(strm_path), exist_ok=True)
        with open(strm_path, "w", encoding="utf-8") as f:
            f.write(video_url)
        cloud_files.add(strm_path)
        print("生成strm: " + strm_path)
    elif file_extension in image_extensions and should_download_file("image"):
        download_with_log("图片", target_path, file_info, access_token)
    elif file_extension in subtitle_extensions and should_download_file("subtitle"):
        download_with_log("字幕", target_path, file_info, access_token)
    elif file_extension == ".nfo" and should_download_file("nfo"):
        download_with_log("nfo", target_path, file_info, access_token)


def should_download_file(file_type):
    """
    判断是否应该下载指定类型的文件
    :param file_type: 文件类型配置名
    :return: bool 是否下载
    """
    return config.get(file_type, False) and config.get("flatten_mode", False) == False


def download_with_log(file_type, target_path, file_info, access_token):
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
    if os.path.exists(target_file):
        print(f"已存在，跳过下载: {target_file}")
    else:
        download_url = get_file_download_info(file_info["fileId"], access_token)
        download_file(download_url, target_file)
        print(f"下载完成: {target_file}")


def traverse_folders(parent_id=0, access_token=None, indent=0, parent_path=""):
    """
    递归遍历所有文件夹
    :param parent_id: 起始文件夹ID，默认为0（根目录）
    :param access_token: 访问令牌，如果未提供则自动获取
    :param indent: 缩进级别，用于格式化输出
    """
    if not access_token:
        access_token = get_access_token()

    # 确保配置已加载
    if config is None:
        load_config()
    if parent_id == 0:
        parent_id = config["rootFolderId"]

    # 获取当前目录下的文件和文件夹
    file_list = get_file_list(
        parent_file_id=parent_id, limit=100, access_token=access_token
    )

    for item in file_list["data"]["fileList"]:
        # 如果是文件夹，递归遍历
        if item["type"] == 1:
            # 记录文件夹
            cloud_files.add(
                os.path.join(config["targetDir"], parent_path, item["filename"])
            )
            traverse_folders(
                item["fileId"],
                access_token,
                indent + 1,
                os.path.join(parent_path, item["filename"]),
            )
        # 如果是文件，进行处理
        elif item["type"] == 0:
            process_file(item, config, access_token, parent_path)


def clean_local_files(local_dir):
    """
    清理本地目录中不在网盘文件列表中的文件和空文件夹
    :param local_dir: 要清理的本地目录路径
    """
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
    # 加载config配置
    config = load_config()
    access_token = get_access_token()
    # 清空云盘文件列表
    clean_cloud_files()
    traverse_folders(access_token=access_token)
    # 遍历完成后清理过期文件和空文件夹
    clean_local_files(config["targetDir"])
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 定时任务执行完成")


job_lock = threading.Lock()
is_running = False


def schedule_job():
    global is_running

    with job_lock:
        if is_running:
            return
        is_running = True
    try:
        job()
    finally:
        is_running = False


print("123strm v0.1 已启动...", flush=True)
config = load_config()
print("config加载成功")
# 计算下次执行时间
if "cron" in config:
    cron = croniter(config["cron"], datetime.now())
    next_time = cron.get_next(datetime)
    print(f"下次执行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
    # 直接使用cron表达式触发，不计算delay
    schedule.every().day.at(next_time.strftime("%H:%M")).do(job)
else:
    # 默认定时任务
    schedule.every().day.at("01:00").do(job)  # 每天凌晨1点执行
try:
    while True:
        schedule.run_pending()
        print(f"当前时间: {datetime.now()}, 下次任务时间: {schedule.next_run()}")
        time.sleep(30)
except Exception as e:
    print(f"定时任务异常: {str(e)}")

except KeyboardInterrupt:
    print("程序退出")
