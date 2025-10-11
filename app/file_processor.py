import os
import urllib.parse
import asyncio

from .cloud_api import get_file_download_url
from .config_manager import config_manager
from .utils import download_file
from . import logger


class FileProcessor:
    """
    文件处理器 - 负责处理单个文件的逻辑，包括生成strm文件和下载各类支持文件
    """

    def __init__(self, job_id: str):
        self.job_id = job_id
        # 加载配置
        self.target_dir = config_manager.get("target_dir", job_id=job_id)
        self.path_prefix = config_manager.get("path_prefix", job_id=job_id)
        self.use_302_url = config_manager.get("use_302_url", job_id=job_id)
        self.flatten_mode = config_manager.get("flatten_mode", job_id=job_id)
        self.overwrite = config_manager.get("overwrite", job_id=job_id)

        # 媒体类型配置
        self.video_extensions = config_manager.get("video_extensions", job_id=job_id)
        self.image_extensions = config_manager.get("image_extensions", job_id=job_id)
        self.subtitle_extensions = config_manager.get(
            "subtitle_extensions", job_id=job_id
        )
        self.download_image_suffix = config_manager.get(
            "download_image_suffix", job_id=job_id
        )

    async def process_file(self, file_info: dict, parent_path: str):
        """
        处理单个文件

        Args:
            file_info: 文件信息字典
            parent_path: 父文件夹路径
        """
        result = None
        file_name = file_info.get("filename", "")
        file_base_name, file_extension = os.path.splitext(file_name)
        file_extension = file_extension.lower()
        if parent_path.startswith(self.target_dir):
            target_path = os.path.join(parent_path)
        else:
            target_path = os.path.join(self.target_dir, parent_path)

        if file_extension in self.video_extensions:
            result = self._process_video_file(
                file_info, file_name, file_base_name, parent_path, target_path
            )
        elif file_extension in self.image_extensions:
            result = await self._process_image_file(file_info, file_base_name, target_path)
        elif file_extension in self.subtitle_extensions:
            result = await self._process_subtitle_file(file_info, target_path)
        elif file_extension == ".nfo":
            result = await self._process_nfo_file(file_info, target_path)
        return result

    def _process_video_file(
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
        # 不再限制最小文件大小
        # if int(file_info.get("size", 0)) <= self.min_file_size:
        #     return

        # 生成视频URL
        if self.use_302_url:
            job_id_encode = urllib.parse.quote(self.job_id)
            video_url = f"{config_manager.get("proxy", self.job_id)}/get_file_url/{file_info["fileId"]}/{job_id_encode}"
        else:
            video_url = os.path.join(self.path_prefix, parent_path, file_name)

        # 确定strm文件路径
        if self.flatten_mode:
            # 平铺模式
            strm_path = os.path.join(self.target_dir, file_base_name + ".strm")
        else:
            strm_path = os.path.join(target_path, file_base_name + ".strm")

        # 确保目标目录存在
        os.makedirs(os.path.dirname(strm_path), exist_ok=True)

        # 检查文件是否存在，文件不存在或者覆写为True时写入文件
        if not os.path.exists(strm_path) or self.overwrite:
            try:
                with open(strm_path, "w", encoding="utf-8") as f:
                    f.write(video_url)
                logger.info(f"生成成功: {strm_path}")
            except Exception as e:
                logger.error(f"生成strm文件失败: {strm_path}, 错误信息: {str(e)}")

        return strm_path

    async def _process_image_file(
        self, file_info: dict, file_base_name: str, target_path: str
    ):
        """
        处理图片文件
        """
        if self._is_filetype_downloadable("image"):
            # 检查是否需要下载特定后缀的图片
            # 修复：确保download_image_suffix是可迭代对象
            if not self.download_image_suffix or (
                isinstance(self.download_image_suffix, (list, tuple))
                and file_base_name.endswith(tuple(self.download_image_suffix))
            ):
                # 直接使用await调用异步方法
                return await self._download_file_with_log(target_path, file_info)

    async def _process_subtitle_file(self, file_info: dict, target_path: str):
        """
        处理字幕文件
        """
        if self._is_filetype_downloadable("subtitle"):
            return await self._download_file_with_log(target_path, file_info)

    async def _process_nfo_file(self, file_info: dict, target_path: str):
        """
        处理nfo文件
        """
        if self._is_filetype_downloadable("nfo"):
            return await self._download_file_with_log(target_path, file_info)

    def _is_filetype_downloadable(self, file_type: str) -> bool:
        """
        判断是否应该下载指定类型的文件

        Args:
            file_type: 文件类型配置名

        Returns:
            bool 是否下载
        """
        return config_manager.get(file_type, self.job_id) and not self.flatten_mode

    async def _download_file_with_log(self, target_path: str, file_info: dict):
        """
        下载文件并打印日志

        Args:
            target_path: 目标路径
            file_info: 文件详情
        """
        filename = file_info.get("filename", "")
        target_file = os.path.join(target_path, filename)

        # 判断文件是否存在
        if not os.path.exists(target_file):
            try:
                # 使用异步方式获取下载URL
                download_url = await get_file_download_url(
                    file_info["fileId"], self.job_id
                )
                # 由于download_file函数是同步的，我们需要在单独的线程中执行
                await asyncio.to_thread(download_file, download_url, target_file)
            except Exception as e:
                logger.error(f"下载文件失败: {target_file}, 错误信息: {str(e)}")
        return target_file
