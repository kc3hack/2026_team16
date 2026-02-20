import os
import requests
from dotenv import load_dotenv

# .envを読み込む
load_dotenv()

class MDMClient:
    def __init__(self):
        # 認証サーバー (日本DC)
        self.auth_url = "https://accounts.zoho.jp/oauth/v2/token"
        # MDM API エンドポイント (日本DC)
        self.base_url = "https://mdm.manageengine.jp/api/v1/mdm"
        
        self.client_id = os.getenv("MDM_CLIENT_ID")
        self.client_secret = os.getenv("MDM_CLIENT_SECRET")
        self.refresh_token = os.getenv("MDM_REFRESH_TOKEN")
        self.device_id = os.getenv("MDM_DEVICE_ID")

    def _get_access_token(self):
        """アクセストークンを再取得する内部メソッド"""
        try:
            payload = {
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token"
            }
            res = requests.post(self.auth_url, data=payload)
            res.raise_for_status()
            return res.json().get("access_token")
        except Exception as e:
            print(f"[MDM] Token Error: {e}")
            return None

    def change_timezone(self, profile_id):
        """指定したプロファイルIDを適用してタイムゾーンを変更"""
        token = self._get_access_token()
        if not token:
            print("[MDM] 認証トークンの取得に失敗しました")
            return False

        if not self.device_id:
            print("[MDM] Device ID が設定されていません")
            return False

        url = f"{self.base_url}/devices/{self.device_id}/profiles"
        headers = {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        data = {"profile_ids": [profile_id]}

        try:
            res = requests.post(url, headers=headers, json=data, timeout=30)
            
            # 200: OK, 201: Created, 202: Accepted
            if res.status_code in [200, 201, 202]:
                print(f"[MDM] ✅ Success: Profile {profile_id} applied.")
                return True
            else:
                print(f"[MDM] ❌ Failed: {res.status_code} - {res.text}")
                return False
        except Exception as e:
            print(f"[MDM] Request Error: {e}")
            return False