import yaml
import os
import time
import shutil
import urllib.parse
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, FileResponse


from .cloud_api import (
    complete_multipart_upload,
    download_url_cache,
    get_file_download_info,
    upload_file_v2_create,
)
from .config_manager import config_manager
from .const import MAX_FILE_SIZE, DEFAULT_DUPLICATE, DEFAULT_CONTAIN_DIR

from . import logger
from .job_manager import job_manager
from .utils import calculate_file_md5
from app import cloud_api
import os

# 启动api
local302Api = FastAPI()


@local302Api.get("/index_old")
async def index():
    return FileResponse("app/public/index.html")


@local302Api.get("/")
async def index_page():
    return FileResponse("app/public/home.html")


@local302Api.get("/config.html")
async def config_page():
    return FileResponse("app/public/config.html")


@local302Api.get("/job_config.html")
async def job_config_page():
    return FileResponse("app/public/job_config.html")


@local302Api.get("/get_config")
async def get_config():
    return config_manager.get_all()


@local302Api.post("/save_config")
async def save_config(update_config: dict):
    """
    保存配置
    :param update_config: 更新的配置数据(dict格式)
    :return: 保存结果
    """
    try:
        # 备份现有配置
        backup_path = os.path.join(config_manager.get_config_folder(), "config.bak.yml")
        shutil.copyfile(
            os.path.join(config_manager.get_config_folder(), "config.yml"), backup_path
        )
        with open(
            os.path.join(config_manager.get_config_folder(), "config.yml"),
            "w",
            encoding="utf-8",
        ) as f:
            yaml.dump(update_config, f, allow_unicode=True)
        config_manager.load()
        return {"success": True, "message": "配置已保存"}
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
            + config_manager.get("cache_expire_time", job_id),
        }
        logger.info(f"302跳转成功: {download_url}")

        return RedirectResponse(download_url, 302)
    except Exception as e:
        logger.info(f"获取文件下载链接失败: {str(e)}")

    logger.info(f"未找到文件: {file_id}")


@local302Api.post("/scrape_directory")
async def scrape_directory(query: dict):
    """
    刮削目标文件夹
    :param dep_job_id: 任务ID
    :param parent_id: 文件夹ID
    :param parent_path: 目标文件夹路径
    :return: 文件ID列表
    """
    # 使用asyncio.to_thread在单独的线程中运行同步函数，避免阻塞事件循环
    # todo: 手动选择文件夹
    result = await asyncio.to_thread(
        job_manager.run_job,
        query["dep_job_id"],
        query["parent_id"],
        query["parent_path"],
    )
    # 返回适当的响应
    return {"success": True, "message": "刮削任务已完成", "result": result}


@local302Api.post("/upload_directory")
async def upload_directory(query: dict):
    """
    上传目标文件夹
    :param dep_job_id: 任务ID
    :param folder_path: 文件夹路径
    :param parent_id: 目标文件夹ID
    :param generate_strm: 是否生成STRM文件
    :param parent_path: 目标文件夹路径
    :return: 上传结果
    """
    # 验证输入参数
    required_params = ["folder_path", "dep_job_id", "parent_id"]
    for param in required_params:
        if param not in query:
            logger.error(f"缺少必要参数: {param}")
            return {
                "success": False,
                "message": f"缺少必要参数: {param}",
                "result": None,
            }

    folder_path = query["folder_path"]
    if not os.path.exists(folder_path):
        logger.error(f"文件夹不存在: {folder_path}")
        return {
            "success": False,
            "message": f"文件夹不存在: {folder_path}",
            "result": None,
        }

    result = "ok"
    success_count = 0
    failed_count = 0

    # 遍历文件夹所有文件
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)

            # 跳过符号链接和特殊文件
            if not os.path.isfile(file_path):
                logger.warning(f"跳过非文件: {file_path}")
                continue

            try:
                # 安全地获取文件大小
                file_size = os.path.getsize(file_path)

                # 计算文件ETAG（这对大文件可能很慢）
                logger.info(f"正在计算文件MD5: {file_path}")
                file_etag = calculate_file_md5(file_path)

                # 构建相对路径作为文件名
                file_name = file_path.replace(
                    folder_path, "", 1
                )  # 添加count=1避免多处替换
                if file_name.startswith(os.sep):
                    file_name = file_name[1:]  # 去掉开头的斜杠

                # 创建上传信息
                logger.info(f"准备上传文件: {file_path} 到 {query['parent_id']}")
                upload_info = upload_file_v2_create(
                    query["parent_id"],
                    file_name,
                    file_etag,
                    file_size,
                    DEFAULT_DUPLICATE,
                    DEFAULT_CONTAIN_DIR,
                    query["dep_job_id"],
                )

                # 防御性检查upload_info
                if not upload_info or "data" not in upload_info:
                    logger.error(f"创建上传信息失败，响应格式错误: {file_path}")
                    failed_count += 1
                    continue

                # 处理秒传逻辑
                if upload_info["data"].get("reuse", False):
                    # 秒传成功，删除本地文件
                    os.remove(file_path)
                    logger.info(f"秒传成功，删除本地文件: {file_path}")
                    success_count += 1
                else:
                    # 获取上传ID
                    upload_id = upload_info["data"].get("preuploadID", "")
                    # 检查文件大小，非秒传情况下不上传超过10GB的文件
                    if file_size > MAX_FILE_SIZE:
                        logger.error(f"文件大小超过10GB，禁止上传: {file_path}")
                        failed_count += 1
                        continue
                    if upload_id:
                        logger.info(f"秒传失败，开始分片上传: {file_path}")
                        # 执行分片上传
                        slice_result = complete_multipart_upload(
                            file_path=file_path,
                            file_name=file_name,
                            upload_info=upload_info["data"],
                            job_id=query["dep_job_id"],
                        )

                        if slice_result and slice_result.get("code") == 0:
                            logger.info(f"分片上传成功: {file_path}")
                            os.remove(file_path)
                            logger.info(f"分片上传成功，删除本地文件: {file_path}")
                            success_count += 1
                        else:
                            error_msg = (
                                slice_result.get("message", "Unknown error")
                                if slice_result
                                else "上传失败"
                            )
                            logger.error(
                                f"分片上传失败: {file_path}, 错误: {error_msg}"
                            )
                            failed_count += 1
                    else:
                        logger.error(f"preuploadID获取失败: {file_path}")
                        failed_count += 1
            except Exception as e:
                logger.error(f"处理文件时出错: {file_path}, 错误: {str(e)}")
                failed_count += 1
                # 继续处理下一个文件，不中断整个任务
                continue

    # 删除空文件夹（从最深层开始删除）
    for root, dirs, files in os.walk(folder_path, topdown=False):
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    logger.info(f"删除空文件夹: {dir_path}")
            except OSError as e:
                logger.warning(f"删除文件夹失败: {dir_path}, 错误: {str(e)}")
    if query.get("generate_strm", False):
        # 生成STRM文件
        await job_manager.run_job(
            job_id=query["dep_job_id"],
            folder_id=query["parent_id"],
            parent_path=query["parent_path"],
        )
    # 返回详细的结果信息
    return {
        "success": True,
        "message": "上传任务已完成",
        "result": {
            "total_files": success_count + failed_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "details": result,
        },
    }


