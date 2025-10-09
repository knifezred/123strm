import os
from typing import Dict

from .error_handler import handle_exception
from . import logger


class FileCleaner:
    """
    文件清理器 - 负责清理本地目录中不在云盘文件列表中的文件和空文件夹
    """

    def __init__(self, cloud_files: Dict[str, str] = None):
        self.cloud_files = cloud_files or {}

    def clean_local_files(self, local_dir: str):
        """
        清理本地目录中不在云盘文件列表中的文件和空文件夹

        Args:
            local_dir: 要清理的本地目录路径
        """
        try:
            if not os.path.exists(local_dir):
                logger.warning(f"清理目录不存在 directory={local_dir}")
                return

            logger.info(f"开始清理目录中的失效文件和空文件夹 directory={local_dir}")

            # 从下到上遍历目录，这样可以安全地删除空文件夹
            for root, dirs, files in os.walk(local_dir, topdown=False):
                # 删除不在网盘列表中的文件
                self._delete_invalid_files(root, files)

                # 删除空文件夹
                self._delete_empty_directories(root, dirs)

            logger.info(f"目录清理完成 directory={local_dir}")
        except Exception as e:
            handle_exception(e, "cleanup", {"directory": local_dir})
        for root, dirs, files in os.walk(local_dir, topdown=False):
            # 删除不在网盘列表中的文件
            self._delete_invalid_files(root, files)

            # 删除空文件夹
            self._delete_empty_directories(root, dirs)

    def _delete_invalid_files(self, root: str, files: list):
        """
        删除不在云盘文件列表中的文件

        Args:
            root: 当前目录路径
            files: 当前目录下的文件列表
        """
        for file in files:
            file_path = os.path.join(root, file)
            # 检查文件是否在云盘列表中
            if file_path not in self.cloud_files:
                try:
                    os.remove(file_path)
                    logger.info(f"删除文件 file_path={file_path}")
                except OSError as e:
                    handle_exception(e, "delete_file", {"file_path": file_path})

    def _delete_empty_directories(self, root: str, dirs: list):
        """
        删除空文件夹

        Args:
            root: 当前目录路径
            dirs: 当前目录下的子目录列表
        """
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            try:
                # 检查目录是否为空
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    logger.info(f"删除空文件夹 directory={dir_path}")
            except OSError as e:
                handle_exception(e, "delete_dir", {"directory": dir_path})

    def update_cloud_files(self, cloud_files: Dict[str, str]):
        """
        更新云盘文件列表

        Args:
            cloud_files: 新的云盘文件列表，键为文件路径，值为文件ID
        """
        self.cloud_files = cloud_files
