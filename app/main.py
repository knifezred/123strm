import time
import schedule
from croniter import croniter
from datetime import datetime
import asyncio
import uvicorn

from . import __version__
from .error_handler import handle_exception
from .cloud_api import clean_download_url_cache, heartbeat
from .config_manager import display_config_overview, config_manager
from .job_manager import job_manager
from .route import local302Api
from . import logger


def clean_expired_cache():
    """清理过期缓存项"""
    clean_download_url_cache()
    # 心跳检测
    job_ids = config_manager.get_job_ids()
    if job_ids:
        for job_id in job_ids:
            heartbeat(job_id)


async def run_scheduler():
    """
    运行定时任务调度器
    """
    # 开启即运行
    if config_manager.get("running_on_start", default=False):
        job_manager.run_all_jobs()
    try:
        logger.info("启动任务调度器")
        schedule_job()
        while True:
            config_manager.check_config_update()
            schedule.run_pending()
            # 清理过期缓存
            clean_expired_cache()
            await asyncio.sleep(30)
    except Exception as e:
        handle_exception(e, "scheduler", {"action": "loop"})


def schedule_job():
    """
    根据cron表达式调度任务
    :param job: 要执行的任务函数
    """
    cron_str = config_manager.get("cron", default="0 1 * * *")
    cron = croniter(cron_str, datetime.now())
    next_time = cron.get_next(datetime)
    # 根据cron表达式设置不同的调度方式
    parts = cron_str.split()
    if len(parts) >= 5:  # 完整cron表达式
        if "*/" in parts[0]:  # 每N分钟执行
            minutes = int(parts[0].split("/")[1])
            logger.info(f"每{minutes}分钟执行一次")
            schedule.every(minutes).minutes.do(job_manager.run_all_jobs)
        elif "*/" in parts[1]:  # 每N小时执行
            hours = int(parts[1].split("/")[1])
            logger.info(f"每{hours}小时执行一次")
            schedule.every(hours).hours.do(job_manager.run_all_jobs)
        elif "*/" in parts[2]:  # 每N天执行
            days = int(parts[2].split("/")[1])
            logger.info(f"每{days}天执行一次")
            schedule.every(days).days.at(next_time.strftime("%H:%M:%S")).do(
                job_manager.run_all_jobs
            )
        elif parts[2] != "*":  # 按月执行
            day_of_month = int(parts[2])
            logger.info(f"每月{day_of_month}号执行一次")
            # 计算距离下次执行的天数
            days_until = (day_of_month - datetime.now().day) % 30
            days_until = 30 if days_until == 0 else days_until
            # 如果是当天，则推迟一个月
            schedule.every(days_until).days.at(next_time.strftime("%H:%M:%S")).do(
                job_manager.run_all_jobs
            )
        elif parts[4] != "*":  # 按周执行
            weekday = int(parts[4])
            logger.info(f"每周{weekday}执行一次")
            # 计算距离下次执行的天数
            days_until = (weekday - datetime.now().weekday()) % 7
            days_until = 7 if days_until == 0 else days_until  # 如果是当天，则推迟一周
            schedule.every(days_until).days.at(next_time.strftime("%H:%M:%S")).do(
                job_manager.run_all_jobs
            )
        else:  # 按具体时间执行
            logger.info(f"每天{next_time.strftime('%H:%M')}执行一次")
            schedule.every().day.at(next_time.strftime("%H:%M:%S")).do(
                job_manager.run_all_jobs
            )

    logger.info(f"下次执行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")


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
