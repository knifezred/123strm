"""
API连接管理模块
包含HTTPS连接池实现
"""

import http.client
import json
import yaml
import os
import requests
import time
import schedule
import threading
from croniter import croniter
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi import Query
from fastapi.responses import RedirectResponse

from app.utils import Utils

# 添加时区设置
import pytz

my_utils = Utils()


class ConnectionPool:
    """
    HTTPS连接池管理类
    属性:
        host: API主机地址
        max_size: 最大连接数
        idle_timeout: 空闲超时时间(秒)
    """

    def __init__(self, host: str, max_size: int = 4, idle_timeout: int = 60):
        """
        初始化连接池
        :param host: API主机地址
        :param max_size: 最大连接数
        :param idle_timeout: 空闲超时时间(秒)
        """
        self.host = host
        self.max_size = max_size
        self.idle_timeout = idle_timeout
        self._pool = []
        self._lock = threading.Lock()

    def get_connection(self) -> http.client.HTTPSConnection:
        """
        从池中获取可用连接
        返回: 只返回HTTPSConnection对象，不返回元组
        """
        with self._lock:
            self._clean_expired_connections()

            if self._pool:
                conn, _ = self._pool.pop()  # 只返回连接对象
                return conn

            if len(self._pool) < self.max_size:
                return http.client.HTTPSConnection(self.host)

            raise RuntimeError("连接池已满")

    def release_connection(self, conn: http.client.HTTPSConnection) -> None:
        """
        释放连接回池
        :param conn: 要释放的连接
        """
        with self._lock:
            if len(self._pool) < self.max_size:
                self._pool.append((conn, time.time()))
            else:
                conn.close()

    def _clean_expired_connections(self) -> None:
        """清理过期连接"""
        current_time = time.time()
        self._pool = [
            (conn, ts)
            for conn, ts in self._pool
            if current_time - ts < self.idle_timeout
        ]


# 全局连接池实例
api_pool = ConnectionPool("open-api.123pan.com")


def http_get_request(job_id, payload="", path=""):
    conn = None
    try:
        access_token = get_access_token(job_id)
        headers = {
            "Content-Type": "application/json",
            "Platform": "open_platform",
            "Authorization": f"Bearer {access_token}",
        }
        conn = api_pool.get_connection()
        if not isinstance(conn, http.client.HTTPConnection):
            raise ValueError("Invalid connection type returned from pool")

        conn.request(
            "GET",
            path,
            payload,
            headers,
        )
        res = conn.getresponse()
        data = res.read()
        response = json.loads(data.decode("utf-8"))
        if response["code"] != 0:
            print(job_id + " " + path + "\n" + response["message"])
            raise HTTPException(
                status_code=response["code"], detail=response["message"]
            )
        return response
    finally:
        if conn is not None:
            api_pool.release_connection(conn)


def auth_access_token(clientId, clientSecret):
    """
    获取123云盘API访问令牌
    :param clientId: 123云盘应用ID
    :param clientSecret: 123云盘应用密钥
    :return: 访问令牌字典
    """
    conn = None
    try:
        conn = api_pool.get_connection()
        payload = json.dumps({"clientID": clientId, "clientSecret": clientSecret})
        headers = {"Platform": "open_platform", "Content-Type": "application/json"}
        conn.request("POST", "/api/v1/access_token", payload, headers)
        res = conn.getresponse()
        data = res.read()
        return json.loads(data.decode("utf-8"))
    finally:
        if conn is not None:
            api_pool.release_connection(conn)


def get_access_token(job_id):
    """
    获取123云盘API访问令牌
    优先使用本地缓存，根据过期时间判断是否需要重新获取（提前一天清除缓存并返回最新token）
    :return: accessToken字符串
    """
    clientId = my_utils.get_config_val("clientID", job_id=job_id)
    # 根据clientID生成缓存文件名
    cache_file = os.path.join(my_utils.config_folder, f"token_cache_{clientId}.json")
    # 尝试从缓存文件读取token信息
    try:
        current_time = datetime.now().replace(tzinfo=None)
        with open(cache_file, "r") as f:
            cache = json.load(f)
        expire_time = datetime.fromisoformat(cache["expiredAt"]).replace(tzinfo=None)
        if expire_time > current_time + timedelta(days=1):
            return cache["accessToken"]
        else:
            # 提前1天清除缓存
            if os.path.exists(cache_file):
                os.remove(cache_file)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    # 获取新token
    clientSecret = my_utils.get_config_val("clientSecret", job_id)
    token_response = auth_access_token(clientId, clientSecret)
    # 保存token到缓存文件
    with open(cache_file, "w") as f:
        json.dump(
            {
                "accessToken": token_response["data"]["accessToken"],
                "expiredAt": token_response["data"]["expiredAt"],
            },
            f,
        )
    return token_response["data"]["accessToken"]


