import os
import yaml
import threading
from typing import Any, Optional, Dict, List, Union
import shutil
import time

# 避免循环导入，使用延迟导入logger
logger = None


def _get_logger():
    global logger
    if logger is None:
        try:
            from . import logger as app_logger

            logger = app_logger
        except ImportError:
            # 如果无法导入app.logger，创建一个简单的日志记录器
            import logging

            temp_logger = logging.getLogger("config_manager")
            temp_logger.setLevel(logging.INFO)
            if not temp_logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter(
                    "%(levelname)s: [%(asctime)s] %(message)s", datefmt="%m-%d %H:%M:%S"
                )
                handler.setFormatter(formatter)
                temp_logger.addHandler(handler)
            logger = temp_logger
    return logger


class ConfigManager:
    """
    配置管理类，提供线程安全的配置加载、访问、更新和保存功能
    支持123strm项目的YAML格式配置文件管理

    设计原则:
    - 线程安全：使用可重入锁确保在多线程环境下安全操作
    - 错误处理：提供明确的异常类型和详细的错误信息
    - 防御性编程：处理所有可能的边界情况和错误场景
    - 易于扩展：设计灵活，方便未来添加新功能
    """

    def __init__(self, config_file: str = "config.yml", backup_enabled: bool = True):
        """
        初始化配置管理器

        Args:
            config_file: 配置文件名称
            backup_enabled: 是否启用配置备份功能

        Raises:
            ConfigLoadError: 当配置文件初始化失败时
        """
        self._config_folder = "config/"
        self._config_path = os.path.join(self._config_folder, config_file)
        self._backup_enabled = backup_enabled
        self._config: Dict[str, Any] = {}
        self._lock = threading.RLock()  # 使用可重入锁保证线程安全
        self._last_modified_time = 0
        self._initialized = False

        try:
            # 加载配置文件
            self.load()
            self._initialized = True
        except Exception as e:
            _get_logger().error(f"配置管理器初始化失败: {str(e)}")
            raise

    def load(self) -> None:
        """
        从文件加载配置

        Raises:
            ConfigLoadError: 当配置文件加载失败时
        """
        with self._lock:
            try:
                # 确保配置目录存在
                config_dir = os.path.dirname(self._config_path)
                if not os.path.exists(config_dir):
                    os.makedirs(config_dir, exist_ok=True)
                    # 创建默认配置文件
                    self._create_default_config()
                    return

                # 检查文件是否存在
                if not os.path.exists(self._config_path):
                    self._create_default_config()
                    return

                # 检查文件修改时间，避免不必要的重新加载
                current_modified_time = os.path.getmtime(self._config_path)
                if current_modified_time <= self._last_modified_time:
                    return

                # 加载配置文件
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}

                self._last_modified_time = current_modified_time
                _get_logger().info(f"配置文件加载成功: {self._config_path}")

            except yaml.YAMLError as e:
                raise ConfigLoadError(f"配置文件格式错误: {str(e)}")
            except IOError as e:
                _get_logger().error(f"配置文件读取失败: {str(e)}")
                raise ConfigLoadError(f"配置文件读取失败: {str(e)}")

    def _create_default_config(self) -> None:
        """创建默认配置文件，基于项目实际配置格式"""
        default_config = {
            "cache_expire_time": 900,
            "cron": "30 06 * * *",
            "use_302_url": True,
            "proxy": "http://127.0.0.1:1236",
            "path_prefix": "/",
            "target_dir": "/media/",
            "flatten_mode": False,
            "video_extensions": [".mp4", ".mkv", ".ts", ".iso"],
            "subtitle": False,
            "subtitle_extensions": [".srt", ".ass", ".sub"],
            "image": False,
            "image_extensions": [".jpg", ".jpeg", ".png", ".webp"],
            "download_image_suffix": [],
            "nfo": False,
            "overwrite": False,
            "min_file_size": 10485760,
            "running_on_start": False,
            "watch_delete": False,
            "client_id": "",
            "client_secret": "",
            "clean_local": False,
            "job_list": [],
        }

        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    default_config, f, allow_unicode=True, default_flow_style=False
                )
            self._config = default_config
            self._last_modified_time = os.path.getmtime(self._config_path)
            _get_logger().info(f"默认配置文件已创建: {self._config_path}")
        except IOError as e:
            _get_logger().error(f"创建默认配置文件失败: {str(e)}")
            raise ConfigLoadError(f"创建默认配置文件失败: {str(e)}")

    def get(self, key: str, job_id: Optional[str] = None, default: Any = None) -> Any:
        """
        获取配置值

        Args:
            key: 配置项键名
            job_id: 可选的任务ID，用于获取特定任务的配置
            default: 默认值，如果配置项不存在则返回

        Returns:
            配置值或默认值
        """
        with self._lock:
            # 首先尝试从任务特定配置中获取
            if job_id is not None:
                job_config = self._get_job_config(job_id)
                if job_config is not None and key in job_config:
                    return job_config[key]

            # 然后尝试从全局配置中获取
            if key in self._config:
                return self._config[key]

            # 最后返回默认值
            if default is not None:
                return default
            demo_default_config = {
                "cache_expire_time": 300,
                "cron": "00 01 * * *",
                "use_302_url": True,
                "proxy": "http://127.0.0.1:1236",
                "path_prefix": "/",
                "target_dir": "/media/",
                "flatten_mode": False,
                "video_extensions": [".mp4", ".mkv", ".ts", ".iso"],
                "subtitle": False,
                "subtitle_extensions": [".srt", ".ass", ".sub"],
                "image": False,
                "image_extensions": [".jpg", ".jpeg", ".png", ".webp"],
                "download_image_suffix": [],
                "nfo": False,
                "overwrite": False,
                "min_file_size": 10485760,
                "running_on_start": False,
                "watch_delete": False,
                "client_id": "",
                "client_secret": "",
            }
            if key in demo_default_config:
                return demo_default_config[key]
            _get_logger().warning(f"配置项 {key} 不存在, 且不存在默认值")
            return None

    def get_all(self) -> Dict[str, Any]:
        """
        获取所有配置

        Returns:
            配置字典的深拷贝
        """
        with self._lock:
            # 返回深拷贝以防止外部修改
            import copy

            return copy.deepcopy(self._config)

    def set(self, key: str, value: Any, job_id: Optional[str] = None) -> None:
        """
        设置配置值

        Args:
            key: 配置项键名
            value: 配置值
            job_id: 可选的任务ID，用于设置特定任务的配置
        """
        with self._lock:
            if job_id is not None:
                # 确保job_list存在
                if "job_list" not in self._config:
                    self._config["job_list"] = []

                # 查找或创建任务配置
                job_config = self._get_job_config(job_id)
                if job_config is None:
                    job_config = {"id": job_id}
                    self._config["job_list"].append(job_config)

                # 设置任务特定配置
                job_config[key] = value
            else:
                # 设置全局配置
                self._config[key] = value

    def update(self, new_config: Dict[str, Any]) -> None:
        """
        批量更新配置

        Args:
            new_config: 包含要更新的配置项的字典
        """
        with self._lock:
            for key, value in new_config.items():
                self._config[key] = value

    def save(self) -> None:
        """
        保存配置到文件

        Raises:
            ConfigSaveError: 当配置保存失败时
        """
        with self._lock:
            try:
                # 备份现有配置
                if self._backup_enabled and os.path.exists(self._config_path):
                    backup_path = f"{self._config_path}.bak.{int(time.time())}"
                    shutil.copy2(self._config_path, backup_path)
                    _get_logger().info(f"配置文件已备份到: {backup_path}")

                # 保存配置
                with open(self._config_path, "w", encoding="utf-8") as f:
                    yaml.dump(
                        self._config, f, allow_unicode=True, default_flow_style=False
                    )

                self._last_modified_time = os.path.getmtime(self._config_path)
                _get_logger().info(f"配置已保存到: {self._config_path}")

            except IOError as e:
                _get_logger().error(f"配置文件保存失败: {str(e)}")
                raise ConfigSaveError(f"配置文件保存失败: {str(e)}")

    def validate(self) -> bool:
        """
        验证配置的有效性，采用防御性验证策略，不轻易抛出异常

        Returns:
            配置是否有效
        """
        with self._lock:
            # 首先检查配置是否已初始化
            if not self._initialized or not isinstance(self._config, dict):
                _get_logger().warning("配置未初始化或格式错误")
                return False

            # 确保job_list存在且为列表类型
            if "job_list" not in self._config:
                self._config["job_list"] = []
                _get_logger().info("配置中缺少job_list，已创建空列表")

            if not isinstance(self._config["job_list"], list):
                _get_logger().warning("job_list必须是列表类型")
                self._config["job_list"] = []
                return False

            # 验证每个任务配置
            valid_jobs_count = 0
            job_ids = set()

            for i, job in enumerate(self._config["job_list"]):
                if not isinstance(job, dict):
                    _get_logger().warning(f"任务配置 #{i} 必须是字典类型")
                    continue

                # 确保任务ID存在且唯一
                if "id" not in job or not job["id"]:
                    job["id"] = f"job_{i}"
                    _get_logger().warning(
                        f"任务 #{i} 缺少id，已分配默认ID: {job['id']}"
                    )

                job_id = job["id"]
                if job_id in job_ids:
                    new_id = f"{job_id}_duplicate_{i}"
                    _get_logger().warning(f"任务ID '{job_id}' 重复，已更改为: {new_id}")
                    job["id"] = new_id
                    job_id = new_id

                job_ids.add(job_id)

                # 确保必要的配置项存在并有合理的默认值
                required_configs = {
                    "target_dir": "",
                    "root_folder_id": "",
                    "path_prefix": "/",
                    "client_id": self._config.get("client_id", ""),
                    "client_secret": self._config.get("client_secret", ""),
                    "image": self._config.get("image", False),
                    "nfo": self._config.get("nfo", False),
                    "subtitle": self._config.get("subtitle", False),
                    "overwrite": self._config.get("overwrite", False),
                    "use_302_url": self._config.get("use_302_url", True),
                }

                for key, default_value in required_configs.items():
                    if key not in job:
                        job[key] = default_value
                        _get_logger().info(
                            f"任务 '{job_id}' 缺少配置 '{key}'，已使用默认值: {default_value}"
                        )

                valid_jobs_count += 1

            # 验证全局配置项
            if "cron" in self._config:
                cron_parts = self._config["cron"].split()
                if len(cron_parts) != 5:
                    _get_logger().warning(
                        f"无效的cron表达式: {self._config['cron']}，已重置为默认值"
                    )
                    self._config["cron"] = "30 06 * * *"
            else:
                self._config["cron"] = "30 06 * * *"

            # 确保媒体扩展名配置存在且为列表类型
            media_configs = {
                "video_extensions": [".mp4", ".mkv", ".ts", ".iso", ".avi", ".m2ts"],
                "subtitle_extensions": [".srt", ".ass", ".sub"],
                "image_extensions": [".jpg", ".jpeg", ".png", ".webp"],
                "download_image_suffix": ["poster", "fanart"],
            }

            for key, default_value in media_configs.items():
                if key not in self._config:
                    self._config[key] = default_value
                elif not isinstance(self._config[key], list):
                    _get_logger().warning(f"{key}必须是列表类型")
                    self._config[key] = default_value

            # 确保数值类型配置项有合理的值
            numeric_configs = {
                "cache_expire_time": 900,
                "min_file_size": 10485760,  # 10MB
            }

            for key, default_value in numeric_configs.items():
                if key not in self._config:
                    self._config[key] = default_value
                elif (
                    not isinstance(self._config[key], (int, float))
                    or self._config[key] < 0
                ):
                    _get_logger().warning(f"{key}必须是正数值")
                    self._config[key] = default_value

            # 确保布尔类型配置项有合理的值
            boolean_configs = {
                "use_302_url": True,
                "flatten_mode": False,
                "image": True,
                "subtitle": True,
                "nfo": True,
                "overwrite": False,
                "running_on_start": False,
                "watch_delete": False,
                "clean_local": False,
            }

            for key, default_value in boolean_configs.items():
                if key not in self._config:
                    self._config[key] = default_value
                elif not isinstance(self._config[key], bool):
                    _get_logger().warning(f"{key}必须是布尔值")
                    self._config[key] = default_value

            _get_logger().info(f"配置验证完成，有效任务数: {valid_jobs_count}")
            return valid_jobs_count > 0

    def _get_job_config(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        获取特定任务的配置

        Args:
            job_id: 任务ID

        Returns:
            任务配置字典，如果不存在则返回None
        """
        if "job_list" not in self._config:
            return None

        for job in self._config["job_list"]:
            if job.get("id") == job_id:
                return job

        return None

    def get_job_ids(self) -> List[str]:
        """
        获取所有任务ID

        Returns:
            任务ID列表
        """
        with self._lock:
            if "job_list" not in self._config:
                return []

            return [job.get("id") for job in self._config["job_list"] if "id" in job]

    def has_job(self, job_id: str) -> bool:
        """
        检查任务是否存在

        Args:
            job_id: 任务ID

        Returns:
            任务是否存在
        """
        return self._get_job_config(job_id) is not None

    def remove_job(self, job_id: str) -> bool:
        """
        移除任务配置

        Args:
            job_id: 任务ID

        Returns:
            是否成功移除
        """
        with self._lock:
            if "job_list" not in self._config:
                return False

            original_length = len(self._config["job_list"])
            self._config["job_list"] = [
                job for job in self._config["job_list"] if job.get("id") != job_id
            ]

            return len(self._config["job_list"]) < original_length

    def get_job_config(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        获取完整的任务配置

        Args:
            job_id: 任务ID

        Returns:
            任务配置的深拷贝，如果不存在则返回None
        """
        with self._lock:
            job_config = self._get_job_config(job_id)
            if job_config is None:
                return None

            # 返回深拷贝以防止外部修改
            import copy

            return copy.deepcopy(job_config)

    def check_config_update(self) -> bool:
        """
        检查配置文件是否被修改，如果被修改则重新加载

        Returns:
            bool: 配置是否被更新
        """
        try:
            if not os.path.exists(self._config_path):
                return False

            current_modified_time = os.path.getmtime(self._config_path)
            with self._lock:
                if current_modified_time > self._last_modified_time:
                    _get_logger().info("检测到配置文件更新，重新加载配置")
                    self.load()
                    return True
            return False
        except Exception as e:
            _get_logger().error(f"检查配置文件更新失败: {str(e)}")
            return False

    def get_config_path(self) -> str:
        """
        获取当前使用的配置文件路径

        Returns:
            str: 配置文件的绝对路径
        """
        return self._config_path

    def get_config_folder(self) -> str:
        """
        获取配置文件夹路径

        Returns:
            配置文件夹的绝对路径
        """
        return self._config_folder

    def is_initialized(self) -> bool:
        """
        检查配置管理器是否已成功初始化

        Returns:
            bool: 是否已初始化
        """
        with self._lock:
            return self._initialized

    def enable_backup(self, enabled: bool) -> None:
        """
        启用或禁用配置备份功能

        Args:
            enabled: 是否启用备份
        """
        with self._lock:
            self._backup_enabled = enabled
            _get_logger().info(f"配置备份功能已{'启用' if enabled else '禁用'}")


def display_config_overview():
    """显示配置概览信息"""
    # 检查配置管理器是否初始化成功
    if config_manager.is_initialized():
        _get_logger().info(f"✅ 配置管理器已成功初始化")
        _get_logger().info(f"📁 配置文件路径: {config_manager.get_config_path()}")
    else:
        _get_logger().error("❌ 配置管理器初始化失败")
        return False

    # 获取全局配置
    _get_logger().info(f"  • 缓存过期时间: {config_manager.get('cache_expire_time')}秒")
    _get_logger().info(f"  • 定时任务表达式: {config_manager.get('cron')}")
    _get_logger().info(
        f"  • 启动后立即生成: {'✅' if config_manager.get('running_on_start') else '❌'}"
    )
    _get_logger().info(
        f"  • 文件删除监听: {'✅' if config_manager.get('watch_delete') else '❌'}"
    )
    _get_logger().info(
        f"  • 本地文件清理: {'✅' if config_manager.get('clean_local') else '❌'}"
    )
    if config_manager.get("watch_delete"):
        # 启动文件删除监控
        from app.file_monitor import FileMonitor

        monitor = FileMonitor()
        monitor.start_monitoring("/media/")
    _get_logger().info(
        f"  • 302转发: {'✅' if config_manager.get('use_302_url') else '❌'}"
    )
    _get_logger().info(
        f"  • 覆盖模式: {'✅' if config_manager.get('overwrite') else '❌'}"
    )
    _get_logger().info(f"  • 代理设置: {config_manager.get('proxy')}")
    from app.utils import convert_byte_size

    _get_logger().info(
        f"  • 最小文件大小: {convert_byte_size(config_manager.get('min_file_size'))}MB"
    )
    _get_logger().info(
        f"  • 视频扩展名: {', '.join(config_manager.get('video_extensions', default=[]))}"
    )

    # 获取任务列表
    job_ids = config_manager.get_job_ids()
    _get_logger().info(f"🔧 已配置的任务数量: {len(job_ids)}")

    if job_ids:
        _get_logger().info("📝 任务详情:")
        for job_id in job_ids:
            _get_logger().info(f"  任务ID: {job_id}")
            job_config = config_manager.get_job_config(job_id)
            if job_config:
                _get_logger().info(f"    • 客户端ID: {job_config.get('client_id')}")
                _get_logger().info(
                    f"    • 根文件夹ID: {job_config.get('root_folder_id')}"
                )
                _get_logger().info(f"    • 目标目录: {job_config.get('target_dir')}")
                _get_logger().info(
                    f"    • 下载图片: {'✅' if job_config.get('image') else '❌'}"
                )
                _get_logger().info(
                    f"    • 下载字幕: {'✅' if job_config.get('subtitle') else '❌'}"
                )
                _get_logger().info(
                    f"    • 下载NFO: {'✅' if job_config.get('nfo') else '❌'}"
                )

    return True


# 创建全局配置管理器实例
try:
    config_manager = ConfigManager()
    _get_logger().info("全局配置管理器初始化成功")
except Exception as e:
    # 如果初始化失败，创建一个基本的配置管理器实例用于错误处理
    class BasicConfigManager:
        def get(
            self, key: str, job_id: Optional[str] = None, default: Any = None
        ) -> Any:
            return default

        def get_all(self) -> Dict[str, Any]:
            return {}

        def set(self, key: str, value: Any, job_id: Optional[str] = None) -> None:
            pass

        def update(self, new_config: Dict[str, Any]) -> None:
            pass

        def save(self) -> None:
            pass

        def validate(self) -> bool:
            return False

        def get_job_ids(self) -> List[str]:
            return []

        def has_job(self, job_id: str) -> bool:
            return False

        def remove_job(self, job_id: str) -> bool:
            return False

        def get_job_config(self, job_id: str) -> Optional[Dict[str, Any]]:
            return None

        def check_config_update(self) -> bool:
            return False

        def get_config_path(self) -> str:
            return ""

        def get_config_folder(self) -> str:
            return ""

        def is_initialized(self) -> bool:
            return False

        def enable_backup(self, enabled: bool) -> None:
            pass

    config_manager = BasicConfigManager()
    _get_logger().error(f"创建全局配置管理器失败，使用基本配置管理器: {str(e)}")
