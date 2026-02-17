import discord
import requests
import re
import os
from datetime import datetime
from dotenv import load_dotenv

# .envファイルからTOKENを読み込む
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# FastAPIサーバーのURL
API_BASE_URL = "http://127.0.0.1:8000"

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
        
        # --- [Step 1] まず、コマンド本文から「日時」と「タイトル」を解析する ---
        # メンション部分 (<@12345...> のような文字列) を先に全部消してしまう
        content_clean = re.sub(r'<@!?[0-9]+>', '', message.content).replace('!plan', '').strip()
        
        parts = content_clean.split()
        
        if len(parts) < 3:
            await message.channel.send("⚠️ 書式エラー: `!plan (@誰か) YYYY-MM-DD HH:MM 予定名` のように入力してください")
            return

        date_str = parts[0]  # YYYY-MM-DD
        time_str = parts[1]  # HH:MM
        title = " ".join(parts[2:]) # 残りすべてをタイトルにする

        # 日時フォーマットチェック
        datetime_str = f"{date_str} {time_str}"
        try:
            dt_obj = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
            iso_format_time = dt_obj.isoformat()
        except ValueError:
            await message.channel.send("⚠️ 日時フォーマットエラー: `YYYY-MM-DD HH:MM` で入力してください (例: 2026-02-17 10:00)")
            return

        # --- [Step 2] ターゲットリストを作成 (メンションがあれば全員、なければ自分) ---
        targets = []
        if message.mentions:
            targets = message.mentions # メンションされた人全員リスト
        else:
            targets = [message.author] # 自分ひとりだけのリスト

        await message.channel.send(f"🔄 **{len(targets)}名** のユーザー処理を開始します...")

        # --- [Step 3] 全員に対してループ処理を実行 ---
        for target_user in targets:
            
            discord_id_str = str(target_user.id)
            target_name = target_user.name
            db_user_id = None
            
            # A. ユーザー確認・作成処理
            try:
                # ユーザー検索
                user_check_url = f"{API_BASE_URL}/users/discord/{discord_id_str}"
                response = requests.get(user_check_url)
                
                if response.status_code == 200:
                    # 既存ユーザー
                    db_user_id = response.json()['id']
                elif response.status_code == 404:
                    # 新規作成
                    create_url = f"{API_BASE_URL}/users/"
                    create_data = {
                        "username": target_name,
                        "discord_user_id": discord_id_str
                    }
                    create_res = requests.post(create_url, json=create_data)
                    if create_res.status_code == 200:
                        db_user_id = create_res.json()['id']
                        await message.channel.send(f"🆕 **{target_name}** さんを新規登録しました！")
                    else:
                        await message.channel.send(f"❌ {target_name} さんの登録失敗: {create_res.text}")
                        continue # 次の人へ
                else:
                    await message.channel.send(f"❌ APIエラー ({target_name}): {response.status_code}")
                    continue

            except Exception as e:
                await message.channel.send(f"❌ サーバー接続エラー ({target_name}): {e}")
                continue

            # B. 予定登録処理
            schedule_url = f"{API_BASE_URL}/users/{db_user_id}/schedules/"
            schedule_data = {
                "title": title,
                "original_start_time": iso_format_time,
                "source": "discord"
            }
            
            try:
                res = requests.post(schedule_url, json=schedule_data)
                if res.status_code == 200:
                    await message.channel.send(f"✅ **{target_name}** さんの予定登録！ (予定: {title})")
                else:
                    await message.channel.send(f"❌ {target_name} さんの予定登録失敗: {res.text}")
            except Exception as e:
                await message.channel.send(f"❌ 送信エラー ({target_name}): {e}")

# Bot起動
client.run(TOKEN)