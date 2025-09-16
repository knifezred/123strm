"""
API连接管理模块
包含HTTPS连接池实现
"""

import http.client
import json
import yaml
import os
import time
import shutil
import threading
import urllib.parse
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, FileResponse


from app.utils import (
    get_config_val,
    config_folder,
    load_config,
    calculate_chunk_md5,
    read_file_chunks,
)

from app import logger


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

# 每个job_id对应的缓存token设置
global_job_cache_tokens = {}

# 默认缓存状态
default_use_cache_token = True


def http_123_request(job_id, payload="", path="", method="GET"):
    """
    123云盘API请求封装
    :param job_id: 任务ID
    :param payload: 请求体数据
    :param path: 请求路径
    :param method: HTTP方法
    :return: 响应数据
    """
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
            method,
            path,
            payload,
            headers,
        )
        res = conn.getresponse()
        data = res.read()
        response = json.loads(data.decode("utf-8"))
        if response["code"] != 0:
            if response["code"] == 401:
                global_job_cache_tokens[job_id] = False
            else:
                # 操作频繁，暂停30秒
                time.sleep(30)
            logger.error(job_id + "\n" + response["message"])
            raise HTTPException(
                status_code=response["code"], detail=response["message"]
            )
        return response
    finally:
        if conn is not None:
            api_pool.release_connection(conn)


def auth_access_token(client_id, client_secret):
    """
    获取123云盘API访问令牌
    :param client_id: 123云盘应用ID
    :param client_secret: 123云盘应用密钥
    :return: 访问令牌字典
    """
    conn = None
    try:
        conn = api_pool.get_connection()
        payload = json.dumps({"client_id": client_id, "client_secret": client_secret})
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
    client_id = get_config_val("client_id", job_id=job_id)
    # 根据client_id生成缓存文件名
    cache_file = os.path.join(config_folder, f"token_cache_{client_id}.json")
    # 尝试从缓存文件读取token信息
    # 检查job_id是否在缓存设置中，不在则使用默认值
    use_cache = global_job_cache_tokens.get(job_id, default_use_cache_token)
    if use_cache:
        try:
            current_time = datetime.now().replace(tzinfo=None)
            with open(cache_file, "r") as f:
                cache = json.load(f)
            expire_time = datetime.fromisoformat(cache["expiredAt"]).replace(
                tzinfo=None
            )
            if expire_time > current_time + timedelta(days=1):
                return cache["accessToken"]
            else:
                # 提前1天清除缓存
                if os.path.exists(cache_file):
                    os.remove(cache_file)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
    # 获取新token
    client_secret = get_config_val("client_secret", job_id=job_id)
    token_response = auth_access_token(client_id, client_secret)
    # 保存token到缓存文件
    try:
        with open(cache_file, "w") as f:
            json.dump(
                {
                    "accessToken": token_response["data"]["accessToken"],
                    "expiredAt": token_response["data"]["expiredAt"],
                },
                f,
            )
    except IOError as e:
        logger.error(f"写入缓存文件 {cache_file} 失败: {str(e)}")
        # 文件操作失败时标记为不使用缓存，强制下次获取新token
        global_job_cache_tokens[job_id] = False
    # 设置该job_id的缓存状态为True
    global_job_cache_tokens[job_id] = True
    return token_response["data"]["accessToken"]


