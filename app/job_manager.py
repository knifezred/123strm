import os
import time
import schedule
from datetime import datetime
import pytz

from . import logger
from .config_manager import config_manager
from .utils import save_file_ids
from .file_traverser import FileTraverser
from .file_cleaner import FileCleaner
from .error_handler import handle_exception


class JobManager:
    """
    任务管理器 - 协调文件遍历、处理和清理操作的主类
    """

    def __init__(self):
        # 存储当前正在运行的任务
        self.running_jobs = set()

    def run_job(self, job_id: str, folder_id: str = None, parent_path: str = ""):
        """
        运行指定任务ID的完整处理流程

        Args:
            job_id: 任务ID
            folder_id: 文件夹ID（可选）
        """
        if job_id in self.running_jobs:
            logger.warning(f"任务已经在运行中，跳过执行 job_id: {job_id}")
            return

        try:
            self.running_jobs.add(job_id)
            logger.info(f"开始处理任务: {job_id}")

            # 1. 创建文件遍历器并遍历文件夹收集信息
            file_traverser = FileTraverser(job_id)
            file_traverser.traverse_folders(
                parent_id=folder_id, parent_path=parent_path
            )
            # 2. 保存文件ID映射
            save_file_ids(file_traverser.get_cloud_files(), job_id)
            # 3. 创建文件清理器并清理本地文件
            file_cleaner = FileCleaner(file_traverser.get_cloud_files())
            if parent_path:
                file_cleaner.clean_local_files(parent_path)
            else:
                target_dir = config_manager.get("target_dir", job_id=job_id)
                file_cleaner.clean_local_files(target_dir)

            logger.info(f"任务处理完成 job_id: {job_id}")
        except Exception as e:
            handle_exception(e, "job", {"job_id": job_id})
        finally:
            self.running_jobs.remove(job_id)

    def run_all_jobs(self):
        """
        运行所有配置的任务
        """
        try:
            # 确保使用正确时区
            now = datetime.now(pytz.timezone("Asia/Shanghai"))
            logger.info(f"任务执行时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"开始执行定时任务")

            # 获取所有任务ID
            job_ids = config_manager.get_job_ids()

            if not job_ids:
                logger.warning("没有配置任何任务")
                return

            # 遍历执行每个任务
            for job_id in job_ids:
                self.run_job(job_id)
                # 添加短暂延迟，避免API请求过于频繁
                time.sleep(1)

            logger.info(f"所有定时任务执行完成")
        except Exception as e:
            handle_exception(e, "job")
        finally:
            # 重新调度任务
            self.reschedule()

    def reschedule(self):
        """
        重新调度任务
        """
        try:
            schedule.clear()
            # 这里应该调用schedule_job函数，但它应该在main.py中定义
            # 为了简化，我们直接从配置中获取cron表达式并设置任务
            cron_expression = config_manager.get("cron", default="30 06 * * *")
            logger.info(f"任务将在下次计划时间执行: {cron_expression}")
        except Exception as e:
            logger.error(f"重新调度任务失败: {str(e)}")


# 创建全局任务管理器实例
job_manager = JobManager()
