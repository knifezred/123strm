import os
import json
from typing import Dict, Optional
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from . import logger
from .config_manager import config_manager
from .cloud_api import delete_file_by_id
from .utils import async_file_exists, async_is_dir, async_listdir


class FileManager:
    """
    文件管理器 - 负责文件监控、清理和缓存管理的统一类
    """
    
    def __init__(self):
        # 初始化文件监控相关属性
        self.observer = None
        self.watcher = None
        self.is_monitoring = False
        self.watch_dir = None
        
    def start_monitoring(self, watch_dir: str):
        """
        启动文件监控
        
        Args:
            watch_dir: 要监控的目录路径
        """
        if self.is_monitoring:
            logger.warning(f"文件监控已经在运行中: {self.watch_dir}")
            return
        
        self.watch_dir = watch_dir
        self.observer = Observer()
        self.watcher = DeleteFileHandler()
        
        try:
            self.observer.schedule(self.watcher, watch_dir, recursive=True)
            self.observer.start()
            self.is_monitoring = True
            logger.info(f"启动文件监控: {watch_dir}")
        except Exception as e:
            logger.error(f"启动文件监控失败: {str(e)}")
            self.observer = None
            self.watcher = None
    
    def stop_monitoring(self):
        """
        停止文件监控
        """
        if not self.is_monitoring or self.observer is None:
            logger.warning("文件监控未运行")
            return
        
        try:
            self.observer.stop()
            self.observer.join()
            self.is_monitoring = False
            logger.info("停止文件监控")
        except Exception as e:
            logger.error(f"停止文件监控失败: {str(e)}")
        finally:
            self.observer = None
            self.watcher = None
    
    async def clean_local_files(self, local_dir: str, cloud_files: Dict[str, str] = None):
        """
        清理本地目录中不在云盘文件列表中的文件和空文件夹
        
        Args:
            local_dir: 要清理的本地目录路径
            cloud_files: 云盘文件列表，键为文件路径，值为文件ID
        """
        cloud_files = cloud_files or {}
        
        if not await async_file_exists(local_dir):
            logger.warning(f"清理目录不存在: {local_dir}")
            return
        
        logger.info(f"清理目录 {local_dir} 中的失效文件和空文件夹")
        await self._clean_recursive(local_dir, cloud_files)
        logger.info(f"清理目录 {local_dir} 完成")
    
    async def _clean_recursive(self, path: str, cloud_files: Dict[str, str]):
        """
        深度优先递归清理目录
        
        Args:
            path: 当前要清理的路径
            cloud_files: 云盘文件列表
        """
        # 检查是否是目录
        is_dir = await async_is_dir(path)
        if not is_dir:
            # 不是目录则检查是否需要删除
            if path not in cloud_files:
                await self._delete_file(path)
            return
        
        # 获取目录内容
        try:
            entries = await async_listdir(path)
        except OSError as e:
            logger.error(f"读取目录内容失败: {path}, 错误: {str(e)}")
            return
        
        # 先处理所有子项
        for entry in entries:
            full_path = os.path.join(path, entry)
            await self._clean_recursive(full_path, cloud_files)  # 递归处理每个子项
        
        # 最后检查并删除空目录
        try:
            loop = asyncio.get_running_loop()
            if not await async_listdir(path):
                await loop.run_in_executor(None, os.rmdir, path)
                logger.info(f"已删除空目录: {path}")
        except OSError as e:
            logger.error(f"删除目录失败: {path}, 错误: {str(e)}")
    
    async def _delete_file(self, file_path: str):
        """
        异步删除单个文件
        
        Args:
            file_path: 要删除的文件路径
        """
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, os.remove, file_path)
            logger.info(f"已删除文件: {file_path}")
        except OSError as e:
            logger.error(f"删除文件失败: {file_path}, 错误: {str(e)}")
    
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
            
    @staticmethod
    def get_file_id_by_path(file_path: str) -> tuple[Optional[str], Optional[str]]:
        """
        根据文件路径获取文件ID和任务ID
        
        Args:
            file_path: 文件路径
        
        Returns:
            tuple: (文件ID, 任务ID)，如果找不到返回(None, None)
        """
        try:
            cache_file_path = os.path.join(
                config_manager.get_config_folder(), "cache_files.json"
            )
            
            if not os.path.exists(cache_file_path):
                logger.warning(f"缓存文件不存在: {cache_file_path}")
                return (None, None)
            
            with open(cache_file_path, "r") as f:
                cache_data = json.load(f)
                # 优先检查global区域
                if "global" in cache_data and file_path in cache_data["global"]:
                    return (cache_data["global"][file_path], None)
                
                # 检查各job区域
                for job_id, job_data in cache_data.items():
                    if job_id != "global" and file_path in job_data:
                        return (job_data[file_path], job_id)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"读取缓存文件失败: {cache_file_path}, 错误: {str(e)}")
        
        return (None, None)


class DeleteFileHandler(FileSystemEventHandler):
    """
    文件系统事件处理器，用于监控并处理文件删除事件
    """
    
    def __init__(self):
        logger.info("DeleteFileHandler 初始化完成")
    
    def on_deleted(self, event):
        """
        当文件被删除时触发
        """
        if event.is_directory:
            return
            
        logger.info(f"监听到文件删除: {event.src_path}, 准备移除云端文件")
        abs_path = os.path.abspath(event.src_path)
        
        # 使用FileManager的静态方法获取文件ID
        file_id, job_id = FileManager.get_file_id_by_path(abs_path)
        if file_id:
            try:
                delete_file_by_id(file_id, job_id)
                logger.info(f"已从云端删除文件: {abs_path}, file_id: {file_id}")
            except Exception as e:
                logger.error(f"从云端删除文件失败: {abs_path}, 错误: {str(e)}")
        else:
            logger.warning(f"未找到文件对应的云端ID: {abs_path}")


# 创建全局文件管理器实例
file_manager = FileManager()