"""
配置管理工具模块
包含配置加载和读取相关功能
"""

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


class Utils:
    """
    配置管理类
    属性:
        config: 全局配置字典
        config_folder: 配置文件目录
    """

    config = None

    config_folder = "/config/"

    @classmethod
    def load_config(cls) -> dict:
        """
        从config.yml加载配置信息
        返回: 包含配置信息的字典
        """
        config_path = os.path.join(cls.config_folder, "config.yml")
        with open(config_path, "r", encoding="utf-8") as f:
            cls.config = yaml.safe_load(f)
        return cls.config

    @classmethod
    def get_config_val(
        cls, key: str, job_id: Optional[str] = None, default_val: Optional[Any] = None
    ) -> Any:
        """
        获取配置值
        :param key: 配置项key
        :param job_id: 任务ID，可选
        :return: 配置项value
        :raises ValueError: 当配置项不存在时抛出
        """
        if not cls.config:
            cls.load_config()

        if job_id is not None:
            for job in cls.config["JobList"]:
                if job is None:
                    print("job任务配置异常")

                if job is not None and job["id"] == job_id:
                    return job.get(key, cls.config.get(key))

        if key not in cls.config and default_val is not None:
            return default_val
        elif key not in cls.config and default_val is None:
            print(f"配置项 {key} 不存在")

        return cls.config[key]

    @classmethod
    def download_file(cls, url, save_path):
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

    @staticmethod
    def clean_local_access_token(job_id):
        """
        清理指定任务的本地缓存访问令牌
        :param job_id: 任务ID
        """
        clientId = Utils.get_config_val("clientID", job_id)
        # 根据clientID生成缓存文件名
        cache_file = os.path.join(Utils.config_folder, f"token_cache_{clientId}.json")
        if os.path.exists(cache_file):
            print("清除失效access_token")
            os.remove(cache_file)


# 全局配置管理器实例
my_utils = Utils()
