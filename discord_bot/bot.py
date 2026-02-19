import discord
import requests
import re
import os
from datetime import datetime
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# FastAPIサーバーのURL (ラズパイのIPアドレス。例: http://192.168.x.x:8000)
# 同じラズパイの中でBotも動かすなら http://127.0.0.1:8000 でOKです
API_BASE_URL = os.getenv('API_BASE_URL', "http://127.0.0.1:8000")

# --- Discord Botの初期設定 ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'✅ Botがログインしました: {client.user}')
    print(f'接続先API: {API_BASE_URL}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # ---------------------------------------------------------
    # コマンド: !plan [メンション... ] YYYY-MM-DD HH:MM 予定名
    # ---------------------------------------------------------
    if message.content.startswith('!plan'):
        
        # --- [Step 1] 文字列の解析 ---
        content_clean = re.sub(r'<@!?[0-9]+>', '', message.content).replace('!plan', '').strip()
        parts = content_clean.split()
        
        if len(parts) < 3:
            await message.channel.send("⚠️ 書式エラー: `!plan (@誰か) YYYY-MM-DD HH:MM 予定名`")
            return

        date_str = parts[0]  # YYYY-MM-DD
        time_str = parts[1]  # HH:MM
        title = " ".join(parts[2:]) # 残りすべて

        # 日時フォーマットチェック（形式が正しいかだけ確認）
        datetime_str = f"{date_str} {time_str}"
        try:
            datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        except ValueError:
            await message.channel.send("⚠️ 日時フォーマットエラー: `YYYY-MM-DD HH:MM` で入力してください")
            return

        # --- [Step 2] ターゲットの決定 ---
        targets = message.mentions if message.mentions else [message.author]
        await message.channel.send(f"🔄 **{len(targets)}名** の設定をラズパイに送信します...")

        # --- [Step 3] ラズパイ（FastAPI）へデータを送信 ---
        for target_user in targets:
            discord_id_str = str(target_user.id)
            target_name = target_user.name
            
            # ラズパイの新APIエンドポイント
            setting_url = f"{API_BASE_URL}/api/settings/"
            
            # APIに送るデータ（※後でMDMのIDなどが入りますが、今は仮で送信）
            setting_data = {
                "discord_user_id": discord_id_str,
                "mdm_device_id": "WINDOWS_PC_01", # 今は仮のID
                "offset_minutes": 60              # 予定が作られたら、とりあえず60分ずらす
            }
            
            try:
                # データをPOST送信！
                res = requests.post(setting_url, json=setting_data)
                
                if res.status_code == 200:
                    await message.channel.send(f"✅ **{target_name}** さんの予定を登録し、時間を+60分ずらす予約をしました！ (予定: {title})")
                else:
                    await message.channel.send(f"❌ {target_name} さんの設定保存に失敗しました: {res.text}")
            except Exception as e:
                await message.channel.send(f"❌ ラズパイへの接続エラー ({target_name}): {e}\n※ラズパイのサーバーは起動していますか？")

# Bot起動
if TOKEN:
    client.run(TOKEN)
else:
    print("⚠️ DISCORD_BOT_TOKENが設定されていません！")