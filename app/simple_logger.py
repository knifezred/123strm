import logging
from logging.handlers import RotatingFileHandler
import os


class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[94m",
        "INFO": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "CRITICAL": "\033[95m",
        "RESET": "\033[0m",
    }

    def format(self, record):
        levelname = record.levelname
        color = self.COLORS.get(levelname, "")
        record.levelname = f"{color}{levelname}{self.COLORS['RESET']}"
        return super().format(record)


def setup_logger():
    """
    配置全局日志记录器
    :return: 配置好的logger对象
    """
    # 创建logs目录
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 创建logger
    logger = logging.getLogger("123strm")
    logger.setLevel(logging.INFO)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 文件处理器
    file_handler = RotatingFileHandler(
        f"{log_dir}/123strm.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)

    formatter = ColoredFormatter(
        "%(levelname)s:     [%(asctime)s]  %(message)s", datefmt="%m-%d %H:%M:%S"
    )
    # formatter = logging.Formatter(
    #     "%(levelname)s: [%(asctime)s] %(message)s",
    #     datefmt="%m-%d %H:%M:%S",
    # )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # 添加处理器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
