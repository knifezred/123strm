"""
配置管理工具模块
包含配置加载和读取相关功能
"""

from app import logger
import json
import yaml
import os
import requests
import time
import schedule
import threading
from croniter import croniter
from datetime import datetime
from typing import Any, Optional


config = None
# 开发时使用 config/ 相对定位
config_folder = "/config/"


def load_config() -> dict:
    """
    从config.yml加载配置信息
    返回: 包含配置信息的字典
    """
    global config
    config_path = os.path.join(config_folder, "config.yml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def get_config_val(
    key: str, job_id: Optional[str] = None, default_val: Optional[Any] = None
) -> Any:
    """
    获取配置值
    :param key: 配置项key
    :param job_id: 任务ID，可选
    :return: 配置项value
    :raises ValueError: 当配置项不存在时抛出
    """
    global config
    if not config:
        config = load_config()

    if job_id is not None:
        for job in config["job_list"]:
            if job is None:
                logger.info("job任务配置异常")

            if job is not None and job["id"] == job_id:
                if job.get(key) is not None:
                    return job.get(key)

    if key not in config and default_val is not None:
        return default_val
    elif key not in config and default_val is None:
        logger.warning(f"配置项 {key} 不存在, 且不存在默认值")

    return config[key]


def is_filetype_downloadable(file_type, job_id):
    """
    判断是否应该下载指定类型的文件
    :param file_type: 文件类型配置名
    :return: bool 是否下载
    """
    return (
        get_config_val(file_type, job_id, default_val=False)
        and get_config_val("flatten_mode", job_id, default_val=False) == False
    )


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
            logger.info(f"下载成功: {save_path}")
            return True
        except requests.RequestException as e:
            retry_count += 1
            if retry_count == max_retries:
                logger.info(f"下载文件失败，已达最大重试次数{max_retries}: {e}")
                return False
            logger.info(f"下载失败: {save_path}, 第{retry_count}次重试, 错误信息: {e}")
            time.sleep(1)  # 重试前等待1秒


def save_file_ids(cloud_files, job_id=None):
    """
    将文件路径和ID记录到config文件夹下的文件中
    :param cloud_files: 要记录的字典，键为文件路径，值为文件ID
    :param job_id: 可选的任务ID，用于分组存储
    """
    file_path = os.path.join(config_folder, "cache_files.json")

    # 如果文件不存在则创建
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

    # 读取现有数据
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 更新数据
    if job_id:
        if job_id not in data:
            data[job_id] = {}
        data[job_id].update(cloud_files)
    else:
        if "global" not in data:
            data["global"] = {}
        data["global"].update(cloud_files)

    # 写回文件
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    logger.info(f"已记录{len(cloud_files)}个文件路径和ID")


def get_file_id(file_path, job_id=None):
    """
    根据文件路径获取文件ID
    :param file_path: 文件路径
    :return: 文件ID
    """
    cache_file_path = os.path.join(config_folder, "cache_files.json")
    # 从cache_files.json读取所有文件信息
    with open(cache_file_path, "r") as f:
        cache_data = json.load(f)
        # 遍历查找文件路径
        if file_path in cache_data:
            return cache_data[file_path]
    return None
