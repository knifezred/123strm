"""
工具函数模块
包含同步和异步工具函数，以及配置管理相关功能
"""

from . import logger
import json
import yaml
import os
import requests
import time
import hashlib
import asyncio
import aiofiles
import aiohttp
from typing import Any, Optional, Generator, Dict, List, Union

from .config_manager import config_manager


# ===== 异步文件操作函数 =====
async def async_file_exists(file_path: str) -> bool:
    """
    异步检查文件或目录是否存在

    Args:
        file_path: 要检查的文件或目录路径

    Returns:
        bool: 文件或目录是否存在
    """
    loop = asyncio.get_running_loop()
    try:
        # 使用loop.run_in_executor来异步执行文件存在检查
        return await loop.run_in_executor(None, os.path.exists, file_path)
    except Exception as e:
        logger.error(f"检查文件/目录是否存在失败: {file_path}, 错误: {str(e)}")
        return False


async def async_is_dir(path: str) -> bool:
    """
    异步检查路径是否为目录

    Args:
        path: 要检查的路径

    Returns:
        bool: 路径是否为目录
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, os.path.isdir, path)
    except Exception as e:
        logger.error(f"检查路径是否为目录失败: {path}, 错误: {str(e)}")
        return False


async def async_makedirs(path: str, exist_ok: bool = True) -> None:
    """
    异步创建目录

    Args:
        path: 要创建的目录路径
        exist_ok: 如果目录已存在是否报错
    """
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, os.makedirs, path, 511, exist_ok)
    except Exception as e:
        logger.error(f"创建目录失败: {path}, 错误: {str(e)}")


async def async_remove_file(file_path: str) -> None:
    """
    异步删除文件

    Args:
        file_path: 要删除的文件路径
    """
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, os.remove, file_path)
        logger.info(f"已删除文件: {file_path}")
    except Exception as e:
        logger.error(f"删除文件失败: {file_path}, 错误: {str(e)}")
        raise


async def async_remove_dir(dir_path: str) -> None:
    """
    异步删除目录

    Args:
        dir_path: 要删除的目录路径
    """
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, os.rmdir, dir_path)
        logger.info(f"已删除目录: {dir_path}")
    except Exception as e:
        logger.error(f"删除目录失败: {dir_path}, 错误: {str(e)}")
        raise


async def async_listdir(path: str) -> List[str]:
    """
    异步列出目录内容

    Args:
        path: 要列出内容的目录路径

    Returns:
        List[str]: 目录中的文件和子目录列表
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, os.listdir, path)
    except Exception as e:
        logger.error(f"读取目录内容失败: {path}, 错误: {str(e)}")
        return []


async def async_is_directory_empty(dir_path: str) -> bool:
    """
    异步检查目录是否为空

    Args:
        dir_path: 要检查的目录路径

    Returns:
        bool: 目录是否为空
    """
    try:
        entries = await async_listdir(dir_path)
        return len(entries) == 0
    except Exception:
        return False


async def async_read_file(file_path: str, encoding: str = "utf-8") -> str:
    """
    异步读取文件内容

    Args:
        file_path: 要读取的文件路径
        encoding: 文件编码

    Returns:
        str: 文件内容
    """
    try:
        async with aiofiles.open(file_path, "r", encoding=encoding) as f:
            return await f.read()
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, 错误: {str(e)}")
        raise


async def async_write_file(
    file_path: str, content: str, encoding: str = "utf-8"
) -> None:
    """
    异步写入文件内容

    Args:
        file_path: 要写入的文件路径
        content: 要写入的内容
        encoding: 文件编码
    """
    try:
        # 确保目录存在
        dir_path = os.path.dirname(file_path)
        if dir_path and not await async_file_exists(dir_path):
            await async_makedirs(dir_path)

        async with aiofiles.open(file_path, "w", encoding=encoding) as f:
            await f.write(content)
    except Exception as e:
        logger.error(f"写入文件失败: {file_path}, 错误: {str(e)}")
        raise


async def async_read_json(file_path: str) -> Dict:
    """
    异步读取JSON文件

    Args:
        file_path: 要读取的JSON文件路径

    Returns:
        Dict: 解析后的JSON数据
    """
    try:
        content = await async_read_file(file_path)
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"解析JSON文件失败: {file_path}, 错误: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"读取JSON文件失败: {file_path}, 错误: {str(e)}")
        raise


async def async_write_json(file_path: str, data: Dict, indent: int = 4) -> None:
    """
    异步写入JSON文件

    Args:
        file_path: 要写入的JSON文件路径
        data: 要写入的数据
        indent: 缩进空格数
    """
    try:
        content = json.dumps(data, indent=indent, ensure_ascii=False)
        await async_write_file(file_path, content)
    except Exception as e:
        logger.error(f"写入JSON文件失败: {file_path}, 错误: {str(e)}")
        raise


