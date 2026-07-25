#!/usr/bin/env python3
import json
import os
import time
import threading
import logging
from pathlib import Path
from flask import Flask, render_template, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)
from hls_downloader import download_ts, format_size, format_time

app = Flask(__name__)

CONFIG_DIR = Path("/data/config")
DOWNLOAD_DIR = Path("/data/downloads")
TASKS_FILE = CONFIG_DIR / "tasks.json"

# 下载任务管理
download_tasks = {}
download_lock = threading.Lock()

def load_tasks():
    if TASKS_FILE.exists():
        with open(TASKS_FILE) as f:
            return json.load(f)
    return {"tasks": []}

def save_tasks(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(TASKS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def extract_m3u8_from_page(page_url):
    import re
    import json
    from urllib.parse import urljoin
    
    logger.info(f"尝试从页面提取 m3u8: {page_url}")
    
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(page_url, timeout=30)
    except ImportError:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": page_url
        }
        resp = requests.get(page_url, headers=headers, timeout=30)
    
    logger.info(f"页面响应状态: {resp.status_code}, 长度: {len(resp.text)}")
    
    # 方法1: var player_aaaa={...}
    match = re.search(r'var\s+player_aaaa\s*=\s*(\{.*?\})\s*;', resp.text, re.DOTALL)
    if match:
        try:
            player_data = json.loads(match.group(1))
            m3u8_url = player_data.get("url", "")
            if m3u8_url:
                logger.info(f"从 player_aaaa 提取到 m3u8: {m3u8_url}")
                return m3u8_url
        except json.JSONDecodeError as e:
            logger.warning(f"解析 player_aaaa 失败: {e}")
    
    # 方法2: 直接匹配 m3u8 URL
    match = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', resp.text)
    if match:
        m3u8_url = match.group(1)
        logger.info(f"从页面匹配到 m3u8: {m3u8_url}")
        return m3u8_url
    
    raise Exception("无法从页面提取 m3u8 地址，页面可能有 Cloudflare 防护")


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    return jsonify(load_tasks())

@app.route("/api/tasks", methods=["POST"])
def add_task():
    data = request.json
    input_url = data.get("m3u8_url")
    title = data.get("title", "video")
    output_dir = data.get("output_dir", "")

    if not input_url:
        return jsonify({"error": "请提供视频链接或 m3u8 地址"}), 400

    tasks_data = load_tasks()
    existing_ids = [t["id"] for t in tasks_data["tasks"]]
    new_id = str(max([int(i) for i in existing_ids] + [0]) + 1)

    if not output_dir:
        output_dir = str(DOWNLOAD_DIR / title)

    new_task = {
        "id": new_id,
        "m3u8_url": input_url,
        "title": title,
        "output_dir": output_dir,
        "status": "pending",
        "progress": 0,
        "total": 0,
        "downloaded": 0,
        "failed": 0,
        "total_size": 0,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    tasks_data["tasks"].append(new_task)
    save_tasks(tasks_data)

    # 启动下载线程
    thread = threading.Thread(target=run_download, args=(new_task,), daemon=True)
    thread.start()

    return jsonify({"success": True, "task": new_task})

@app.route("/api/tasks/<task_id>/retry", methods=["POST"])
def retry_task(task_id):
    tasks_data = load_tasks()
    for task in tasks_data["tasks"]:
        if task["id"] == task_id:
            task["status"] = "pending"
            task["progress"] = 0
            task["error"] = ""
            save_tasks(tasks_data)
            
            thread = threading.Thread(target=run_download, args=(task,), daemon=True)
            thread.start()
            break
    return jsonify({"success": True})

@app.route("/api/tasks/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    with download_lock:
        if task_id in download_tasks:
            download_tasks[task_id]["cancelled"] = True
    
    tasks_data = load_tasks()
    for task in tasks_data["tasks"]:
        if task["id"] == task_id:
            task["status"] = "cancelled"
            save_tasks(tasks_data)
            break
    return jsonify({"success": True})

@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    tasks_data = load_tasks()
    tasks_data["tasks"] = [t for t in tasks_data["tasks"] if t["id"] != task_id]
    save_tasks(tasks_data)
    return jsonify({"success": True})

def run_download(task):
    task_id = task["id"]
    
    with download_lock:
        download_tasks[task_id] = {"cancelled": False}
    
    # 更新状态
    tasks_data = load_tasks()
    for t in tasks_data["tasks"]:
        if t["id"] == task_id:
            t["status"] = "downloading"
            save_tasks(tasks_data)
            break
    
    try:
        import requests
        from urllib.parse import urljoin
        from concurrent.futures import ThreadPoolExecutor, as_completed

        m3u8_url = task["m3u8_url"]
        output_dir = Path(task["output_dir"])
        title = task["title"]
        
        logger.info(f"开始下载: {title}, 输入URL: {m3u8_url}")
        
        # 判断是否为页面URL还是m3u8链接
        if not m3u8_url.endswith(".m3u8") and "m3u8" not in m3u8_url:
            logger.info("检测到页面URL，尝试提取m3u8...")
            m3u8_url = extract_m3u8_from_page(m3u8_url)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        ts_dir = output_dir / "temp_ts"
        ts_dir.mkdir(exist_ok=True)

        # 获取 m3u8
        import requests as req
        resp = req.get(m3u8_url, timeout=30)
        logger.info(f"m3u8 响应状态: {resp.status_code}")
        if "#EXT-X-STREAM-INF" in resp.text:
            for line in resp.text.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    m3u8_url = urljoin(m3u8_url, line)
                    resp = requests.get(m3u8_url, timeout=30)
                    break

        segments = [line.strip() for line in resp.text.strip().split("\n") 
                    if line.strip() and not line.startswith("#")]

        total = len(segments)
        logger.info(f"共 {total} 个片段")
        start_time = time.time()

        def update_progress(downloaded, failed, total_size):
            tasks_data = load_tasks()
            for t in tasks_data["tasks"]:
                if t["id"] == task_id:
                    t["total"] = total
                    t["downloaded"] = downloaded
                    t["failed"] = failed
                    t["total_size"] = total_size
                    t["progress"] = round((downloaded + failed) / total * 100) if total > 0 else 0
                    save_tasks(tasks_data)
                    break

        # 下载片段
        from hls_downloader import download_ts as dl_ts, RETRY_TIMES, MIN_SEGMENT_SIZE

        downloaded = 0
        failed = 0
        total_size = 0

        tasks_args = []
        for i, seg in enumerate(segments):
            if not seg.startswith("http"):
                seg = urljoin(m3u8_url, seg)
            ts_file = ts_dir / f"seg_{i:05d}.ts"
            tasks_args.append((seg, ts_file, i, total, RETRY_TIMES))

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(dl_ts, t): t for t in tasks_args}
            for future in as_completed(futures):
                # 检查取消
                with download_lock:
                    if download_tasks.get(task_id, {}).get("cancelled"):
                        executor.shutdown(wait=False, cancel_futures=True)
                        return

                success, index, size, status = future.result()
                if success:
                    if status == "skip":
                        pass
                    else:
                        downloaded += 1
                    total_size += size
                else:
                    failed += 1
                    logger.warning(f"片段 {index} 下载失败: {status}")

                update_progress(downloaded, failed, total_size)
        
        logger.info(f"下载完成: {downloaded} 成功, {failed} 失败, 总大小: {total_size/1024/1024:.1f}MB")

        # 合并
        ts_files = sorted(ts_dir.glob("seg_*.ts"))
        ts_files = [f for f in ts_files if f.stat().st_size > MIN_SEGMENT_SIZE]

        output_file = output_dir / f"{title}.mp4"
        with open(output_file, "wb") as outfile:
            for ts_file in ts_files:
                with open(ts_file, "rb") as infile:
                    while True:
                        chunk = infile.read(1024*1024)
                        if not chunk:
                            break
                        outfile.write(chunk)

        # 清理
        for ts_file in ts_files:
            ts_file.unlink()
        ts_dir.rmdir()

        # 更新状态
        tasks_data = load_tasks()
        for t in tasks_data["tasks"]:
            if t["id"] == task_id:
                t["status"] = "completed"
                t["progress"] = 100
                save_tasks(tasks_data)
                break

    except Exception as e:
        logger.error(f"下载失败: {e}")
        tasks_data = load_tasks()
        for t in tasks_data["tasks"]:
            if t["id"] == task_id:
                t["status"] = "failed"
                t["error"] = str(e)
                save_tasks(tasks_data)
                break

if __name__ == "__main__":
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8080)
