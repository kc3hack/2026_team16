import os
import time
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
        
        self.client_id = (os.getenv("MDM_CLIENT_ID") or "").strip()
        self.client_secret = (os.getenv("MDM_CLIENT_SECRET") or "").strip()
        self.refresh_token = (os.getenv("MDM_REFRESH_TOKEN") or "").strip()
        self.device_id = (os.getenv("MDM_DEVICE_ID") or "").strip()

        # トークン使い回し（キャッシュ）用の変数
        self._access_token = None
        self._token_expiry = 0

    def _missing_env_keys(self):
        missing = []
        if not self.client_id:
            missing.append("MDM_CLIENT_ID")
        if not self.client_secret:
            missing.append("MDM_CLIENT_SECRET")
        if not self.refresh_token:
            missing.append("MDM_REFRESH_TOKEN")
        if not self.device_id:
            missing.append("MDM_DEVICE_ID")
        return missing

    def _get_access_token(self):
        """アクセストークンを取得（有効なキャッシュがあればそれを返す）"""
        missing = self._missing_env_keys()
        if missing:
            print(f"[MDM] ❌ 必須環境変数が不足しています: {', '.join(missing)}")
            return None

        # 現在の時刻を取得
        current_time = time.time()
        
        # キャッシュされたトークンがあり、かつ有効期限内（余裕を持って期限の60秒前）なら使い回す
        if self._access_token and current_time < (self._token_expiry - 60):
            return self._access_token

        print("[MDM] 🔄 新しいアクセストークンを要求します...")
        try:
            payload = {
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token"
            }
            res = requests.post(self.auth_url, data=payload, timeout=20)

            if res.status_code != 200:
                print(f"[MDM] ❌ Token HTTP Error: {res.status_code}")
                print(f"[MDM] Response: {res.text}")
                return None

            body = res.json()
            token = body.get("access_token")
            # 通常は3600秒（1時間）が返ってくる
            expires_in = body.get("expires_in", 3600) 

            if not token:
                print(f"[MDM] ❌ access_token がレスポンスにありません: {body}")
                return None

            # 取得したトークンと、期限切れになる時刻を記憶する
            self._access_token = token
            self._token_expiry = current_time + expires_in
            print(f"[MDM] ✅ 新しいトークンを取得・保存しました (有効期間: {expires_in}秒)")

            return token
            
        except requests.exceptions.Timeout:
            print("[MDM] ❌ Token Timeout: 認証サーバー応答待ちでタイムアウトしました")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[MDM] ❌ Token Request Error: {e}")
            return None
        except ValueError as e:
            print(f"[MDM] ❌ Token JSON Parse Error: {e}")
            print(f"[MDM] Raw Response: {res.text if 'res' in locals() else 'N/A'}")
            return None
        except Exception as e:
            print(f"[MDM] ❌ Token Unknown Error: {e}")
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