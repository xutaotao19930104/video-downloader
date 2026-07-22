# downloader.py
import time
import requests
from pathlib import Path


class Downloader:
    def __init__(self, speed_limit=0, chunk_size=1024 * 1024 * 8):
        self.speed_limit = speed_limit
        self.chunk_size = chunk_size
        self.downloaded = 0
        self.start_time = 0

    def download(self, url, filepath, filename, callback=None):
        filepath = Path(filepath)
        filepath.mkdir(parents=True, exist_ok=True)

        full_path = filepath / filename
        temp_path = filepath / f"{filename}.tmp"

        headers = {}
        downloaded_size = 0
        if temp_path.exists():
            downloaded_size = temp_path.stat().st_size
            headers["Range"] = f"bytes={downloaded_size}-"

        for attempt in range(3):
            try:
                resp = requests.get(url, headers=headers, stream=True, timeout=30)
                total_size = int(resp.headers.get("content-length", 0))

                if resp.status_code == 200:
                    downloaded_size = 0
                    mode = "wb"
                elif resp.status_code == 206:
                    mode = "ab"
                else:
                    return False

                self.downloaded = downloaded_size
                self.start_time = time.time()

                with open(temp_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)
                            self.downloaded += len(chunk)
                            self._print_progress(total_size, callback)

                temp_path.rename(full_path)
                return True

            except Exception as e:
                if attempt < 2:
                    time.sleep(3)
                    continue
                return False

        return False

    def _print_progress(self, total_size, callback=None):
        if total_size <= 0:
            return

        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return

        speed = self.downloaded / elapsed / 1024 / 1024
        progress = self.downloaded / total_size * 100

        if callback:
            callback(progress, speed, total_size)
        else:
            if speed > 0:
                remaining = (total_size - self.downloaded) / speed
                remaining_str = f"{remaining:.0f}s"
            else:
                remaining_str = "计算中..."
            print(
                f"\r  进度: {progress:.1f}% | 速度: {speed:.2f} MB/s | 剩余: {remaining_str}",
                end="",
            )
