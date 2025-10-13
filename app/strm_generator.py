import os
import urllib.parse
from typing import Dict
import asyncio

from .cloud_api import get_file_info, get_file_list, get_file_download_url
from .config_manager import config_manager
from .utils import async_file_exists, async_makedirs, async_download_file
from . import logger


class StrmGenerator:
    """
    strm文件生成器 - 负责根据云盘文件信息生成对应的strm文件
    """

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.cloud_files: Dict[str, str] = {}  # 键为文件路径，值为文件ID

        # 一次性加载所有配置，避免频繁调用config_manager
        self.target_dir = config_manager.get("target_dir", job_id=job_id)
        self.path_prefix = config_manager.get("path_prefix", job_id=job_id)
        self.use_302_url = config_manager.get("use_302_url", job_id=job_id)
        self.flatten_mode = config_manager.get("flatten_mode", job_id=job_id)
        self.overwrite = config_manager.get("overwrite", job_id=job_id)

        # 媒体类型配置
        self.video_extensions = config_manager.get(
            "video_extensions",
            job_id=job_id,
            default=[".mp4", ".mkv", ".ts", ".iso"],
        )
        self.image_extensions = config_manager.get(
            "image_extensions",
            job_id=job_id,
            default=[".jpg", ".jpeg", ".png", ".webp"],
        )
        self.subtitle_extensions = config_manager.get(
            "subtitle_extensions",
            job_id=job_id,
            default=[".srt", ".ass", ".sub"],
        )
        self.download_image_suffix = config_manager.get(
            "download_image_suffix",
            job_id=job_id,
            default=[],
        )

        # 预计算可下载类型的配置
        self.download_images = (
            config_manager.get("image", job_id=job_id) and not self.flatten_mode
        )
        self.download_subtitles = (
            config_manager.get("subtitle", job_id=job_id) and not self.flatten_mode
        )
        self.download_nfo = (
            config_manager.get("nfo", job_id=job_id) and not self.flatten_mode
        )

    async def traverse_folders(self, parent_id=None, parent_path=""):
        """
        递归遍历文件夹，处理所有分页数据
        """
        try:
            if parent_id is None:
                parent_id = config_manager.get("root_folder_id", job_id=self.job_id)
            logger.info(f"遍历文件夹: {parent_path}")

            # 兼容同账号多文件夹配置
            if isinstance(parent_id, str) and "," in parent_id:
                for pid in parent_id.split(","):
                    await self.traverse_folders(pid, parent_path)
                return

            # 构建基础路径
            if parent_path == "":
                folder_info = await get_file_info(parent_id, self.job_id)
                folder_path = folder_info.get("filename", "") if folder_info else ""
                parent_path = os.path.join(parent_path, folder_path)

            # 处理分页数据
            last_file_id = None
            while True:
                file_list = await get_file_list(
                    self.job_id,
                    parent_file_id=parent_id,
                    limit=100,
                    lastFileId=last_file_id,
                )

                if not file_list or "data" not in file_list:
                    break

                await self._process_file_list(file_list, parent_path)

                if file_list["data"].get("lastFileId") == -1:
                    break
                last_file_id = file_list["data"]["lastFileId"]

        except Exception as e:
            logger.error(f"遍历文件夹失败: {parent_path}, 错误信息: {str(e)}")

    async def _process_file_list(self, file_list: dict, parent_path: str):
        """
        处理文件列表中的每个项目
        """
        if "data" not in file_list or "fileList" not in file_list["data"]:
            return

        file_list_data = file_list["data"]["fileList"]

        for item in file_list_data:
            item_type = item.get("type")
            filename = item.get("filename", "")

            # 构建路径 - 简化逻辑
            if parent_path == "":
                process_path = filename
            elif parent_path.startswith("/media/") or parent_path.startswith("media/"):
                process_path = os.path.join(parent_path, filename)
            else:
                process_path = os.path.join(self.target_dir, parent_path, filename)

            if item_type == 1:  # 文件夹
                self.cloud_files[process_path] = item["fileId"]
                await self.traverse_folders(item["fileId"], process_path)
            elif item_type == 0:  # 文件
                # 直接处理文件并添加到cloud_files
                file_path = await self._process_file(
                    item, os.path.dirname(process_path)
                )
                self.cloud_files[file_path] = item["fileId"]

    async def _process_file(self, file_info: dict, parent_path: str):
        """
        处理单个文件，根据文件类型执行不同的处理逻辑
        """
        file_name = file_info.get("filename", "")
        file_base_name, file_extension = os.path.splitext(file_name)
        file_extension = file_extension.lower()

        # 确定目标路径
        target_path = (
            parent_path
            if parent_path.startswith(self.target_dir)
            else os.path.join(self.target_dir, parent_path)
        )

        # 根据文件类型处理
        if file_extension in self.video_extensions:
            # 处理视频文件，生成strm文件
            return await self._process_video_file(
                file_info, file_name, file_base_name, parent_path, target_path
            )
        elif file_extension in self.image_extensions and self.download_images:
            # 处理图片文件
            if not self.download_image_suffix or (
                isinstance(self.download_image_suffix, (list, tuple))
                and file_base_name.endswith(tuple(self.download_image_suffix))
            ):
                return await self._download_file_with_log(target_path, file_info)
        elif file_extension in self.subtitle_extensions and self.download_subtitles:
            # 处理字幕文件
            return await self._download_file_with_log(target_path, file_info)
        elif file_extension == ".nfo" and self.download_nfo:
            # 处理nfo文件
            return await self._download_file_with_log(target_path, file_info)

        # 默认返回文件路径
        return os.path.join(target_path, file_name)

    async def _process_video_file(
        self,
        file_info: dict,
        file_name: str,
        file_base_name: str,
        parent_path: str,
        target_path: str,
    ):
        """
        处理视频文件，生成strm文件
        """
        # 生成视频URL
        if self.use_302_url:
            job_id_encode = urllib.parse.quote(self.job_id)
            video_url = f"{config_manager.get("proxy", self.job_id)}/get_file_url/{file_info["fileId"]}/{job_id_encode}"
        else:
            video_url = os.path.join(self.path_prefix, parent_path, file_name)

        # 确定strm文件路径
        if self.flatten_mode:
            strm_path = os.path.join(self.target_dir, file_base_name + ".strm")
        else:
            strm_path = os.path.join(target_path, file_base_name + ".strm")

        # 确保目标目录存在
        await async_makedirs(os.path.dirname(strm_path))

        # 检查文件是否存在，文件不存在或者覆写为True时写入文件
        if not await async_file_exists(strm_path) or self.overwrite:
            try:
                # 使用异步方式写入文件
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: open(strm_path, "w", encoding="utf-8").write(video_url),
                )
                logger.info(f"生成成功: {strm_path}")
            except Exception as e:
                logger.error(f"生成strm文件失败: {strm_path}, 错误信息: {str(e)}")

        return strm_path

    async def _download_file_with_log(self, target_path: str, file_info: dict):
        """
        下载文件并打印日志
        """
        filename = file_info.get("filename", "")
        target_file = os.path.join(target_path, filename)

        # 判断文件是否存在
        if not await async_file_exists(target_file):
            # 确保目标目录存在
            await async_makedirs(os.path.dirname(target_file))
            try:
                # 使用异步方式获取下载URL并下载文件
                download_url = await get_file_download_url(
                    file_info["fileId"], self.job_id
                )
                await async_download_file(download_url, target_file)
                logger.info(f"下载成功: {target_file}")
            except Exception as e:
                logger.error(f"下载文件失败: {target_file}, 错误信息: {str(e)}")
        return target_file

    def get_cloud_files(self) -> Dict[str, str]:
        """
        获取收集到的云盘文件信息
        """
        return self.cloud_files
