# api.py
import requests
import time
import re

BASE_URL = "https://api.aliyundrive.com"


class AliyunDriveAPI:
    def __init__(self, token, is_access_token=False):
        if is_access_token:
            self.access_token = token
            self.refresh_token = None
            self.token_expires = float("inf")
        else:
            self.refresh_token = token
            self.access_token = None
            self.token_expires = 0
        self.share_token = None

    def get_access_token(self):
        if self.access_token and time.time() < self.token_expires:
            return self.access_token

        if not self.refresh_token:
            raise ValueError("No refresh_token available")

        url = "https://auth.aliyundrive.com/v2/account/token"
        resp = requests.post(
            url, json={"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        )
        resp.raise_for_status()
        data = resp.json()

        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self.token_expires = time.time() + data.get("expires_in", 7200) - 300
        return self.access_token

    def get_share_token(self, share_id):
        url = f"{BASE_URL}/v2/share_token/get"
        resp = requests.post(url, json={"share_id": share_id})
        resp.raise_for_status()
        data = resp.json()
        self.share_token = data["share_token"]
        return self.share_token

    def get_user_info(self):
        url = f"{BASE_URL}/v2/user/get"
        resp = requests.post(url, headers=self._headers(), json={})
        resp.raise_for_status()
        return resp.json()

    def get_file_list(self, share_id, parent_file_id="root"):
        url = f"{BASE_URL}/v2/file/list"
        headers = self._headers()
        items = []
        page_token = None

        while True:
            body = {"share_id": share_id, "parent_file_id": parent_file_id}
            if page_token:
                body["page_token"] = page_token
            body["limit"] = 100
            resp = requests.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("items", []))
            if not data.get("next_marker"):
                break
            page_token = data["next_marker"]

        return items

    def get_download_url(self, share_id, file_id):
        url = f"{BASE_URL}/v2/file/get_download_url"
        headers = self._headers()
        resp = requests.post(
            url, json={"share_id": share_id, "file_id": file_id}, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("url"), data.get("size", 0)

    def get_share_info(self, share_id):
        url = f"{BASE_URL}/v2/share/get"
        resp = requests.post(url, json={"share_id": share_id})
        resp.raise_for_status()
        return resp.json()

    def parse_share_url(self, url):
        parts = url.rstrip("/").split("/")
        share_id = None
        file_id = None

        for i, part in enumerate(parts):
            if part == "s" and i + 1 < len(parts):
                share_id = parts[i + 1]
            if part == "folder" and i + 1 < len(parts):
                file_id = parts[i + 1]

        return share_id, file_id

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "x-share-token": self.share_token,
        }
