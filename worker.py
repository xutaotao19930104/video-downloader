# worker.py
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from api import AliyunDriveAPI
from downloader import Downloader
from verifier import FileVerifier
from config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/data/logs/worker.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class DownloadWorker:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.task_file = Path(self.config.get("task_file", "tasks.json"))
        self.check_interval = self.config.get("check_interval", 60)
        self.api = AliyunDriveAPI(self.config["refresh_token"])
        self.downloader = Downloader(
            speed_limit=self.config.get("download_speed_limit", 0),
            chunk_size=self.config.get("chunk_size", 1024 * 1024 * 8),
        )
        self.verifier = FileVerifier()

    def load_tasks(self):
        if not self.task_file.exists():
            return []
        with open(self.task_file, "r") as f:
            data = json.load(f)
            return data.get("tasks", [])

    def save_tasks(self, tasks):
        self.task_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.task_file, "w") as f:
            json.dump({"tasks": tasks}, f, indent=2, ensure_ascii=False)

    def process_task(self, task):
        share_url = task["share_url"]
        title = task["title"]

        logger.info(f"开始处理任务: {title}")

        try:
            share_id, folder_id = self.api.parse_share_url(share_url)
            if not share_id:
                logger.error(f"无法解析分享链接: {share_url}")
                return False

            self.api.get_share_token(share_id)
            files = self.api.get_file_list(share_id, folder_id or "root")

            video_files = [
                f
                for f in files
                if f["name"].lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".flv"))
            ]
            if not video_files:
                logger.warning(f"未找到视频文件: {title}")
                return False

            video_files.sort(key=lambda x: x["name"])

            if "episodes" not in task:
                task["episodes"] = []
                for idx, vf in enumerate(video_files, 1):
                    task["episodes"].append(
                        {
                            "id": f"ep{idx:02d}",
                            "name": f"{title} - 第{idx:02d}集.mp4",
                            "file_id": vf["id"],
                            "size": vf.get("size", 0),
                            "status": "pending",
                        }
                    )

            download_dir = Path(self.config["download_dir"]) / title
            download_dir.mkdir(parents=True, exist_ok=True)

            success_count = 0
            for i, ep in enumerate(task["episodes"], 1):
                if ep["status"] == "completed":
                    success_count += 1
                    continue

                logger.info(f"下载第 {i}/{len(task['episodes'])} 个视频: {ep['name']}")

                try:
                    download_url, size = self.api.get_download_url(
                        share_id, ep["file_id"]
                    )
                except Exception as e:
                    logger.error(f"获取下载链接失败: {e}")
                    ep["status"] = "failed"
                    ep["error"] = str(e)
                    continue

                if not download_url:
                    ep["status"] = "failed"
                    ep["error"] = "获取下载链接失败"
                    continue

                ep["size"] = size

                if self.downloader.download(download_url, str(download_dir), ep["name"]):
                    ep["status"] = "completed"
                    ep["downloaded_at"] = datetime.now().isoformat()

                    verify_result = self.verifier.verify(
                        str(download_dir / ep["name"]), ep["size"]
                    )
                    ep["verify_result"] = verify_result
                    if not verify_result["valid"]:
                        ep["status"] = "corrupted"
                        logger.warning(f"文件校验失败: {ep['name']}")
                    else:
                        success_count += 1
                else:
                    ep["status"] = "failed"
                    ep["error"] = "下载失败"

                if i < len(task["episodes"]):
                    time.sleep(3)

            logger.info(
                f"任务完成: {title}, 成功: {success_count}/{len(task['episodes'])}"
            )
            return True

        except Exception as e:
            logger.error(f"任务处理失败: {e}")
            return False

    def run(self):
        logger.info("Worker启动，开始监听任务队列...")

        while True:
            try:
                tasks = self.load_tasks()
                pending_tasks = [t for t in tasks if t["status"] == "pending"]

                if pending_tasks:
                    task = pending_tasks[0]
                    task["status"] = "downloading"
                    self.save_tasks(tasks)

                    success = self.process_task(task)

                    if success:
                        task["status"] = "completed"
                        task["completed_at"] = datetime.now().isoformat()
                    else:
                        task["status"] = "failed"
                        task["failed_at"] = datetime.now().isoformat()

                    self.save_tasks(tasks)

            except Exception as e:
                logger.error(f"Worker循环错误: {e}")

            time.sleep(self.check_interval)


if __name__ == "__main__":
    worker = DownloadWorker()
    worker.run()
