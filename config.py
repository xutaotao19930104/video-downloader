# config.py
import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".aliyun-downloader/config.json"

DEFAULT_CONFIG = {
    "refresh_token": "",
    "access_token": "",
    "download_dir": str(Path.home() / "Downloads/aliyun-videos"),
    "download_speed_limit": 0,
    "retry_times": 3,
    "retry_delay": 5,
    "chunk_size": 1024 * 1024 * 8,
    "task_file": str(Path.home() / ".aliyun-downloader/tasks.json"),
    "check_interval": 60,
    "enable_web": True,
    "web_port": 8080,
}


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_CONFIG


def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