def heartbeat(job_id):
    """
    心跳检测
    :param job_id: 任务ID
    """
    try:
        jsonData = http_get_request(
            job_id, path="/api/v2/file/list?parentFileId=0&limit=1"
        )
        if jsonData["code"] != 0:
            print("心跳检测失败，清除缓存文件")
            my_utils.clean_local_access_token(job_id)
    except:
        print("心跳检测异常，清除缓存文件")
        my_utils.clean_local_access_token(job_id)


def get_file_list(job_id, parent_file_id=0, limit=100, lastFileId=None, max_retries=0):
    """
    获取文件列表
    :param parent_file_id: 父文件夹ID，默认为0（根目录）
    :param limit: 返回的文件数量限制，默认为100
    :param access_token: 访问令牌，如果未提供则自动获取
    :return: 文件列表JSON数据
    """
    try:
        start_time = time.time()
        response = http_get_request(
            job_id,
            path=f"/api/v2/file/list?parentFileId={parent_file_id}&limit={limit}"
            + (f"&lastFileId={lastFileId}" if lastFileId else ""),
        )
        elapsed = time.time() - start_time
        if elapsed < 0.34:
            time.sleep(0.34 - elapsed)
        return response
    except:
        if max_retries < 3:
            time.sleep(5)
            max_retries = max_retries + 1
            print(f"获取文件列表失败: {parent_file_id}, 重试{max_retries}...")
            return get_file_list(
                job_id,
                parent_file_id=parent_file_id,
                limit=limit,
                lastFileId=lastFileId,
                max_retries=max_retries,
            )
        else:
            raise Exception(f"获取文件列表失败: {parent_file_id}")


def get_file_info(fileId, job_id, max_retries=0):
    """
    获取文件信息
    :param fileId: 文件ID
    :return: 文件信息JSON数据
    """

    try:
        response = http_get_request(job_id, path=f"/api/v1/file/detail?fileID={fileId}")
        return response["data"]["filename"]
    except:
        if max_retries < 3:
            time.sleep(5)
            max_retries = max_retries + 1
            print(f"获取文件信息失败: {fileId}, 重试{max_retries}...")
            return get_file_info(fileId, job_id, max_retries)
        else:
            raise Exception(f"获取文件信息失败: {fileId}")


def get_file_download_info(file_id, job_id, max_retries=0):
    """
    获取文件下载信息
    :param file_id: 文件ID
    :param access_token: 访问令牌，如果未提供则自动获取
    :return: 下载信息JSON数据
    """
    try:
        response = http_get_request(
            job_id, path=f"/api/v1/file/download_info?fileId={file_id}"
        )
        return response["data"]["downloadUrl"]
    except:
        if max_retries < 3:
            time.sleep(5)
            max_retries = max_retries + 1
            print(f"获取文件下载信息失败: {file_id}, 重试{max_retries}...")
            return get_file_download_info(file_id, job_id, max_retries)
        else:
            print(f"获取文件下载信息失败: {file_id}")


###############API#############

# 文件下载URL缓存 (存储格式: {file_id: {'url': url, 'expire_time': timestamp}})
download_url_cache = {}


def clean_download_url_cache():
    """清理过期302链接缓存项"""
    for file_id, item in list(download_url_cache.items()):
        if time.time() > item["expire_time"]:
            del download_url_cache[file_id]


# 启动api
local302Api = FastAPI()


@local302Api.get("/")
async def index():
    return "123strm已启动"


@local302Api.get("/get_file_url/{file_id}")
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
    cache_item = download_url_cache.get(file_id)
    if cache_item is not None:
        print(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 从缓存获取302跳转URL: {cache_item['url']}"
        )
        return RedirectResponse(cache_item["url"], 302)

    # 获取下载URL并存入缓存
    try:
        download_url = get_file_download_info(file_id, job_id)
        if not download_url:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 未找到文件: {file_id}")

        # 存储URL和过期时间
        download_url_cache[file_id] = {
            "url": download_url,
            "expire_time": time.time()
            + my_utils.get_config_val("cacheExpireTime", job_id, default_val=300),
        }
        print(f"[{time.strftime('%m-%d %H:%M:%S')}] 302跳转成功: {download_url}")

        return RedirectResponse(download_url, 302)
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 获取文件下载链接失败: {str(e)}")

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 未找到文件: {file_id}")
