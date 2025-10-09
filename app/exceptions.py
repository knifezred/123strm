class StrmAppError(Exception):
    """\应用的基础异常类"""
    def __init__(self, message: str, error_code: int = 1, details: dict = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)


class ConfigError(StrmAppError):
    """\配置相关错误"""
    def __init__(self, message: str, error_code: int = 100, details: dict = None):
        super().__init__(message, error_code, details)


class ApiError(StrmAppError):
    """\API调用相关错误"""
    def __init__(self, message: str, error_code: int = 200, details: dict = None):
        super().__init__(message, error_code, details)


class FileError(StrmAppError):
    """\文件处理相关错误"""
    def __init__(self, message: str, error_code: int = 300, details: dict = None):
        super().__init__(message, error_code, details)


class JobError(StrmAppError):
    """\任务执行相关错误"""
    def __init__(self, message: str, error_code: int = 400, details: dict = None):
        super().__init__(message, error_code, details)


class ValidationError(StrmAppError):
    """\数据验证相关错误"""
    def __init__(self, message: str, error_code: int = 500, details: dict = None):
        super().__init__(message, error_code, details)