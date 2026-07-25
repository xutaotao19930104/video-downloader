#!/usr/bin/env python3
import json
import os
import time
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify
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

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    return jsonify(load_tasks())

@app.route("/api/tasks", methods=["POST"])
def add_task():
    data = request.json
    m3u8_url = data.get("m3u8_url")
    title = data.get("title", "video")
    output_dir = data.get("output_dir", "")

    if not m3u8_url:
        return jsonify({"error": "请提供 m3u8 地址"}), 400

    tasks_data = load_tasks()
    existing_ids = [t["id"] for t in tasks_data["tasks"]]
    new_id = str(max([int(i) for i in existing_ids] + [0]) + 1)

    if not output_dir:
        output_dir = str(DOWNLOAD_DIR / title)

    new_task = {
        "id": new_id,
        "m3u8_url": m3u8_url,
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
        
        output_dir.mkdir(parents=True, exist_ok=True)
        ts_dir = output_dir / "temp_ts"
        ts_dir.mkdir(exist_ok=True)

        # 获取 m3u8
        resp = requests.get(m3u8_url, timeout=30)
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

                update_progress(downloaded, failed, total_size)

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
