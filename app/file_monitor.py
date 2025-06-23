import json
import os

from app import logger

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from app.api import delete_file_by_id
from app.utils import config_folder


class strmFileWatcher(FileSystemEventHandler):
    """文件系统事件处理器，用于监控并处理strm文件"""

    def __init__(self):
        logger.info("FileWatcher 初始化完成")

    def on_deleted(self, event):
        """
        当文件被删除时触发
        :param event: 文件系统事件对象
        """
        logger.info("监听到文件删除, 准备移除云端文件")
        if not event.is_directory and event.src_path.endswith(".strm"):
            # 从cache_files.json获取fileID
            abs_path = os.path.abspath(event.src_path)
            file_id, job_id = self.get_file_id_by_path(abs_path)
            if file_id is not None:
                delete_file_by_id(file_id, job_id)

    def get_file_id_by_path(self, file_path):
        """
        根据文件路径获取文件ID
        :param file_path: 要查找的文件路径
        :return: 文件ID，如果找不到返回None
        """
        try:
            cache_file_path = os.path.join(config_folder, "cache_files.json")
            logger.info(cache_file_path)
            with open(cache_file_path, "r") as f:
                cache_data = json.load(f)
                # 优先检查global区域
                if "global" in cache_data and file_path in cache_data["global"]:
                    return (cache_data["global"][file_path], None)

                # 检查各job区域
                for job_id, job_data in cache_data.items():
                    if job_id != "global" and file_path in job_data:
                        return (job_data[file_path], job_id)

        except (FileNotFoundError, json.JSONDecodeError):
            logger.error(f"读取缓存文件失败: {cache_file_path}")
        return (None, None)


class FileMonitor:
    def __init__(self):
        self.observer = Observer()
        self.watcher = strmFileWatcher()
        self.is_running = False

    def start_monitoring(self, watch_dir):
        """启动文件监控"""
        if not self.is_running:
            logger.info(f"启动文件监控: {watch_dir}")
            self.observer.schedule(self.watcher, watch_dir, recursive=True)
            self.observer.start()
            self.is_running = True

    def stop_monitoring(self):
        """暂停文件监控"""
        if self.is_running:
            logger.info("暂停文件监控")
            self.observer.stop()
            self.observer.join()
            self.is_running = False

    def restart_monitoring(self, watch_dir):
        """恢复文件监控"""
        self.stop_monitoring()
        self.observer = Observer()  # 重新创建Observer实例
        self.start_monitoring(watch_dir)
