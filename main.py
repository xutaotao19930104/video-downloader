# main.py
import sys
import re
import time
from pathlib import Path
from api import AliyunDriveAPI
from downloader import Downloader
from config import load_config


def parse_filename(title, index):
    return f"{title} - 第{index:02d}集.mp4"


def main():
    config = load_config()

    if len(sys.argv) > 1:
        share_url = sys.argv[1]
    else:
        share_url = input("请输入阿里云盘分享链接: ")

    token = config.get("access_token") or config.get("refresh_token")
    is_access_token = bool(config.get("access_token"))

    if not token:
        token = input("请输入 access_token 或 refresh_token: ").strip()
        token_type = input("这是 access_token 还是 refresh_token? (a/r): ").strip().lower()
        is_access_token = token_type == "a"
        if is_access_token:
            config["access_token"] = token
        else:
            config["refresh_token"] = token
        from config import save_config
        save_config(config)

    api = AliyunDriveAPI(token, is_access_token=is_access_token)
    share_id, folder_id = api.parse_share_url(share_url)

    if not share_id:
        print("错误: 无法解析分享链接")
        return

    print(f"分享ID: {share_id}")
    print("正在获取分享令牌...")
    api.get_share_token(share_id)

    print("正在获取文件列表...")
    files = api.get_file_list(share_id, folder_id or "root")

    video_files = [
        f
        for f in files
        if f["name"].lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".flv"))
    ]

    if not video_files:
        print("未找到视频文件")
        return

    video_files.sort(key=lambda x: x["name"])

    first_name = video_files[0]["name"]
    title_match = re.match(
        r"^(.*?)[\s._-]*(?:第?\d+集|EP?\d+|E\d+|\d+)", first_name, re.IGNORECASE
    )
    default_title = title_match.group(1).strip() if title_match else ""

    user_input = input(f"请输入视频标题（回车使用默认: {default_title}）: ").strip()
    title = user_input if user_input else default_title

    if not title:
        print("错误: 必须输入标题")
        return

    print(f"\n视频标题: {title}")
    print(f"共找到 {len(video_files)} 个视频文件")
    for i, f in enumerate(video_files, 1):
        print(f"  {i:2d}. {f['name']}")

    confirm = input("\n是否开始下载？(y/n): ")
    if confirm.lower() != "y":
        print("已取消下载")
        return

    download_dir = Path(config["download_dir"]) / title
    download_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n下载目录: {download_dir}")

    downloader = Downloader(
        speed_limit=config.get("download_speed_limit", 0),
        chunk_size=config.get("chunk_size", 1024 * 1024 * 8),
    )

    success_count = 0
    for i, file_info in enumerate(video_files, 1):
        print(f"\n{'=' * 50}")
        print(f"正在下载第 {i}/{len(video_files)} 个视频: {file_info['name']}")

        filename = parse_filename(title, i)

        print("正在获取下载链接...")
        try:
            download_url, size = api.get_download_url(share_id, file_info["file_id"])
        except Exception as e:
            print(f"  获取下载链接失败: {e}")
            continue

        if not download_url:
            print("  获取下载链接失败，跳过此文件")
            continue

        print(f"  文件大小: {size / 1024 / 1024:.2f} MB")

        if downloader.download(download_url, str(download_dir), filename):
            success_count += 1

        if i < len(video_files):
            print(f"\n  等待 3 秒后继续...")
            time.sleep(3)

    print(f"\n{'=' * 50}")
    print(f"下载完成!")
    print(f"成功: {success_count}/{len(video_files)}")
    print(f"保存位置: {download_dir}")


if __name__ == "__main__":
    main()
