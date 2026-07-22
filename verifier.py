# verifier.py
import subprocess
from pathlib import Path


class FileVerifier:
    MP4_SIGNATURES = [
        b"\x00\x00\x00\x18ftyp",
        b"\x00\x00\x00\x1cftyp",
        b"\x00\x00\x00\x20ftyp",
    ]
    MKV_SIGNATURES = [b"\x1a\x45\xdf\xa3"]

    def verify(self, filepath, expected_size=0):
        filepath = Path(filepath)
        result = {"valid": True, "checks": [], "errors": []}

        if not filepath.exists():
            result["valid"] = False
            result["errors"].append("文件不存在")
            return result

        actual_size = filepath.stat().st_size
        if expected_size > 0 and actual_size != expected_size:
            result["valid"] = False
            result["errors"].append(f"文件大小不匹配: 期望{expected_size}, 实际{actual_size}")
        result["checks"].append(f"文件大小: {actual_size / 1024 / 1024:.2f} MB")

        with open(filepath, "rb") as f:
            header = f.read(12)

        if not self._check_magic_bytes(header):
            result["valid"] = False
            result["errors"].append("文件头校验失败，可能不是有效的视频文件")
        else:
            result["checks"].append("文件头校验通过")

        probe_result = self._ffprobe_check(filepath)
        if probe_result is None:
            result["checks"].append("FFprobe未安装，跳过深度校验")
        elif probe_result["valid"]:
            result["checks"].append(f"FFprobe校验通过 - 时长: {probe_result['duration']:.1f}秒")
        else:
            result["valid"] = False
            result["errors"].append(f"FFprobe检测失败: {probe_result['error']}")

        return result

    def _check_magic_bytes(self, header):
        for sig in self.MP4_SIGNATURES:
            if header.startswith(sig):
                return True
        for sig in self.MKV_SIGNATURES:
            if header.startswith(sig):
                return True
        return False

    def _ffprobe_check(self, filepath):
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(filepath),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                duration = float(result.stdout.strip())
                return {"valid": True, "duration": duration}
            return {"valid": False, "error": result.stderr}
        except FileNotFoundError:
            return None
        except Exception as e:
            return {"valid": False, "error": str(e)}
