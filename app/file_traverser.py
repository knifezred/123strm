import os
import urllib.parse
from typing import Dict, Set

from .file_processor import FileProcessor


from .error_handler import handle_exception
from .cloud_api import get_file_info, get_file_list
from .config_manager import config_manager

from . import logger


class FileTraverser:
    """
    文件遍历器 - 负责递归遍历云盘文件夹并收集文件信息
    """

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.cloud_files: Dict[str, str] = {}
        self.target_dir = config_manager.get("target_dir", job_id=job_id)

        self.file_processor = FileProcessor(self.job_id)

        # 加载配置
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
            "subtitle_extensions", job_id=job_id, default=[".srt", ".ass", ".sub"]
        )
        self.download_image_suffix = config_manager.get(
            "download_image_suffix", job_id=job_id, default=[]
        )

    def traverse_folders(self, parent_id=None, parent_path=""):
        """
        递归遍历文件夹，处理所有分页数据

        Args:
            parent_id: 当前父文件夹ID，默认None表示使用配置中的root_folder_id
            parent_path: 当前父文件夹的路径，用于构建完整路径
        """
        try:
            if parent_id is None:
                parent_id = config_manager.get("root_folder_id", job_id=self.job_id)
            logger.info(
                f"开始遍历文件夹: {parent_path}",
            )

            # 兼容同账号多文件夹配置
            if isinstance(parent_id, str) and "," in parent_id:
                parent_id_list = parent_id.split(",")
                for pid in parent_id_list:
                    self.traverse_folders(pid, parent_path)
                return
            if parent_path == "":
                folder_info = get_file_info(parent_id, self.job_id)
                folder_path = folder_info.get("filename", "") if folder_info else ""
                parent_path = os.path.join(parent_path, folder_path)

            # 处理当前页和所有分页数据
            last_file_id = None
            while True:
                file_list = get_file_list(
                    self.job_id,
                    parent_file_id=parent_id,
                    limit=100,
                    lastFileId=last_file_id,
                )

                if not file_list or "data" not in file_list:
                    break

                self._process_file_list(file_list, parent_path)

                if file_list["data"].get("lastFileId") == -1:
                    break
                last_file_id = file_list["data"]["lastFileId"]

        except Exception as e:
            handle_exception(
                e,
                "traverse",
                {
                    "job_id": self.job_id,
                    "folder_id": parent_id,
                    "folder_path": parent_path,
                },
            )

    def _process_file_list(self, file_list: dict, parent_path: str):
        """
        处理文件列表中的每个项目

        Args:
            file_list: 文件列表数据
            parent_path: 父文件夹路径
        """
        if "data" not in file_list or "fileList" not in file_list["data"]:
            return

        file_list_data = file_list["data"]["fileList"]

        for item in file_list_data:
            item_type = item.get("type")
            filename = item.get("filename", "")
            # 构建路径
            process_path = ""
            if parent_path == "":
                process_path = filename
            elif parent_path.startswith("/media/") or parent_path.startswith("media/"):
                process_path = os.path.join(parent_path, filename)
            else:
                process_path = os.path.join(self.target_dir, parent_path, filename)
            if item_type == 1:  # 文件夹
                self.cloud_files[process_path] = item["fileId"]
                self.traverse_folders(item["fileId"], process_path)
            elif item_type == 0:  # 文件
                # 处理文件
                process_path = process_path.replace(filename, "")
                file_path = self.file_processor.process_file(item, process_path)
                self.cloud_files[file_path] = item["fileId"]

    def get_cloud_files(self) -> Dict[str, str]:
        """
        获取收集到的云盘文件信息

        Returns:
            字典，键为文件路径，值为文件ID
        """
        return self.cloud_files
