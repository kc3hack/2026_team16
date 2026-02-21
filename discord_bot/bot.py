import discord
from discord.ext import commands
import requests
import os
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
API_BASE_URL = os.getenv('API_BASE_URL', "http://127.0.0.1:8000")

# !plan コマンドを受け付ける設定
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Botがログインしました: {bot.user}')
    print(f'接続先API: {API_BASE_URL}/api/plan/')

# コマンド: !plan YYYY-MM-DD HH:MM 予定名
@bot.command()
async def plan(ctx, date: str, time: str, *, task: str):
    discord_id = str(ctx.author.id)
    target_name = ctx.author.name
    
    setting_url = f"{API_BASE_URL}/api/plan/"
    
    # 日時・予定名もAPIに送信するよう改修
    payload = {
        "discord_user_id": discord_id,
        "date": date,
        "time": time,
        "task": task,
    }
    
    try:
        response = requests.post(setting_url, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            calendar_msg = "✅ Googleカレンダーにも登録しました！" if data.get("calendar_registered") else "⚠️ カレンダー未登録（!authで認証してください）"
            await ctx.send(
                f"✅ {target_name} さんの予定を登録しました！\n"
                f"📅 {date} {time}\n"
                f"📝 {task}\n"
                f"📆 {calendar_msg}"
            )
        else:
            await ctx.send(f"⚠️ サーバーとの通信に失敗しました。ステータス: {response.status_code}")
    except Exception as e:
        await ctx.send(f"❌ ラズパイへの接続エラー: {e}\n※ラズパイのサーバーは起動していますか？")

# コマンド: !auth （Googleカレンダー認証）
@bot.command()
async def auth(ctx):
    """
    !auth
    Googleカレンダーへのアクセスを認証する。
    DMに認証用URLを送信する。
    """
    discord_id = str(ctx.author.id)
    url = f"{API_BASE_URL}/auth/google?discord_user_id={discord_id}"

    try:
        response = requests.get(url)
        if response.status_code == 200:
            auth_url = response.json()["auth_url"]
            # DMで認証 URLを送る
            await ctx.author.send(
                f"🔑 **Googleカレンダー認証**\n"
                f"下記のURLをクリックして、Googleアカウントと連携してください。\n\n"
                f"{auth_url}"
            )
            await ctx.send("📨 DMに認証用URLを送りました！クリックして認証を完了してください。")
        else:
            await ctx.send(f"⚠️認証URLの取得に失敗しました。")
    except Exception as e:
        await ctx.send(f"❌ サーバーへの接続エラー: {e}")

# コマンド: !register メールアドレス
@bot.command()
async def register(ctx, gmail: str):
    """
    !register example@gmail.com
    自分のGmailアドレスをDiscordアカウントと紐付けてDBに登録する。
    """
    discord_id = str(ctx.author.id)
    target_name = ctx.author.name

    register_url = f"{API_BASE_URL}/api/register/"
    payload = {"discord_user_id": discord_id, "gmail": gmail}

    try:
        response = requests.post(register_url, json=payload)

        if response.status_code == 200:
            data = response.json()
            await ctx.send(
                f"✅ Gmailを登録しました！\n"
                f"👤 Discordユーザー: {target_name}\n"
                f"📧 Gmail: {data['gmail']}"
            )
        else:
            await ctx.send(f"⚠️ 登録に失敗しました。ステータス: {response.status_code}")
    except Exception as e:
        await ctx.send(f"❌ サーバーへの接続エラー: {e}\n※サーバーは起動していますか？")

# コマンド: !myinfo （テスト用・自分のDB情報を全表示）
@bot.command()
async def myinfo(ctx):
    """
    !myinfo
    コマンドを打った人のDBに保存されている全情報を表示する。
    """
    discord_id = str(ctx.author.id)
    url = f"{API_BASE_URL}/api/user/{discord_id}"

    try:
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()

            if data["status"] == "not_found":
                await ctx.send("⚠️ あなたのデータはDBに登録されていません。\n`!register メールアドレス` で登録してください。")
                return

            await ctx.send(
                f"📋 **あなたのDB情報（テスト用）**\n"
                f"──────────────────\n"
                f"🆔 DB内部ID: `{data['id']}`\n"
                f"👤 Discord ID: `{data['discord_user_id']}`\n"
                f"📧 Gmail: `{data['gmail'] or '未登録'}`\n"
                f"📱 MDMデバイスID: `{data['mdm_device_id'] or '未登録'}`\n"
                f"⏰ ズレ時間: `{data['offset_minutes']}分`\n"
                f"🎯 攻撃予約フラグ: `{data['is_attack_scheduled']}`\n"
                f"──────────────────"
            )
        else:
            await ctx.send(f"⚠️ 情報の取得に失敗しました。ステータス: {response.status_code}")
    except Exception as e:
        await ctx.send(f"❌ サーバーへの接続エラー: {e}\n※サーバーは起動していますか？")

# Bot起動
if TOKEN:
    bot.run(TOKEN)
else:
    print("⚠️ DISCORD_BOT_TOKENが設定されていません！.envを確認してください。")
