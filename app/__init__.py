"""
123strm应用包初始化文件

包含应用核心模块的导入和初始化逻辑
"""

# 包版本信息
__version__ = "2.0.0"

logger = None


def init_app():
    """
    延迟初始化应用组件
    """
    global logger
    from .logger import setup_logger

    logger = setup_logger()


init_app()

# 基础导入
from . import cloud_api
from . import utils
