import http.client
import json
import yaml
import os
import requests
import time
import schedule
import threading
import urllib.parse
from croniter import croniter
from datetime import datetime
import aiohttp
import aiofiles
import asyncio
import uvicorn

from app.api import (
    get_access_token,
    get_file_download_info,
    get_file_list,
    get_file_info,
    heartbeat,
    clean_download_url_cache,
)

from app.api import local302Api

from app.utils import Utils

# 添加时区设置
import pytz

my_utils = Utils()

# 全局网盘文件列表
cloud_files = set()


def should_download_file(file_type, job_id):
    """
    判断是否应该下载指定类型的文件
    :param file_type: 文件类型配置名
    :return: bool 是否下载
    """
    return (
        my_utils.get_config_val(file_type, job_id, default_val=False)
        and my_utils.get_config_val("flatten_mode", job_id, default_val=False) == False
    )


def download_with_log(file_type, target_path, file_info, job_id):
    """
    下载文件并打印日志
    :param file_type: 文件类型名称(用于日志)
    :param target_path: 生成路径
    :param file_info: 文件详情
    """
    target_file = os.path.join(target_path, file_info.get("filename", ""))
    cloud_files.add(target_file)
    # 判断文件是否存在
    if not os.path.exists(target_file):
        download_url = get_file_download_info(file_info["fileId"], job_id)
        my_utils.download_file(download_url, target_file)
        print(f"下载成功: {target_file}")


def traverse_folders(job_id, parent_id=0, indent=0, parent_path=""):
    if parent_id == 0:
        parent_id = my_utils.get_config_val("rootFolderId", job_id=job_id)
    # 兼容同账号多文件夹配置
    if "," in str(parent_id):
        parent_id_list = parent_id.split(",")
        for parent_id in parent_id_list:
            # 多文件夹保留当前文件夹目录
            parent_path = get_file_info(parent_id, job_id)
            traverse_folders(job_id, parent_id, indent, parent_path)
    # 处理当前页和所有分页数据
    last_file_id = None
    while True:
        file_list = get_file_list(
            job_id, parent_file_id=parent_id, limit=100, lastFileId=last_file_id
        )
        process_file_list(job_id, file_list, parent_id, parent_path, indent)

        if file_list["data"]["lastFileId"] == -1:
            break
        last_file_id = file_list["data"]["lastFileId"]


def process_file_list(job_id, file_list, parent_id, parent_path, indent):
    """处理文件列表中的每个项目
    优化点：
    1. 预先计算target_dir路径避免重复计算
    2. 使用更快的路径拼接方式
    3. 减少不必要的变量创建
    """
    target_dir = my_utils.get_config_val("targetDir", job_id=job_id)
    file_list_data = file_list["data"]["fileList"]

    for item in file_list_data:
        item_type = item["type"]
        filename = item["filename"]
        full_path = f"{parent_path}/{filename}" if parent_path else filename

        if item_type == 1:  # 文件夹
            cloud_files.add(os.path.join(target_dir, full_path))
            traverse_folders(job_id, item["fileId"], indent + 1, full_path)
        elif item_type == 0:  # 文件
            process_file(item, parent_path, job_id)


def process_file(file_info, parent_path, job_id):
    """
    处理单个文件
    :param file_info: 文件信息字典
    """
    # 视频文件扩展名
    video_extensions = [".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".m2ts"]
    # 图片文件扩展名
    image_extensions = [".jpg", ".jpeg", ".png"]
    # 字幕文件扩展名
    subtitle_extensions = [".srt", ".ass", ".ssa", ".sub"]

    file_name = file_info.get("filename", "")
    file_base_name, file_extension = os.path.splitext(file_name)
    target_path = os.path.join(
        my_utils.get_config_val("targetDir", job_id), parent_path
    )
    if file_extension in video_extensions:
        # 只处理大于最小文件大小的文件
        if int(file_info["size"]) <= int(
            my_utils.get_config_val("minFileSize", job_id, default_val=104857600)
        ):
            return
        # 生成strm文件
        video_url = os.path.join(
            my_utils.get_config_val("pathPrefix", job_id, default_val="/"),
            parent_path,
            file_name,
        )
        if my_utils.get_config_val("use302Url", job_id, default_val=True):
            job_id_encode = urllib.parse.quote(job_id)
            video_url = f"{my_utils.get_config_val("proxy",job_id,default_val="http://127.0.0.1:1236")}/get_file_url/{file_info["fileId"]}/{job_id_encode}"
        if my_utils.get_config_val("flatten_mode", job_id, default_val=False):
            # 平铺模式
            target_path = my_utils.get_config_val("targetDir", job_id)
            strm_path = os.path.join(target_path, file_base_name + ".strm")
        else:
            strm_path = os.path.join(target_path, file_base_name + ".strm")

        if not os.path.exists(os.path.dirname(strm_path)):
            os.makedirs(os.path.dirname(strm_path), exist_ok=True)
        # 检查文件是否存在，文件不存在或者覆写为True时写入文件
        if not os.path.exists(strm_path) or my_utils.get_config_val(
            "overwrite", job_id, default_val=False
        ):
            with open(strm_path, "w", encoding="utf-8") as f:
                f.write(video_url)
            print(strm_path)
        cloud_files.add(strm_path)
    elif file_extension in image_extensions and should_download_file("image", job_id):
        download_with_log("图片", target_path, file_info, job_id)
    elif file_extension in subtitle_extensions and should_download_file(
        "subtitle", job_id
    ):
        download_with_log("字幕", target_path, file_info, job_id)
    elif file_extension == ".nfo" and should_download_file("nfo", job_id):
        download_with_log("nfo", target_path, file_info, job_id)


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


def clean_expired_cache():
    """清理过期缓存项"""
    clean_download_url_cache()
    # 心跳检测
    if "JobList" in my_utils.config:
        # 遍历 JobList 中的每个任务
        for job in my_utils.config["JobList"]:
            job_id = job["id"]
            heartbeat(job_id)


def job():
    # 确保使用正确时区
    now = datetime.now(pytz.timezone("Asia/Shanghai"))
    print(f"任务执行时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始执行定时任务")
    # 加载最新config配置
    config = my_utils.load_config()
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
            clean_local_files(my_utils.get_config_val("targetDir", job_id=job_id))
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 定时任务执行完成")


async def run_scheduler():
    """
    运行定时任务调度器
    """
    # 开启即运行
    if my_utils.get_config_val("runningOnStart", default_val=False):
        job()
    while True:
        schedule.run_pending()
        # 清理过期缓存
        clean_expired_cache()
        await asyncio.sleep(150)


async def main():
    """
    主函数，同时启动API服务和定时任务
    """
    print("123strm v1.5 已启动...", flush=True)
    my_utils.load_config()
    if my_utils.config is not None:
        print("config加载成功")
    else:
        # 抛出一个自定义异常，这里以 ValueError 为例
        raise ValueError("config加载失败，程序执行异常")
    # 计算下次执行时间
    cron = croniter(
        my_utils.get_config_val(key="cron", default_val="0 1 * * *"), datetime.now()
    )
    next_time = cron.get_next(datetime)
    print(f"下次执行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
    schedule.every().day.at(next_time.strftime("%H:%M")).do(job)
    server = uvicorn.Server(
        config=uvicorn.Config(app=local302Api, host="0.0.0.0", port=1236)
    )
    await asyncio.gather(server.serve(), run_scheduler())


if __name__ == "__main__":
    asyncio.run(main())
