#!/usr/bin/env python3
import requests
import os
import sys
import time
import json
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

RETRY_TIMES = 3
RETRY_DELAY = 2
MIN_SEGMENT_SIZE = 1024

def download_ts(args):
    seg_url, filepath, index, total, retry_times = args
    for attempt in range(retry_times):
        try:
            if filepath.exists() and filepath.stat().st_size > MIN_SEGMENT_SIZE:
                size = filepath.stat().st_size
                return True, index, size, "skip"
            
            resp = requests.get(seg_url, stream=True, timeout=30)
            resp.raise_for_status()
            size = 0
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
                    size += len(chunk)
            return True, index, size, "download"
        except Exception as e:
            if attempt < retry_times - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                if filepath.exists():
                    filepath.unlink()
                return False, index, 0, str(e)

def format_size(bytes_size):
    if bytes_size >= 1024*1024*1024:
        return f"{bytes_size/1024/1024/1024:.2f} GB"
    elif bytes_size >= 1024*1024:
        return f"{bytes_size/1024/1024:.1f} MB"
    elif bytes_size >= 1024:
        return f"{bytes_size/1024:.1f} KB"
    return f"{bytes_size} B"

def format_time(seconds):
    if seconds >= 3600:
        return f"{int(seconds//3600)}h{int((seconds%3600)//60)}m"
    elif seconds >= 60:
        return f"{int(seconds//60)}m{int(seconds%60)}s"
    return f"{int(seconds)}s"

def save_progress(base_dir, progress):
    progress_file = base_dir / ".download_progress.json"
    with open(progress_file, "w") as f:
        json.dump(progress, f, indent=2)

def load_progress(base_dir):
    progress_file = base_dir / ".download_progress.json"
    if progress_file.exists():
        with open(progress_file) as f:
            return json.load(f)
    return None

def main(m3u8_url, output_dir, title):
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    ts_dir = base_dir / "temp_ts"
    ts_dir.mkdir(exist_ok=True)
    output_file = base_dir / f"{title}.mp4"

    print(f"输出目录: {base_dir}")
    print(f"临时目录: {ts_dir}")
    print()

    # 加载上次进度
    saved_progress = load_progress(base_dir)
    if saved_progress and saved_progress.get("m3u8_url") == m3u8_url:
        print(f"检测到上次下载进度: {saved_progress.get('downloaded', 0)}/{saved_progress.get('total', 0)}")

    print("正在获取 m3u8...")
    resp = requests.get(m3u8_url, timeout=30)
    
    # 处理多码率
    if "#EXT-X-STREAM-INF" in resp.text:
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                m3u8_url = urljoin(m3u8_url, line)
                print(f"发现子播放列表: {m3u8_url}")
                resp = requests.get(m3u8_url, timeout=30)
                break

    segments = [line.strip() for line in resp.text.strip().split("\n") 
                if line.strip() and not line.startswith("#")]

    print(f"共 {len(segments)} 个片段\n")

    tasks = []
    for i, seg in enumerate(segments):
        if not seg.startswith("http"):
            seg = urljoin(m3u8_url, seg)
        ts_file = ts_dir / f"seg_{i:05d}.ts"
        tasks.append((seg, ts_file, i, len(segments), RETRY_TIMES))

    total_size = 0
    downloaded = 0
    skipped = 0
    failed = 0
    failed_list = []
    start_time = time.time()

    print("下载中...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_ts, t): t for t in tasks}
        for future in as_completed(futures):
            success, index, size, status = future.result()
            if success:
                if status == "skip":
                    skipped += 1
                else:
                    downloaded += 1
                total_size += size
            else:
                failed += 1
                failed_list.append(index)

            done = downloaded + skipped + failed
            elapsed = time.time() - start_time
            speed = total_size / elapsed / 1024 / 1024 if elapsed > 0 else 0
            
            remaining_tasks = len(segments) - done
            eta = remaining_tasks * (elapsed / done) if done > 0 and speed > 0 else 0

            print(f"\r  {done}/{len(segments)} | "
                  f"下载:{downloaded} 跳过:{skipped} 失败:{failed} | "
                  f"{format_size(total_size)} | "
                  f"{speed:.1f} MB/s | "
                  f"剩余:{format_time(eta)}", end="", flush=True)

            # 保存进度
            if done % 50 == 0:
                save_progress(base_dir, {
                    "m3u8_url": m3u8_url,
                    "title": title,
                    "total": len(segments),
                    "downloaded": done,
                    "failed": failed_list,
                    "total_size": total_size
                })

    print(f"\n\n下载完成: {downloaded} 下载, {skipped} 跳过, {failed} 失败")
    if failed_list:
        print(f"失败片段: {failed_list}")

    # 检查有效片段
    ts_files = sorted(ts_dir.glob("seg_*.ts"))
    ts_files = [f for f in ts_files if f.stat().st_size > MIN_SEGMENT_SIZE]

    print(f"有效片段: {len(ts_files)}/{len(segments)}")

    missing = len(segments) - len(ts_files)
    if missing > 0:
        print(f"\n警告: 缺失 {missing} 个片段，视频可能不完整")
        confirm = input("是否继续合并? (y/n): ").strip().lower()
        if confirm != "y":
            print("已取消合并")
            return False

    # 备份旧文件
    if output_file.exists():
        backup = output_file.with_suffix('.backup.mp4')
        if backup.exists():
            backup.unlink()
        output_file.rename(backup)
        print(f"已备份旧文件: {backup.name}")

    # 合并
    print("合并中...")
    with open(output_file, "wb") as outfile:
        for ts_file in ts_files:
            with open(ts_file, "rb") as infile:
                while True:
                    chunk = infile.read(1024*1024)
                    if not chunk:
                        break
                    outfile.write(chunk)

    final_size = output_file.stat().st_size
    print(f"完成: {output_file.name} ({format_size(final_size)})")

    # 清理
    if failed == 0 and missing == 0:
        for ts_file in ts_files:
            ts_file.unlink()
        ts_dir.rmdir()
        print("已清理临时文件")
        
        progress_file = base_dir / ".download_progress.json"
        if progress_file.exists():
            progress_file.unlink()
        
        backup = output_file.with_suffix('.backup.mp4')
        if backup.exists():
            backup.unlink()
            print("已删除旧备份")
    else:
        print(f"保留临时文件 ({len(ts_files)} 个片段)，可重新合并")

    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HLS视频下载器")
    parser.add_argument("m3u8_url", help="m3u8地址")
    parser.add_argument("-o", "--output", help="输出目录", default=str(Path.home() / "Downloads"))
    parser.add_argument("-t", "--title", help="视频标题", default="video")
    args = parser.parse_args()

    print("=" * 50)
    print(f"下载: {args.title}")
    print("=" * 50)
    
    if main(args.m3u8_url, args.output, args.title):
        print("\n下载成功!")
    else:
        print("\n下载失败!")
