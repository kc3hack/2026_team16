# backend/test_mdm_direct.py
from mdm_client import MDMClient
import os
from dotenv import load_dotenv

load_dotenv()

print("🚀 MDM接続テストを開始します...")

# 1. クライアントの準備
try:
    mdm = MDMClient()
    print("✅ クライアント初期化 OK")
except Exception as e:
    print(f"❌ 初期化失敗: {e}")
    exit()

# 2. 設定値の確認
profile_id = os.getenv("MDM_PROFILE_TOKYO")
device_id = os.getenv("MDM_DEVICE_ID")
print(f"ℹ️ 使用プロファイルID: {profile_id}")
print(f"ℹ️ 使用デバイスID: {device_id}")

# 3. 実行テスト
print("📡 命令を送信中...")
result = mdm.change_timezone(profile_id)

print("-" * 30)
if result:
    print("🎉 成功！ (Trueが返ってきました)")
else:
    print("⚠️ 失敗 (Falseが返ってきました)")
    print("↑上に 'Failed' や 'Token Error' が出ていないか確認してください")
print("-" * 30)