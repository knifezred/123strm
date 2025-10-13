import os
import yaml
import copy
from typing import Any, Optional, Dict, List, Union
from . import logger


class ConfigManager:
    """
    配置管理类
    负责加载、保存和访问YAML格式的配置文件
    """

    def __init__(self, config_file: str = "config.yml"):
        """初始化配置管理器"""
        self._config_folder = "config/"
        self._config_path = os.path.join(self._config_folder, config_file)
        self._config: Dict[str, Any] = {}
        self._last_modified_time = 0
        self._initialized = False
        self._default_config = {
            "cache_expire_time": 300,
            "cron": "0 01 * * *",
            "client_id": "",
            "client_secret": "",
            "root_folder_id": 0,
            "min_file_size": 10485760,
            "overwrite": False,
            "running_on_start": False,
            "watch_delete": False,
            "clean_local": False,
            "use_302_url": True,
            "proxy": "http://127.0.0.1:1236",
            "path_prefix": "",
            "target_dir": "/media/",
            "flatten_mode": False,
            "video_extensions": [".mp4", ".mkv", ".ts", ".iso"],
            "subtitle": False,
            "subtitle_extensions": [".srt", ".ass", ".sub"],
            "image": False,
            "image_extensions": [".jpg", ".jpeg", ".png", ".webp"],
            "download_image_suffix": [],
            "nfo": True,
            "job_list": [],
        }

        try:
            self.load()
            self._initialized = True
            logger.info("配置管理器初始化成功")
        except Exception as e:
            logger.error(f"配置管理器初始化失败: {str(e)}")
            raise

    def load(self) -> None:
        """从文件加载配置"""
        # 确保配置目录存在
        config_dir = os.path.dirname(self._config_path)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
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
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}

            self._last_modified_time = current_modified_time
            logger.info(f"配置文件加载成功: {self._config_path}")
        except yaml.YAMLError as e:
            logger.error(f"配置文件格式错误: {str(e)}")
            raise
        except IOError as e:
            logger.error(f"配置文件读取失败: {str(e)}")
            raise

    def _create_default_config(self) -> None:
        """创建默认配置文件"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    self._default_config,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                )
            self._config = self._default_config
            self._last_modified_time = os.path.getmtime(self._config_path)
            logger.info(f"默认配置文件已创建: {self._config_path}")
        except IOError as e:
            logger.error(f"创建默认配置文件失败: {str(e)}")
            raise

    def get(self, key: str, job_id: Optional[str] = None, default: Any = None) -> Any:
        """获取配置值"""
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

        # 内置默认值，作为最后的保障
        if key in self._default_config:
            return self._default_config[key]

        logger.warning(f"配置项 {key} 不存在，且无默认值")
        return None

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置（深拷贝）"""
        return copy.deepcopy(self._config)

    def set(self, key: str, value: Any, job_id: Optional[str] = None) -> None:
        """设置配置值"""
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
        """批量更新配置"""
        for key, value in new_config.items():
            self._config[key] = value

    def save(self) -> None:
        """保存配置到文件"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)

            self._last_modified_time = os.path.getmtime(self._config_path)
            logger.info(f"配置已保存到: {self._config_path}")
        except IOError as e:
            logger.error(f"配置文件保存失败: {str(e)}")
            raise

    def _get_job_config(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取特定任务的配置"""
        if "job_list" not in self._config:
            return None

        for job in self._config["job_list"]:
            if job.get("id") == job_id:
                return job

        return None

    def get_job_ids(self) -> List[str]:
        """获取所有任务ID"""
        if "job_list" not in self._config:
            return []

        return [job.get("id") for job in self._config["job_list"] if "id" in job]

    def get_job_config(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取完整的任务配置（深拷贝）"""
        job_config = self._get_job_config(job_id)
        if job_config is None:
            return None

        return copy.deepcopy(job_config)

    def check_config_update(self) -> bool:
        """检查配置文件是否被修改"""
        try:
            if not os.path.exists(self._config_path):
                return False

            current_modified_time = os.path.getmtime(self._config_path)
            if current_modified_time > self._last_modified_time:
                logger.info("检测到配置文件更新，重新加载配置")
                self.load()
                return True
            return False
        except Exception as e:
            logger.error(f"检查配置文件更新失败: {str(e)}")
            return False

    def get_config_path(self) -> str:
        """获取当前使用的配置文件路径"""
        return self._config_path

    def get_config_folder(self) -> str:
        """获取配置文件夹路径"""
        return self._config_folder

    def is_initialized(self) -> bool:
        """检查配置管理器是否已成功初始化"""
        return self._initialized


def display_config_overview() -> bool:
    """显示配置概览信息"""
    # 检查配置管理器是否初始化成功
    if config_manager.is_initialized():
        logger.info(f"✅ 配置管理器已成功初始化")
        logger.info(f"📁 配置文件路径: {config_manager.get_config_path()}")
    else:
        logger.error("❌ 配置管理器初始化失败")
        return False

    # 获取全局配置
    logger.info(
        f"  • 启动后立即执行: {'✅' if config_manager.get('running_on_start') else '❌'}"
    )
    logger.info(
        f"  • 本地文件清理: {'✅' if config_manager.get('clean_local') else '❌'}"
    )
    logger.info(
        f"  • 文件删除监听: {'✅' if config_manager.get('watch_delete') else '❌'}"
    )
    logger.info(f"  • 覆盖模式: {'✅' if config_manager.get('overwrite') else '❌'}")
    logger.info(f"  • 302转发: {'✅' if config_manager.get('use_302_url') else '❌'}")
    logger.info(f"  • 缓存时间: {config_manager.get('cache_expire_time')} 秒")
    logger.info(f"  • 代理设置: {config_manager.get('proxy')}")

    logger.info(f"  • 定时设置: {config_manager.get('cron')}")

    video_exts = config_manager.get("video_extensions", default=[])
    logger.info(f"  • 视频扩展名: {', '.join(video_exts)}")

    # 获取任务列表
    job_ids = config_manager.get_job_ids()
    logger.info(f"🔧 已配置的任务数量: {len(job_ids)}")

    if job_ids:
        logger.info("📝 任务详情:")
        for job_id in job_ids:
            logger.info(f"  任务ID: {job_id}")
            job_config = config_manager.get_job_config(job_id)
            if job_config:
                logger.info(f"    • 客户端ID: {job_config.get('client_id')}")
                logger.info(f"    • 根文件夹ID: {job_config.get('root_folder_id')}")
                logger.info(f"    • 目标目录: {job_config.get('target_dir')}")
                logger.info(
                    f"    • 下载图片: {'✅' if job_config.get('image') else '❌'}"
                )
                logger.info(
                    f"    • 下载字幕: {'✅' if job_config.get('subtitle') else '❌'}"
                )
                logger.info(f"    • 下载NFO: {'✅' if job_config.get('nfo') else '❌'}")

    return True


# 创建全局配置管理器实例
try:
    config_manager = ConfigManager()
except Exception as e:
    logger.critical(f"创建全局配置管理器失败: {str(e)}")
