"""
API连接管理模块
使用aiohttp进行异步API调用
"""

import json
import os
import time
import asyncio
import aiohttp
from datetime import datetime, timedelta

from .config_manager import config_manager
from .utils import calculate_chunk_md5, async_read_json, async_write_json, async_file_exists, async_remove_file, async_read_file_chunks

from . import logger


# 创建全局aiohttp会话管理器
class AsyncSessionManager:
    """
    异步请求会话管理器
    使用aiohttp的ClientSession管理HTTP连接
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._sessions = {}

    async def get_session(self, host=None):
        """
        获取或创建一个异步会话
        :param host: 主机地址，默认为123云盘API
        :return: aiohttp.ClientSession对象
        """
        if host is None:
            host = "https://open-api.123pan.com"

        async with self._lock:
            if host not in self._sessions:
                session = aiohttp.ClientSession()
                # 配置会话参数
                # aiohttp的超时设置在请求时单独设置
                self._sessions[host] = session
            return self._sessions[host]

    async def close_all(self):
        """关闭所有会话"""
        async with self._lock:
            for session in self._sessions.values():
                await session.close()
            self._sessions.clear()


# 全局会话管理器实例
session_manager = AsyncSessionManager()

# 每个job_id对应的缓存token设置
global_job_cache_tokens = {}

# 默认缓存状态
default_use_cache_token = True

# 文件下载URL缓存 (存储格式: {file_id: {'url': url, 'expire_time': timestamp}})
download_url_cache = {}


async def clean_download_url_cache():
    """清理过期302链接缓存项"""
    for file_id, item in list(download_url_cache.items()):
        if time.time() > item["expire_time"]:
            del download_url_cache[file_id]


async def http_123_request(job_id, payload="", path="", method="GET"):
    """
    123云盘API请求封装 - 使用aiohttp实现异步调用
    :param job_id: 任务ID
    :param payload: 请求体数据
    :param path: 请求路径
    :param method: HTTP方法
    :return: 响应数据
    """
    try:
        access_token = await get_access_token(job_id)
        headers = {
            "Content-Type": "application/json",
            "Platform": "open_platform",
            "Authorization": f"Bearer {access_token}",
        }

        # 构建完整URL
        url = f"https://open-api.123pan.com{path}"

        # 获取会话并发送请求
        session = await session_manager.get_session()

        # 根据方法类型发送请求
        if method == "GET":
            params = json.loads(payload) if payload else None
            async with session.get(
                url, headers=headers, params=params, timeout=30
            ) as response:
                response.raise_for_status()
                result = await response.json()
        elif method == "POST":
            async with session.post(
                url, headers=headers, data=payload, timeout=30
            ) as response:
                response.raise_for_status()
                result = await response.json()
        else:
            # 支持其他方法
            async with session.request(
                method, url, headers=headers, data=payload, timeout=30
            ) as response:
                response.raise_for_status()
                result = await response.json()

        # 检查响应状态
        if result["code"] != 0:
            if result["code"] == 401:
                global_job_cache_tokens[job_id] = False
            else:
                # 操作频繁，暂停30秒
                await asyncio.sleep(30)
            error_msg = f"API请求失败(job_id={job_id}): {result['message']}"
            logger.error(error_msg, {"job_id": job_id, "response_code": result["code"]})
            raise ApiError(
                error_msg, error_code=result["code"], details={"job_id": job_id}
            )
        return result
    except aiohttp.ClientError as e:
        error_msg = f"HTTP请求异常(job_id={job_id}): {str(e)}"
        logger.error(error_msg, {"job_id": job_id})
        raise ApiError(error_msg, details={"job_id": job_id})
    except json.JSONDecodeError as e:
        error_msg = f"响应解析失败(job_id={job_id}): {str(e)}"
        logger.error(error_msg, {"job_id": job_id})
        raise ApiError(error_msg, details={"job_id": job_id})


async def auth_access_token(client_id, client_secret):
    """
    获取123云盘API访问令牌 - 使用aiohttp实现异步调用
    :param client_id: 123云盘应用ID
    :param client_secret: 123云盘应用密钥
    :return: 访问令牌字典
    """
    try:
        url = "https://open-api.123pan.com/api/v1/access_token"
        payload = json.dumps({"client_id": client_id, "client_secret": client_secret})
        headers = {"Platform": "open_platform", "Content-Type": "application/json"}

        session = await session_manager.get_session()
        async with session.post(
            url, data=payload, headers=headers, timeout=30
        ) as response:
            response.raise_for_status()
            return await response.json()
    except aiohttp.ClientError as e:
        error_msg = f"获取访问令牌失败: {str(e)}"
        logger.error(error_msg)
        raise ApiError(error_msg)


async def get_access_token(job_id):
    """
    获取123云盘API访问令牌
    优先使用本地缓存，根据过期时间判断是否需要重新获取（提前一天清除缓存并返回最新token）
    :return: accessToken字符串
    """
    client_id = config_manager.get("client_id", job_id=job_id)
    # 根据client_id生成缓存文件名
    cache_file = os.path.join(
        config_manager.get_config_folder(), f"token_cache_{client_id}.json"
    )
    # 尝试从缓存文件读取token信息
    # 检查job_id是否在缓存设置中，不在则使用默认值
    use_cache = global_job_cache_tokens.get(job_id, default_use_cache_token)
    if use_cache:
        try:
            current_time = datetime.now().replace(tzinfo=None)
            # 使用异步文件操作
            cache = await async_read_json(cache_file)
            expire_time = datetime.fromisoformat(cache["expiredAt"]).replace(
                tzinfo=None
            )
            if expire_time > current_time + timedelta(days=1):
                return cache["accessToken"]
            else:
                # 提前1天清除缓存
                if await async_file_exists(cache_file):
                    await async_remove_file(cache_file)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
    # 获取新token
    client_secret = config_manager.get("client_secret", job_id=job_id)
    token_response = await auth_access_token(client_id, client_secret)
    # 保存token到缓存文件
    try:
        await async_write_json(
            cache_file,
            {
                "accessToken": token_response["data"]["accessToken"],
                "expiredAt": token_response["data"]["expiredAt"],
            },
        )
    except IOError as e:
        logger.error(f"写入缓存文件 {cache_file} 失败: {str(e)}")
        # 文件操作失败时标记为不使用缓存，强制下次获取新token
        global_job_cache_tokens[job_id] = False
    # 设置该job_id的缓存状态为True
    global_job_cache_tokens[job_id] = True
    return token_response["data"]["accessToken"]


# 继续修改cloud_api.py，将剩余函数改为异步实现


async def heartbeat(job_id):
    """
    心跳检测 - 异步实现
    :param job_id: 任务ID
    """
    try:
        heartbeat_url = "heartbeat_" + job_id
        heartbeat_cache = download_url_cache.get(heartbeat_url)
        if heartbeat_cache is None:
            jsonData = await http_123_request(
                job_id, path="/api/v2/file/list?parentFileId=0&limit=1"
            )
            download_url_cache[heartbeat_url] = {
                "url": heartbeat_url,
                "expire_time": time.time()
                + config_manager.get("cache_expire_time", job_id),
            }
            if jsonData["code"] != 0:
                # 抛出异常以便调用者处理
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=jsonData["code"], detail=jsonData["message"]
                )
    except Exception as e:
        if isinstance(e, HTTPException):
            global_job_cache_tokens[job_id] = False
            logger.warning(f"{job_id} 心跳检测失败, 禁用缓存文件。error:{e}")


async def get_file_list(
    job_id, parent_file_id=0, limit=100, lastFileId=None, max_retries=0
):
    """
    获取文件列表 - 异步实现
    :param parent_file_id: 父文件夹ID，默认为0（根目录）
    :param limit: 返回的文件数量限制，默认为100
    :param access_token: 访问令牌，如果未提供则自动获取
    :return: 文件列表JSON数据
    """
    try:
        start_time = time.time()
        response = await http_123_request(
            job_id,
            path=f"/api/v2/file/list?parentFileId={parent_file_id}&limit={limit}"
            + (f"&lastFileId={lastFileId}" if lastFileId else ""),
        )
        elapsed = time.time() - start_time
        if elapsed < 0.34:
            await asyncio.sleep(0.34 - elapsed)
        return response
    except:
        if max_retries < 3:
            await asyncio.sleep(5)
            max_retries = max_retries + 1
            logger.info(f"获取文件列表失败: {parent_file_id}, 重试{max_retries}...")
            return await get_file_list(
                job_id,
                parent_file_id=parent_file_id,
                limit=limit,
                lastFileId=lastFileId,
                max_retries=max_retries,
            )
        else:
            raise Exception(f"获取文件列表失败: {parent_file_id}")


async def get_file_infos(job_id, file_ids):
    """
    获取多个文件信息 - 异步实现
    :param file_ids: 文件ID列表，逗号分隔
    :return: 文件信息JSON数据
    """
    try:
        payload = json.dumps({"fileIds": file_ids})
        response = await http_123_request(
            job_id, payload=payload, path=f"/api/v1/file/infos", method="POST"
        )
        return response
    except:
        raise Exception(f"获取文件信息失败: {file_ids}")


async def get_file_info(fileId, job_id, max_retries=0):
    """
    获取文件信息 - 异步实现
    :param fileId: 文件ID
    :return: 文件信息JSON数据
    """

    try:
        response = await http_123_request(
            job_id, path=f"/api/v1/file/detail?fileID={fileId}"
        )
        return response["data"]
    except:
        if max_retries < 3:
            await asyncio.sleep(5)
            max_retries = max_retries + 1
            logger.info(f"获取文件信息失败: {fileId}, 重试{max_retries}...")
            return await get_file_info(fileId, job_id, max_retries)
        else:
            raise Exception(f"获取文件信息失败: {fileId}")


async def get_file_download_url(file_id, job_id, max_retries=0):
    """
    获取文件下载信息 - 异步实现
    :param file_id: 文件ID
    :param access_token: 访问令牌，如果未提供则自动获取
    :return: 下载信息JSON数据
    """
    try:
        response = await http_123_request(
            job_id, path=f"/api/v1/file/download_info?fileId={file_id}"
        )
        return response["data"]["downloadUrl"]
    except:
        if max_retries < 3:
            await asyncio.sleep(5)
            max_retries = max_retries + 1
            logger.info(f"获取文件下载信息失败: {file_id}, 重试{max_retries}...")
            return await get_file_download_url(file_id, job_id, max_retries)
        else:
            logger.info(f"获取文件下载信息失败: {file_id}")


async def delete_file_by_id(file_id, job_id):
    """
    删除文件 - 异步实现
    :param file_id: 文件ID
    :param job_id: 任务ID
    :return: 删除结果JSON数据
    """
    # qps设置为1
    await asyncio.sleep(1)
    try:
        payload = json.dumps({"fileIDs": [file_id]})
        response = await http_123_request(
            job_id, payload=payload, path=f"/api/v1/file/trash", method="POST"
        )
        if response["code"] == 0:
            logger.info(f"删除云盘文件成功: {job_id} - {file_id}")
    except Exception as e:
        logger.info(f"删除云盘文件失败: {job_id} - {file_id} - 错误: {str(e)}")


# 创建文件上传信息
async def upload_file_v2_create(
    parent_file_id, filename, etag, size, duplicate, contain_dir, job_id
):
    """
    创建文件上传信息 - 异步实现
    :param parent_file_id: 父文件夹ID
    :param filename: 文件名
    :param etag: 文件ETAG
    :param size: 文件大小
    :param duplicate: 是否允许重复
    :param contain_dir: 是否包含目录
    :param job_id: 任务ID
    :return: 上传信息JSON数据，包含code, message, data字段
    """
    try:
        payload = json.dumps(
            {
                "parentFileID": parent_file_id,
                "filename": filename,
                "etag": etag,
                "size": size,
                "duplicate": duplicate,
                "containDir": contain_dir,
            }
        )
        response = await http_123_request(
            job_id, payload=payload, path=f"/upload/v2/file/create", method="POST"
        )
        return response
    except Exception as e:
        # 永远记录具体错误信息，而不是模糊的"失败"二字
        logger.error(f"创建文件上传信息失败: {filename}, 错误: {str(e)}")
        # 返回一致的错误结构，与正常响应保持相同格式
        return {
            "code": 500,
            "message": f"创建文件上传信息失败: {str(e)}",
            "data": {"reuse": False, "preuploadID": ""},
        }


async def upload_file_v2_slice(
    file_name: str, slice_no: str, chunk: bytes, upload_id: str, url: str, job_id: str
):
    """上传文件分片到123云盘 - 异步实现

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
    access_token = await get_access_token(job_id)

    # 计算分片MD5
    slice_md5 = calculate_chunk_md5(chunk)

    # 准备请求头
    headers = {
        "Platform": "open_platform",
        "Authorization": f"Bearer {access_token}",
    }

    # 记录请求信息用于调试
    logger.info(f"分片大小: {len(chunk)} bytes, MD5: {slice_md5}")

    # 准备请求数据 - 使用FormData进行文件上传
    data = aiohttp.FormData()
    data.add_field(
        "slice",
        chunk,
        filename=os.path.basename(file_name),
        content_type="application/octet-stream",
    )
    data.add_field("preuploadID", upload_id)
    data.add_field("sliceNo", slice_no)
    data.add_field("sliceMD5", slice_md5)
    data.add_field("sliceSize", str(len(chunk)))

    # 发送请求，增加超时设置
    try:
        session = await session_manager.get_session()
        async with session.post(
            url, headers=headers, data=data, timeout=30
        ) as response:
            # 错误处理：检查响应是否有效
            response.raise_for_status()
            # 尝试解析JSON响应
            if await response.text():
                return await response.json()
            else:
                # 响应内容为空
                return {"code": 1, "message": "Empty response from server"}
    except aiohttp.ClientError as e:
        logger.error(f"请求异常: {str(e)}")
        return {"code": 999, "message": f"Request failed: {str(e)}"}
    except json.JSONDecodeError:
        # JSON解析错误
        return {
            "code": 2,
            "message": f"Invalid JSON response",
        }


