import requests
import os
import urllib.parse
from typing import Optional, Dict, Any

class YandexDiskHandler:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"OAuth {token}",
            "Accept": "application/json"
        }
        self.base_url = "https://cloud-api.yandex.net/v1/disk"

    def check_connection(self) -> bool:
        """Verify if the OAuth token is valid and connection works."""
        try:
            response = requests.get(self.base_url, headers=self.headers, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def create_folder(self, path: str) -> bool:
        """
        Create a folder on Yandex.Disk. Supports nested folders (recursively creates parents).
        Path should start with '/' and be absolute within the disk (e.g. '/Generator/Project1')
        """
        # Clean path: remove trailing slash, ensure it starts with /
        path = "/" + path.strip("/")
        parts = [p for p in path.split("/") if p]
        
        current_path = ""
        for part in parts:
            current_path += "/" + part
            encoded_path = urllib.parse.quote(current_path)
            url = f"{self.base_url}/resources?path={encoded_path}"
            try:
                # Try to create folder
                response = requests.put(url, headers=self.headers, timeout=10)
                # 201 Created is success. 409 Conflict means it already exists (which is fine).
                if response.status_code not in (201, 409):
                    print(f"Failed to create folder {current_path}: {response.text}")
                    return False
            except Exception as e:
                print(f"Error creating folder {current_path}: {e}")
                return False
        return True

    def upload_file(self, local_file_path: str, disk_file_path: str, overwrite: bool = True) -> Optional[str]:
        """
        Uploads a local file to Yandex.Disk at disk_file_path and returns the public URL.
        disk_file_path should look like '/Generator/Project1/image.png'
        """
        if not os.path.exists(local_file_path):
            print(f"Local file does not exist: {local_file_path}")
            return None

        # Make sure parent directory exists on Yandex.Disk
        parent_dir = os.path.dirname(disk_file_path).replace("\\", "/")
        if parent_dir and parent_dir != "/":
            self.create_folder(parent_dir)

        # 1. Get URL to upload the file to
        encoded_disk_path = urllib.parse.quote(disk_file_path)
        upload_url_api = f"{self.base_url}/resources/upload?path={encoded_disk_path}&overwrite={str(overwrite).lower()}"
        
        try:
            response = requests.get(upload_url_api, headers=self.headers, timeout=10)
            if response.status_code != 200:
                print(f"Failed to get upload URL: {response.text}")
                return None
            
            upload_data = response.json()
            upload_href = upload_data.get("href")
            if not upload_href:
                print("No upload href returned in response")
                return None

            # 2. Upload file contents to the received href
            with open(local_file_path, "rb") as f:
                upload_response = requests.put(upload_href, data=f, timeout=60)
            
            # Yandex returns 201 Created on successful upload
            if upload_response.status_code not in (201, 202):
                print(f"Failed uploading file contents: {upload_response.status_code} - {upload_response.text}")
                return None

            # 3. Publish the uploaded file to make it public
            publish_url = f"{self.base_url}/resources/publish?path={encoded_disk_path}"
            publish_response = requests.put(publish_url, headers=self.headers, timeout=10)
            if publish_response.status_code not in (200, 201):
                print(f"Failed to publish file: {publish_response.text}")
                # We can still try to read public_url just in case
            
            # 4. Get metadata including public_url
            meta_url = f"{self.base_url}/resources?path={encoded_disk_path}&fields=public_url"
            meta_response = requests.get(meta_url, headers=self.headers, timeout=10)
            if meta_response.status_code == 200:
                meta_data = meta_response.json()
                public_url = meta_data.get("public_url")
                if public_url:
                    return public_url
                else:
                    print("File uploaded but public URL was not found in response metadata.")
            else:
                print(f"Failed to fetch metadata: {meta_response.text}")
            
            return None

        except Exception as e:
            print(f"Exception during Yandex Disk upload: {e}")
            return None