def heartbeat(job_id):
    """
    心跳检测
    :param job_id: 任务ID
    """
    try:
        heartbeat_url = "heartbeat_" + job_id
        heartbeat_cache = download_url_cache.get(heartbeat_url)
        if heartbeat_cache is None:
            jsonData = http_123_request(
                job_id, path="/api/v2/file/list?parentFileId=0&limit=1"
            )
            download_url_cache[heartbeat_url] = {
                "url": heartbeat_url,
                "expire_time": time.time()
                + get_config_val("cache_expire_time", job_id, default_val=300),
            }
            if jsonData["code"] != 0:
                # 抛出异常以便调用者处理
                raise HTTPException(
                    status_code=jsonData["code"], detail=jsonData["message"]
                )
    except Exception as e:
        if isinstance(e, HTTPException):
            global_job_cache_tokens[job_id] = False
            logger.warning(f"{job_id} 心跳检测失败, 禁用缓存文件。error:{e}")


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
        response = http_123_request(
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
            logger.info(f"获取文件列表失败: {parent_file_id}, 重试{max_retries}...")
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
        response = http_123_request(job_id, path=f"/api/v1/file/detail?fileID={fileId}")
        return response["data"]["filename"]
    except:
        if max_retries < 3:
            time.sleep(5)
            max_retries = max_retries + 1
            logger.info(f"获取文件信息失败: {fileId}, 重试{max_retries}...")
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
        response = http_123_request(
            job_id, path=f"/api/v1/file/download_info?fileId={file_id}"
        )
        return response["data"]["downloadUrl"]
    except:
        if max_retries < 3:
            time.sleep(5)
            max_retries = max_retries + 1
            logger.info(f"获取文件下载信息失败: {file_id}, 重试{max_retries}...")
            return get_file_download_info(file_id, job_id, max_retries)
        else:
            logger.info(f"获取文件下载信息失败: {file_id}")


def delete_file_by_id(file_id, job_id):
    """
    删除文件
    :param file_id: 文件ID
    :param job_id: 任务ID
    :return: 删除结果JSON数据
    """
    # qps设置为1
    time.sleep(1)
    try:
        payload = json.dumps({"fileIDs": [file_id]})
        response = http_123_request(
            job_id, payload=payload, path=f"/api/v1/file/trash", method="POST"
        )
        if response["code"] == 0:
            logger.info(f"删除云盘文件成功: {job_id} - {file_id}")
    except:
        logger.info(
            f"删除云盘文件失败: {job_id} - {file_id} -{response["code"]}: {response["message"]}"
        )

# 创建文件上传信息
def upload_file_v2_create(parent_file_id,filename,etag,size,duplicate,containDir, job_id, max_retries=3):
    """
    创建文件上传信息
    :param parent_file_id: 父文件夹ID
    :param filename: 文件名
    :param etag: 文件ETAG
    :param size: 文件大小
    :param duplicate: 是否允许重复
    :param containDir: 是否包含目录
    :param job_id: 任务ID
    :return: 上传信息JSON数据
    """
    try:
        payload = json.dumps({
            "parentFileID": parent_file_id,
            "filename": filename,
            "etag": etag,
            "size": size,
            "duplicate": duplicate,
            "containDir": containDir
        })
        response = http_123_request(
            job_id, payload=payload, path=f"/upload/v2/file/create", method="POST"
        )
        return response
    except:
        if max_retries < 3:
            time.sleep(5)
            max_retries = max_retries + 1
            logger.info(f"创建文件上传信息失败: {filename}, 重试{max_retries}...")
            return upload_file_v2_create(parent_file_id,filename,etag,size,duplicate,containDir, job_id, max_retries)
        else:
            logger.info(f"创建文件上传信息失败: {filename}")



def upload_file_v2_slice(file_name: str, slice_no: str, chunk: bytes, upload_id: str,url: str, job_id: str):
    """上传文件分片到123云盘
    
    Args:
        file_path: 文件路径
        file_name: 文件名
        slice_no: 分片序号
        chunk: 分片数据
        upload_id: 上传ID
        job_id: 任务ID
    
    Returns:
        上传响应JSON数据
    """
    
    # 获取访问令牌
    access_token = get_access_token(job_id)
    
    # 计算分片MD5
    slice_md5 = calculate_chunk_md5(chunk)
    
    # 准备请求头
    headers = {
        "Platform": "open_platform",
        "Authorization": f"Bearer {access_token}",
    }
    
    # 记录请求信息用于调试
    logger.info(f"分片大小: {len(chunk)} bytes, MD5: {slice_md5}")
    
    # 准备请求数据 - 尝试调整字段名以匹配服务器期望的格式
    files = {
        'slice': (os.path.basename(file_name), chunk, 'application/octet-stream')
    }
    data = {
        "preuploadID": upload_id,
        "sliceNo": slice_no,
        "sliceMD5": slice_md5,
        "sliceSize": str(len(chunk))
    }
    
    # 发送请求，增加超时设置
    try:
        response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
    except requests.exceptions.RequestException as e:
        logger.error(f"请求异常: {str(e)}")
        return {'code': 999, 'message': f'Request failed: {str(e)}'}
    # 错误处理：检查响应是否有效
    try:
        # 首先检查响应状态码
        response.raise_for_status()
        # 尝试解析JSON响应
        if response.text.strip():
            return response.json()
        else:
            # 响应内容为空
            return {'code': 1, 'message': 'Empty response from server'}
    except requests.exceptions.HTTPError as e:
        # HTTP错误
        return {'code': response.status_code, 'message': f'HTTP Error: {str(e)}'}
    except ValueError:
        # JSON解析错误
        return {'code': 2, 'message': f'Invalid JSON response: {response.text[:100]}...'}

# 完整的分片上传流程
def complete_multipart_upload(file_path: str, file_name: str,upload_info: dict, job_id: str):
    """执行完整的分片上传流程
    
    Args:
        file_path: 文件路径
        file_name: 文件名
        upload_info: 上传信息字典，包含preuploadID等
        job_id: 任务ID
    
    Returns:
        最终上传结果
    """
    # 参数验证和错误处理
    try:
        # 获取必要的上传信息
        preupload_id = upload_info.get('preuploadID')
        if not preupload_id:
            return {'code': 3, 'message': 'Missing preuploadID in upload_info'}
        
        # 获取分片大小，默认为4MB
        slice_size = upload_info.get('sliceSize', 4 * 1024 * 1024)
        try:
            slice_size = int(slice_size)
        except (ValueError, TypeError):
            logger.warning(f"Invalid sliceSize: {slice_size}, using default 4MB")
            slice_size = 4 * 1024 * 1024
        
        # 获取上传服务器地址
        servers = upload_info.get('servers', [])
        if not servers:
            return {'code': 4, 'message': 'No upload servers available'}
        
        upload_server = servers[0]
        
        # 读取文件分片并逐个上传
        for i, chunk in enumerate(read_file_chunks(file_path, chunk_size=slice_size)):
            slice_no = str(i + 1)  # 分片序号从1开始
            url = f"{upload_server}/upload/v2/file/slice"
            
            # 记录上传前日志
            logger.info(f"开始上传分片 {slice_no}，大小: {len(chunk)} bytes")
            
            response = upload_file_v2_slice(
                file_name=file_name,
                slice_no=slice_no,
                chunk=chunk,
                upload_id=preupload_id,
                url=url,
                job_id=job_id
            )
            
            # 检查上传是否成功
            if response.get('code') != 0:
                error_msg = response.get('message', 'Unknown error')
                logger.error(f"分片 {slice_no} 上传失败: {error_msg}")
                return {
                    'code': response.get('code', 5),
                    'message': f"分片 {slice_no} 上传失败: {error_msg}"
                }
            
        # 所有分片上传完成
        logger.info(f"文件 {file_name} 所有分片上传成功")
        return {
            'code': 0,
            'message': '所有分片上传成功',
            'data': {
                'upload_id': preupload_id
            }
        }
        
    except Exception as e:
        # 捕获所有其他异常
        logger.error(f"分片上传过程中发生错误: {str(e)}")
        return {
            'code': 999,
            'message': f"Upload process failed: {str(e)}"
        }
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
    return FileResponse("app/public/index.html")


@local302Api.get("/get_config")
async def get_config():
    return load_config()


@local302Api.post("/save_config")
async def save_config(update_config: dict):
    """
    保存配置
    :param update_config: 更新的配置数据(dict格式)
    :return: 保存结果
    """
    try:
        # 备份现有配置
        backup_path = os.path.join(config_folder, "config.bak.yml")
        shutil.copyfile(os.path.join(config_folder, "config.yml"), backup_path)
        with open(
            os.path.join(config_folder, "config.yml"), "w", encoding="utf-8"
        ) as f:
            yaml.dump(update_config, f, allow_unicode=True)
        load_config()
        return {"message": "配置已保存"}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"配置保存失败: {str(e)}")


@local302Api.get("/get_file_url/{file_id}/{job_id}")
async def get_file_url(file_id: int, job_id: str):
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
        logger.info(f"从缓存获取302跳转URL: {cache_item['url']}")
        return RedirectResponse(cache_item["url"], 302)

    # 获取下载URL并存入缓存
    try:
        job_id = urllib.parse.unquote(job_id)
        download_url = get_file_download_info(file_id, job_id)
        if not download_url:
            logger.info(f"未找到文件: {file_id}")

        # 存储URL和过期时间
        download_url_cache[file_id] = {
            "url": download_url,
            "expire_time": time.time()
            + get_config_val("cache_expire_time", job_id, default_val=300),
        }
        logger.info(f"302跳转成功: {download_url}")

        return RedirectResponse(download_url, 302)
    except Exception as e:
        logger.info(f"获取文件下载链接失败: {str(e)}")

    logger.info(f"未找到文件: {file_id}")