# 完整的分片上传流程
async def complete_multipart_upload(
    file_path: str, file_name: str, upload_info: dict, job_id: str
):
    """执行完整的分片上传流程 - 异步实现

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
        preupload_id = upload_info.get("preuploadID")
        if not preupload_id:
            return {"code": 3, "message": "Missing preuploadID in upload_info"}

        # 获取分片大小，默认为4MB
        slice_size = upload_info.get("sliceSize", 4 * 1024 * 1024)
        try:
            slice_size = int(slice_size)
        except (ValueError, TypeError):
            logger.warning(f"Invalid sliceSize: {slice_size}, using default 4MB")
            slice_size = 4 * 1024 * 1024

        # 获取上传服务器地址
        servers = upload_info.get("servers", [])
        if not servers:
            return {"code": 4, "message": "No upload servers available"}

        upload_server = servers[0]

        # 读取文件分片并逐个上传
        i = 0
        async for chunk in async_read_file_chunks(file_path, chunk_size=slice_size):
            i += 1
            slice_no = str(i)  # 分片序号从1开始
            url = f"{upload_server}/upload/v2/file/slice"

            # 记录上传前日志
            logger.info(f"开始上传分片 {slice_no}，大小: {len(chunk)/1000/1000} MB")

            response = await upload_file_v2_slice(
                file_name=file_name,
                slice_no=slice_no,
                chunk=chunk,
                upload_id=preupload_id,
                url=url,
                job_id=job_id,
            )

            # 检查上传是否成功
            if response.get("code") != 0:
                error_msg = response.get("message", "Unknown error")
                logger.error(f"分片 {slice_no} 上传失败: {error_msg}")
                return {
                    "code": response.get("code", 5),
                    "message": f"分片 {slice_no} 上传失败: {error_msg}",
                }

        # 所有分片上传完成
        logger.info(f"文件 {file_name} 所有分片上传成功")
        return {
            "code": 0,
            "message": "所有分片上传成功",
            "data": {"upload_id": preupload_id},
        }

    except Exception as e:
        # 捕获所有其他异常
        logger.error(f"分片上传过程中发生错误: {str(e)}")
        return {"code": 999, "message": f"Upload process failed: {str(e)}"}
