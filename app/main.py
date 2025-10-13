import asyncio
import uvicorn

from . import __version__
from .config_manager import display_config_overview, config_manager
from .route import local302Api
from .scheduler import task_scheduler
from . import logger


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
    
    try:
        # 同时启动调度器和API服务器
        await asyncio.gather(task_scheduler.start(), server.serve())
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序运行出错: {str(e)}")
    finally:
        # 确保调度器正确停止
        await task_scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
