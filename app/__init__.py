"""
123strm应用包初始化文件

包含应用核心模块的导入和初始化逻辑
"""

# 包版本信息
__version__ = "1.8.1"

# 延迟导入以避免循环依赖
logger = None
config = None


def init_app():
    """
    延迟初始化应用组件
    """
    global logger, config
    from .simple_logger import setup_logger

    logger = setup_logger()

    from .utils import load_config

    config = load_config()


init_app()

# 基础导入
from . import utils
from . import api
