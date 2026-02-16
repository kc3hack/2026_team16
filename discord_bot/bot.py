import discord
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

# .envファイルからTOKENを読み込む
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# APIサーバーのURL
# ローカルテストならこれでOK。ラズパイで動かすときはラズパイのIPに変える。
API_BASE_URL = os.getenv('API_BASE_URL', 'http://127.0.0.1:8000')

# Discordの接続設定
intents = discord.Intents.default()
intents.message_content = True # メッセージの中身を読む権限
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'ログインしました: {client.user}')
    print('Botが準備完了です！')

@client.event
async def on_message(message):
    # 自分自身のメッセージは無視
    if message.author == client.user:
        return

    # コマンド: !plan YYYY-MM-DD HH:MM 予定名
    if message.content.startswith('!plan'):
        try:
            # メッセージを分解する
            # 例: "!plan 2026-02-17 10:00 キックオフ"
            parts = message.content.split()
            
            if len(parts) < 4:
                await message.channel.send("⚠️ 形式エラー: `!plan YYYY-MM-DD HH:MM 予定名` の順で入力してください")
                return

            date_str = parts[1] # 2026-02-17
            time_str = parts[2] # 10:00
            title = " ".join(parts[3:]) # キックオフ

            # 日時チェック（ISO形式に変換するため）
            full_datetime_str = f"{date_str}T{time_str}:00"
            dt = datetime.strptime(full_datetime_str, '%Y-%m-%dT%H:%M:%S')

            # --- APIに送信するデータを作成 ---
            payload = {
                "title": title,
                "original_start_time": full_datetime_str, # ISO 8601形式
                "source": "discord"
            }

            # ユーザーIDは仮で「1」として送信（実際はDiscord IDと紐付ける処理を入れると良い）
            user_id = 1 
            
            # APIを叩く (POST)
            print(f"Sending to API: {payload}")
            response = requests.post(f"{API_BASE_URL}/users/{user_id}/schedules/", json=payload)

            if response.status_code == 200:
                data = response.json()
                await message.channel.send(f"✅ **予定を登録しました！**\nタイトル: {title}\n日時: {date_str} {time_str}\n\n🤖 エンジニア時間システムと同期完了。")
            else:
                await message.channel.send(f"❌ APIエラーが発生しました: Status {response.status_code}")
                print(response.text)

        except ValueError:
            await message.channel.send("❌ 日付形式が間違っています。 `2026-02-17 10:00` のように入力してください。")
        except Exception as e:
            await message.channel.send(f"❌ 予期せぬエラー: {e}")
            print(e)

# ボット起動
client.run(TOKEN)