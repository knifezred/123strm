import asyncio
import uvicorn
from croniter import croniter
from datetime import datetime
import pytz

from . import __version__
from .cloud_api import clean_download_url_cache, heartbeat
from .config_manager import display_config_overview, config_manager
from .job_manager import job_manager
from .route import local302Api
from . import logger

# 全局任务引用
cron_task = None


async def run_scheduler():
    """
    运行定时任务调度器 - 使用asyncio实现
    """
    # 开启即运行
    if config_manager.get("running_on_start", default=False):
        await job_manager.run_all_jobs()

    if config_manager.get("watch_delete"):
        # 启动文件删除监控
        from .file_manager import file_manager

        file_manager.start_monitoring("/media/")

    try:
        logger.info("启动任务调度器")
        await schedule_job()
        while True:
            config_manager.check_config_update()
            await clean_expired_cache()
            await asyncio.sleep(30)
    except Exception as e:
        logger.error(f"定时任务调度器循环失败, 错误信息: {str(e)}")


async def schedule_job():
    """
    根据cron表达式调度任务 - 使用asyncio实现
    """
    global cron_task

    # 取消现有任务
    if cron_task and not cron_task.done():
        cron_task.cancel()
        try:
            await cron_task
        except asyncio.CancelledError:
            pass

    cron_str = config_manager.get("cron", default="0 1 * * *")
    cron = croniter(cron_str, datetime.now())
    next_time = cron.get_next(datetime)

    # 计算下次执行的时间差
    now = datetime.now()
    time_diff = (next_time - now).total_seconds()

    logger.info(f"下次执行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 调度下一次执行
    cron_task = asyncio.create_task(run_delayed_job(time_diff))


async def run_delayed_job(delay_seconds):
    """
    延迟执行任务
    """
    try:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        await job_manager.run_all_jobs()
        # 重新调度下一次执行
        await schedule_job()
    except asyncio.CancelledError:
        logger.info("定时任务已取消")
    except Exception as e:
        logger.error(f"定时任务执行失败, 错误信息: {str(e)}")
        # 即使出错也重新调度
        await schedule_job()


async def clean_expired_cache():
    """清理过期缓存项"""
    # 清理下载URL缓存
    await clean_download_url_cache()

    # 心跳检测 - 由于heartbeat已经改为异步函数，我们需要异步调用它
    job_ids = config_manager.get_job_ids()
    if job_ids:
        # 创建心跳任务列表
        heartbeat_tasks = []
        for job_id in job_ids:
            # 为每个任务ID创建一个心跳任务
            heartbeat_tasks.append(asyncio.create_task(heartbeat(job_id)))

        # 等待所有心跳任务完成
        if heartbeat_tasks:
            await asyncio.gather(*heartbeat_tasks, return_exceptions=True)


async def main():
    """
    主函数，同时启动API服务和定时任务
    """
    if not display_config_overview():
        print("配置管理器未初始化，无法继续示例")
        return

    logger.info(f"123strm v{__version__} 已启动")

    server = uvicorn.Server(
        config=uvicorn.Config(app=local302Api, host="0.0.0.0", port=1236)
    )
    await asyncio.gather(run_scheduler(), server.serve())


if __name__ == "__main__":
    asyncio.run(main())
