import asyncio
from croniter import croniter
from datetime import datetime

from . import logger
from .config_manager import config_manager
from .job_manager import job_manager
from .cloud_api import clean_download_url_cache, heartbeat
from .file_manager import file_manager


class TaskScheduler:
    """
    任务调度器类 - 封装所有调度逻辑和状态
    """
    def __init__(self):
        self._cron_task = None
        self._running = False

    async def start(self):
        """启动调度器"""
        if self._running:
            logger.warning("调度器已经在运行中")
            return
        
        self._running = True
        logger.info("启动任务调度器")
        
        # 开启即运行
        if config_manager.get("running_on_start", default=False):
            await job_manager.run_all_jobs()

        if config_manager.get("watch_delete"):
            # 启动文件删除监控
            file_manager.start_monitoring("/media/")
        
        # 开始调度循环
        await self._scheduler_loop()
        
    async def stop(self):
        """停止调度器"""
        self._running = False
        
        # 取消当前任务
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                logger.info("定时任务已取消")
        
        logger.info("任务调度器已停止")

    async def _scheduler_loop(self):
        """调度器主循环"""
        try:
            # 第一次调度
            await self._schedule_job()
            
            # 定期检查配置更新和清理缓存
            while self._running:
                config_manager.check_config_update()
                await self._clean_expired_cache()
                await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"定时任务调度器循环失败, 错误信息: {str(e)}")
            self._running = False

    async def _schedule_job(self):
        """调度下一次任务执行"""
        # 取消现有任务（如果有）
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass
        
        # 获取cron表达式并计算下次执行时间
        cron_str = config_manager.get("cron", default="0 1 * * *")
        cron = croniter(cron_str, datetime.now())
        next_time = cron.get_next(datetime)
        
        # 计算时间差
        now = datetime.now()
        time_diff = (next_time - now).total_seconds()
        
        logger.info(f"下次执行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 创建新的延迟执行任务
        self._cron_task = asyncio.create_task(self._run_delayed_job(time_diff))

    async def _run_delayed_job(self, delay_seconds):
        """延迟执行任务"""
        try:
            if delay_seconds > 0 and self._running:
                await asyncio.sleep(delay_seconds)
            
            if self._running:
                await job_manager.run_all_jobs()
                # 重新调度下一次执行
                await self._schedule_job()
        except asyncio.CancelledError:
            logger.info("定时任务已取消")
        except Exception as e:
            logger.error(f"定时任务执行失败, 错误信息: {str(e)}")
            # 即使出错也重新调度（如果调度器仍在运行）
            if self._running:
                await self._schedule_job()

    async def _clean_expired_cache(self):
        """清理过期缓存项"""
        # 清理下载URL缓存
        await clean_download_url_cache()

        # 心跳检测
        job_ids = config_manager.get_job_ids()
        if job_ids and self._running:
            # 创建心跳任务列表
            heartbeat_tasks = []
            for job_id in job_ids:
                heartbeat_tasks.append(asyncio.create_task(heartbeat(job_id)))
            
            # 等待所有心跳任务完成
            if heartbeat_tasks:
                await asyncio.gather(*heartbeat_tasks, return_exceptions=True)


# 创建全局任务调度器实例
task_scheduler = TaskScheduler()