from typing import Dict, Optional, Union, Callable
import traceback

from . import logger
from .exceptions import (
    StrmAppError,
    ConfigError,
    ApiError,
    FileError,
    JobError,
    ValidationError,
)


def handle_exception(
    e: Exception,
    error_type: str = "general",
    context: Optional[Dict] = None,
    re_raise: bool = False,
) -> bool:
    """\
    统一异常处理函数
    
    Args:
        e: 捕获的异常对象
        error_type: 错误类型标识
        context: 错误发生时的上下文信息
        re_raise: 是否重新抛出异常
    
    Returns:
        bool: 是否成功处理了异常
    """
    context = context or {}
    error_info = {
        "error_type": error_type,
        "context": context,
        "traceback": traceback.format_exc(),
    }

    # 根据异常类型记录不同级别的日志
    if isinstance(e, StrmAppError):
        # 自定义异常的处理
        error_info.update({"error_code": e.error_code, "details": e.details})

        if error_type == "config":
            logger.error(f"配置错误({e.error_code}): {e.message} - 上下文: {context}")
        elif error_type == "api":
            logger.error(f"API错误({e.error_code}): {e.message} - 上下文: {context}")
        elif error_type == "file":
            logger.error(f"文件错误({e.error_code}): {e.message} - 上下文: {context}")
        elif error_type == "job":
            logger.error(f"任务错误({e.error_code}): {e.message} - 上下文: {context}")
        elif error_type == "validation":
            logger.error(f"验证错误({e.error_code}): {e.message} - 上下文: {context}")
        else:
            logger.error(f"应用错误({e.error_code}): {e.message} - 上下文: {context}")
    else:
        # 系统异常的处理
        logger.error(f"未处理的系统异常: {str(e)} - 上下文: {context}")
        logger.debug(f"异常堆栈: {traceback.format_exc()}")

    if re_raise:
        raise

    return True


def log_debug(message: str, context: Optional[Dict] = None) -> None:
    """\
    记录调试级别日志
    
    Args:
        message: 日志消息
        context: 上下文信息
    """
    context_str = f" - 上下文: {context}" if context else ""
    logger.debug(f"{message}{context_str}")


def log_info(message: str, context: Optional[Dict] = None) -> None:
    """\
    记录信息级别日志
    
    Args:
        message: 日志消息
        context: 上下文信息
    """
    context_str = f" - 上下文: {context}" if context else ""
    logger.info(f"{message}{context_str}")


def log_warning(message: str, context: Optional[Dict] = None) -> None:
    """\
    记录警告级别日志
    
    Args:
        message: 日志消息
        context: 上下文信息
    """
    context_str = f" - 上下文: {context}" if context else ""
    logger.warning(f"{message}{context_str}")


def log_error(
    message: str, context: Optional[Dict] = None, exc_info: bool = False
) -> None:
    """\
    记录错误级别日志
    
    Args:
        message: 日志消息
        context: 上下文信息
        exc_info: 是否包含异常信息
    """
    context_str = f" - 上下文: {context}" if context else ""
    logger.error(f"{message}{context_str}", exc_info=exc_info)


def with_error_handling(
    func: Callable,
    error_type: str = "general",
    re_raise: bool = False,
    default_return: any = None,
) -> Callable:
    """\
    错误处理装饰器
    
    Args:
        func: 被装饰的函数
        error_type: 错误类型标识
        re_raise: 是否重新抛出异常
        default_return: 发生错误时的默认返回值
    
    Returns:
        Callable: 包装后的函数
    """

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # 提取函数名和参数作为上下文
            context = {"function": func.__name__, "args": args, "kwargs": kwargs}
            handle_exception(e, error_type, context, re_raise)
            return default_return

    # 保留原函数的元数据
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    wrapper.__module__ = func.__module__

    return wrapper


# 为了向后兼容，提供与原始日志模块相同的接口
log = logger