@local302Api.get("/get_job_folders/{job_id}/{folder_id}")
def get_job_folders(job_id: str, folder_id: str = None):
    """
    递归遍历文件夹

    Args:
        job_id: 任务ID
        folder_id: 根文件夹ID，逗号分隔多个文件夹ID

    Returns:
        包含所有文件夹ID的集合
    """
    # 存储所有文件夹ID的集合
    all_folders = []
    file_list = []
    root_folder_id = None
    current_job = config_manager.get_job_config(job_id)
    if not current_job:
        logger.error(f"获取job_id失败，job_id: {job_id}")
        raise HTTPException(status_code=400, detail=f"获取job_id失败: {job_id}")
    if folder_id == "root":
        folder_id = None
        root_folder_id = current_job.get("root_folder_id")
        if not root_folder_id:
            logger.error(f"获取root_folder_id失败，job_id: {job_id}")
            raise HTTPException(
                status_code=400, detail=f"获取root_folder_id失败: {job_id}"
            )

    if folder_id:
        file_list = cloud_api.get_file_list(
            job_id, parent_file_id=folder_id, lastFileId=None
        )
    else:
        root_folder_ids = root_folder_id.split(",")
        file_list = cloud_api.get_file_infos(job_id, file_ids=root_folder_ids)

    if not (
        not file_list or "data" not in file_list or "fileList" not in file_list["data"]
    ):
        # 遍历当前页的所有文件
        for item in file_list["data"]["fileList"]:
            item_type = item.get("type")
            is_trashed = item.get("trashed", 0) == 1
            item_id = item.get("fileId")
            logger.info(
                f"item_id: {item_id}, item_type: {item_type}, is_trashed: {is_trashed}"
            )
            # 处理根文件夹的情况
            if folder_id is None:
                item["parentFileId"] = "root"
            # 如果是文件夹且未被删除，则添加到集合并递归遍历
            if item_type == 1 and not is_trashed and item_id:
                all_folders.append(item)

    return {"success": True, "message": "获取文件夹列表成功", "result": all_folders}


@local302Api.get("/get_job_ids")
async def get_job_ids():
    """
    获取所有job_id
    :return: job_id列表或错误信息
    :raises HTTPException 500: 当获取job_id失败时
    """
    try:
        job_ids = config_manager.get_job_ids()
        return {"success": True, "message": "获取job_ids成功", "result": job_ids}
    except Exception as e:
        logger.error(f"获取job_ids失败，错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取job_ids失败: {str(e)}")


@local302Api.get("/get_job_target_dir/{job_id}")
async def get_job_target_dir(job_id: str):
    """
    获取job_id对应的刮削目录
    :param job_id: 任务ID
    :return: 刮削目录路径或错误信息
    :raises HTTPException 400: 当job_id不存在时
    :raises HTTPException 500: 当获取刮削目录失败时
    """
    try:
        job_config = config_manager.get_job_config(job_id)
        if not job_config:
            raise HTTPException(status_code=400, detail=f"job_id {job_id} 不存在")

        target_dir = job_config.get("target_dir")
        if not target_dir:
            raise HTTPException(status_code=400, detail=f"job_id {job_id} 没有刮削目录")

        return {"success": True, "message": "获取刮削目录成功", "result": target_dir}
    except Exception as e:
        logger.error(f"获取job_id {job_id} 刮削目录失败，错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务刮削目录失败: {str(e)}")