async def async_download_file(url: str, save_path: str, chunk_size: int = 8192) -> bool:
    """
    异步下载文件

    Args:
        url: 文件的下载URL
        save_path: 文件保存的本地路径
        chunk_size: 下载分块大小

    Returns:
        bool: 下载是否成功
    """
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            # 确保目录存在
            dir_path = os.path.dirname(save_path)
            if dir_path and not await async_file_exists(dir_path):
                await async_makedirs(dir_path)

            # 使用aiohttp进行异步下载
            async with aiohttp.ClientSession() as session:
                # 使用现代aiohttp API处理流式响应
                async with session.get(url, timeout=None) as response:
                    response.raise_for_status()
                    async with aiofiles.open(save_path, "wb") as f:
                        # 直接读取内容而不是使用iter_chunked
                        content = await response.read()
                        await f.write(content)
            logger.info(f"下载成功: {save_path}")
            return True
        except aiohttp.ClientError as e:
            retry_count += 1
            if retry_count == max_retries:
                logger.info(f"下载文件失败，已达最大重试次数{max_retries}: {e}")
                return False
            logger.info(f"下载失败: {save_path}, 第{retry_count}次重试, 错误信息: {e}")
            await asyncio.sleep(1)  # 重试前等待1秒


async def async_read_file_chunks_aio(
    file_path: str, chunk_size: int = 8 * 1024 * 1024
) -> Generator[bytes, None, None]:
    """
    异步读取文件的分片数据（使用aiofiles实现）

    Args:
        file_path: 文件路径
        chunk_size: 分片大小，默认8MB

    Yields:
        bytes: 文件分片数据
    """
    try:
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    except Exception as e:
        logger.error(f"读取文件分片失败: {file_path}, 错误: {str(e)}")
        raise


async def async_calculate_file_md5(
    file_path: str, chunk_size: int = 8 * 1024 * 1024
) -> str:
    """
    异步计算文件的MD5值

    Args:
        file_path: 文件路径
        chunk_size: 读取分块大小，默认8MB

    Returns:
        str: 文件的MD5哈希值
    """
    md5_hash = hashlib.md5()

    try:
        # 获取文件大小
        loop = asyncio.get_running_loop()
        total_size = await loop.run_in_executor(None, os.path.getsize, file_path)
        processed_size = 0
        last_log_percentage = -1

        # 只对较大文件（大于100MB）显示进度
        show_progress = total_size > 100 * 1024 * 1024  # 100MB

        # 异步读取文件并计算MD5
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                md5_hash.update(chunk)
                processed_size += len(chunk)

                # 计算进度百分比并记录日志
                if show_progress:
                    percentage = int((processed_size / total_size) * 100)
                    if percentage % 2 == 0 and percentage != last_log_percentage:
                        logger.info(
                            f"文件MD5计算进度: {os.path.basename(file_path)} - {percentage}% ({processed_size // (1024*1024)}MB/{total_size // (1024*1024)}MB)"
                        )
                        last_log_percentage = percentage

        return md5_hash.hexdigest()
    except Exception as e:
        logger.error(f"计算文件MD5失败: {file_path}, 错误: {str(e)}")
        raise


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


# 异步读取文件分片
async def async_read_file_chunks(
    file_path: str, chunk_size: int = 8 * 1024 * 1024
) -> Generator[bytes, None, None]:
    """异步读取文件的分片数据

    Args:
        file_path: 文件路径
        chunk_size: 分片大小，默认8MB

    Yields:
        文件分片数据
    """
    if not await async_file_exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 使用aiofiles实现更高效的异步读取
    try:
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    except Exception as e:
        logger.error(f"读取文件分片失败: {file_path}, 错误: {str(e)}")
        raise


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


async def async_download_file(url, save_path):
    """
    异步根据指定的URL下载文件并保存到指定路径。
    :param url: 文件的下载URL
    :param save_path: 文件保存的本地路径
    :return: 若下载成功返回True，否则返回False
    """
    loop = asyncio.get_running_loop()
    # 使用线程池执行同步下载
    result = await loop.run_in_executor(None, lambda: download_file(url, save_path))
    return result


async def async_save_file_ids(cloud_files, job_id):
    """
    异步将文件路径和ID记录到config文件夹下的文件中
    :param cloud_files: 要记录的字典，键为文件路径，值为文件ID
    :param job_id: 任务ID，用于分组存储
    """
    logger.info(
        f"开始异步记录{len(cloud_files)}个文件路径和ID到任务ID为{job_id}的缓存文件"
    )
    file_path = os.path.join(config_manager.get_config_folder(), "cache_files.json")
    logger.debug(f"缓存文件路径: {file_path}")

    # 如果文件不存在则创建
    if not await async_file_exists(file_path):
        await async_write_file(file_path, "{}", encoding="utf-8")

    # 读取现有数据
    try:
        content = await async_read_file(file_path, encoding="utf-8")
        data = json.loads(content)
    except Exception:
        data = {}
    logger.debug(f"当前缓存数据: {data}")
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
    await async_write_file(
        file_path, json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8"
    )

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


async def async_get_file_id(file_path, job_id=None):
    """
    异步根据文件路径获取文件ID
    :param file_path: 文件路径
    :return: 文件ID
    """
    cache_file_path = os.path.join(
        config_manager.get_config_folder(), "cache_files.json"
    )

    # 检查文件是否存在
    if not await async_file_exists(cache_file_path):
        return None

    # 异步从cache_files.json读取所有文件信息
    try:
        content = await async_read_file(cache_file_path, "r", encoding="utf-8")
        cache_data = json.loads(content)
        # 遍历查找文件路径
        if file_path in cache_data:
            return cache_data[file_path]
    except Exception as e:
        logger.error(f"读取文件ID缓存失败: {str(e)}")
    return None
