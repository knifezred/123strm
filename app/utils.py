"""
配置管理工具模块
包含配置加载和读取相关功能
"""

from . import logger
import json
import yaml
import os
import requests
import time
import hashlib
from typing import Any, Optional, Generator

from .config_manager import config_manager


def convert_byte_size(bytes_size, unit: str = "MB") -> float:
    """
    将字节大小转换为指定单位的值

    Args:
        bytes_size: 字节大小
        unit: 目标单位，支持 'KB', 'MB', 'GB', 'TB' 等，默认 'MB'

    Returns:
        转换后的值
    """
    unit = unit.upper()
    units = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    if unit in units:
        return bytes_size / units[unit]
    return bytes_size


# 读取文件分片
def read_file_chunks(
    file_path: str, chunk_size: int = 8 * 1024 * 1024
) -> Generator[bytes, None, None]:
    """读取文件的分片数据

    Args:
        file_path: 文件路径
        chunk_size: 分片大小，默认8MB

    Yields:
        文件分片数据
    """
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


# 计算文件分片的MD5
def calculate_chunk_md5(chunk: bytes) -> str:
    """计算文件分片的MD5值

    Args:
        chunk: 文件分片数据

    Returns:
        MD5哈希值（16进制字符串）
    """
    md5_hash = hashlib.md5()
    md5_hash.update(chunk)
    return md5_hash.hexdigest()


# 计算整个文件的MD5（分块处理，适合大文件）
def calculate_file_md5(file_path: str, chunk_size: int = 8 * 1024 * 1024) -> str:
    """计算整个文件的MD5值（分块读取，避免内存溢出）

    Args:
        file_path: 文件路径
        chunk_size: 读取分块大小，默认8MB

    Returns:
        文件的MD5哈希值（16进制字符串）
    """
    md5_hash = hashlib.md5()
    total_size = os.path.getsize(file_path)
    processed_size = 0
    last_log_percentage = -1

    # 只对较大文件（大于100MB）显示进度
    show_progress = total_size > 100 * 1024 * 1024  # 100MB

    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            md5_hash.update(chunk)
            processed_size += len(chunk)

            # 计算进度百分比并记录日志（每1%进度或达到100%时记录）
            if show_progress:
                percentage = int((processed_size / total_size) * 100)
                if percentage % 2 == 0 and percentage != last_log_percentage:
                    logger.info(
                        f"文件MD5计算进度: {os.path.basename(file_path)} - {percentage}% ({processed_size // (1024*1024)}MB/{total_size // (1024*1024)}MB)"
                    )
                    last_log_percentage = percentage

    # if show_progress:
    #     logger.info(f"文件MD5计算完成: {os.path.basename(file_path)} - MD5: {md5_hash.hexdigest()}")

    return md5_hash.hexdigest()


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
    file_path = os.path.join(config_manager.get_config_folder(), "cache_files.json")

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
    cache_file_path = os.path.join(
        config_manager.get_config_folder(), "cache_files.json"
    )
    # 从cache_files.json读取所有文件信息
    with open(cache_file_path, "r") as f:
        cache_data = json.load(f)
        # 遍历查找文件路径
        if file_path in cache_data:
            return cache_data[file_path]
    return None
