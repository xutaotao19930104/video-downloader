#!/usr/bin/env python3
import json
import os
import time
import threading
import subprocess
from pathlib import Path
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CONFIG_DIR = Path("/data/config")
DOWNLOAD_DIR = Path("/data/downloads")
TASKS_FILE = CONFIG_DIR / "tasks.json"

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
    url = data.get("url")
    title = data.get("title", "")
    output_dir = data.get("output_dir", "")

    if not url:
        return jsonify({"error": "请提供视频链接"}), 400

    tasks_data = load_tasks()
    existing_ids = [t["id"] for t in tasks_data["tasks"]]
    new_id = str(max([int(i) for i in existing_ids] + [0]) + 1)

    if not output_dir:
        output_dir = str(DOWNLOAD_DIR / (title or "videos"))

    new_task = {
        "id": new_id,
        "url": url,
        "title": title,
        "output_dir": output_dir,
        "status": "pending",
        "progress": 0,
        "filename": "",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    tasks_data["tasks"].append(new_task)
    save_tasks(tasks_data)

    thread = threading.Thread(target=run_download, args=(new_task,), daemon=True)
    thread.start()

    return jsonify({"success": True, "task": new_task})

@app.route("/api/tasks/<task_id>/retry", methods=["POST"])
def retry_task(task_id):
    tasks_data = load_tasks()
    for task in tasks_data["tasks"]:
        if task["id"] == task_id:
            task["status"] = "pending"
            task["error"] = ""
            save_tasks(tasks_data)
            thread = threading.Thread(target=run_download, args=(task,), daemon=True)
            thread.start()
            break
    return jsonify({"success": True})

@app.route("/api/tasks/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
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
    
    tasks_data = load_tasks()
    for t in tasks_data["tasks"]:
        if t["id"] == task_id:
            t["status"] = "downloading"
            save_tasks(tasks_data)
            break

    try:
        output_dir = Path(task["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        url = task["url"]
        output_template = str(output_dir / "%(title)s.%(ext)s")

        cmd = [
            "yt-dlp",
            "--no-check-certificates",
            "-o", output_template,
            "--newline",
            url
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in process.stdout:
            line = line.strip()
            if "[download]" in line and "%" in line:
                try:
                    percent = float(line.split("%")[0].split()[-1])
                    tasks_data = load_tasks()
                    for t in tasks_data["tasks"]:
                        if t["id"] == task_id:
                            t["progress"] = round(percent)
                            save_tasks(tasks_data)
                            break
                except:
                    pass
            elif "Destination:" in line:
                filename = line.split("Destination:")[-1].strip()
                tasks_data = load_tasks()
                for t in tasks_data["tasks"]:
                    if t["id"] == task_id:
                        t["filename"] = filename
                        save_tasks(tasks_data)
                        break

        process.wait()

        if process.returncode == 0:
            tasks_data = load_tasks()
            for t in tasks_data["tasks"]:
                if t["id"] == task_id:
                    t["status"] = "completed"
                    t["progress"] = 100
                    save_tasks(tasks_data)
                    break
        else:
            raise Exception(f"yt-dlp 返回错误码: {process.returncode}")

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
