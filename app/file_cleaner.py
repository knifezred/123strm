import os
from typing import Dict
import asyncio

from . import logger


class FileCleaner:
    """
    文件清理器 - 负责清理本地目录中不在云盘文件列表中的文件和空文件夹
    """

    def __init__(self, cloud_files: Dict[str, str] = None):
        self.cloud_files = cloud_files or {}

    async def clean_local_files(self, local_dir: str):
        """
        清理本地目录中不在云盘文件列表中的文件和空文件夹

        Args:
            local_dir: 要清理的本地目录路径
        """
        try:
            # 检查目录是否存在 - 使用to_thread避免阻塞事件循环
            dir_exists = await asyncio.to_thread(os.path.exists, local_dir)
            if not dir_exists:
                logger.warning(f"清理目录不存在: {local_dir}")
                return

            logger.info(f"清理目录 {local_dir} 中的失效文件和空文件夹")

            # 从下到上遍历目录，这样可以安全地删除空文件夹
            # os.walk是同步操作，使用to_thread在单独线程中执行
            async def walk_dirs():
                # 创建一个协程列表来存储目录遍历过程中的操作
                tasks = []
                # 使用to_thread执行os.walk
                for root, dirs, files in await asyncio.to_thread(
                    os.walk, local_dir, topdown=False
                ):
                    # 添加删除无效文件的任务
                    tasks.append(self._delete_invalid_files(root, files))
                    # 添加删除空目录的任务
                    tasks.append(self._delete_empty_directories(root, dirs))
                # 等待所有任务完成
                await asyncio.gather(*tasks)

            # 执行目录遍历和清理操作
            await walk_dirs()

            logger.info(f"清理目录 {local_dir} 完成")
        except Exception as e:
            logger.error(e)

    async def _delete_invalid_files(self, root: str, files: list):
        """
        删除不在云盘文件列表中的文件

        Args:
            root: 当前目录路径
            files: 当前目录下的文件列表
        """
        # 创建任务列表来并行处理文件删除
        tasks = []
        for file in files:
            file_path = os.path.join(root, file)
            # 检查文件是否在云盘列表中
            if file_path not in self.cloud_files:
                # 为每个文件删除操作创建一个异步任务
                tasks.append(self._delete_file(file_path))
        # 并行执行所有删除任务
        if tasks:
            await asyncio.gather(*tasks)

    async def _delete_file(self, file_path: str):
        """
        异步删除单个文件

        Args:
            file_path: 要删除的文件路径
        """
        try:
            # 使用to_thread在单独线程中执行文件删除操作
            await asyncio.to_thread(os.remove, file_path)
            logger.info(f"已删除: {file_path}")
        except OSError as e:
            logger.error(e)

    async def _delete_empty_directories(self, root: str, dirs: list):
        """
        删除空文件夹

        Args:
            root: 当前目录路径
            dirs: 当前目录下的子目录列表
        """
        # 创建任务列表来并行处理目录删除
        tasks = []
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            # 为每个目录删除操作创建一个异步任务
            tasks.append(self._delete_empty_dir(dir_path))
        # 并行执行所有删除任务
        if tasks:
            await asyncio.gather(*tasks)

    async def _delete_empty_dir(self, dir_path: str):
        """
        异步删除空目录

        Args:
            dir_path: 要删除的目录路径
        """
        try:
            # 检查目录是否为空 - 使用to_thread避免阻塞事件循环
            is_empty = await asyncio.to_thread(self._is_directory_empty, dir_path)
            if is_empty:
                # 使用to_thread在单独线程中执行目录删除操作
                await asyncio.to_thread(os.rmdir, dir_path)
                logger.info(f"已删除: {dir_path}")
        except OSError as e:
            logger.error(e)

    def _is_directory_empty(self, dir_path: str) -> bool:
        """
        检查目录是否为空

        Args:
            dir_path: 要检查的目录路径

        Returns:
            bool: 目录是否为空
        """
        try:
            return len(os.listdir(dir_path)) == 0
        except OSError:
            return False
