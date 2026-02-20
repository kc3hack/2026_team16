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
    
    # FastAPIの「予定受付専用エンドポイント」を叩く
    setting_url = f"{API_BASE_URL}/api/plan/"
    
    # APIには「誰が予定を入れたか」だけを伝える
    payload = {"discord_user_id": discord_id}
    
    try:
        response = requests.post(setting_url, json=payload)
        
        if response.status_code == 200:
            await ctx.send(f"✅ {target_name} さんの予定を登録しました！\n📅 {date} {time}\n📝 {task}\n（※裏でTimeHackerが起動準備に入りました...）")
        else:
            await ctx.send(f"⚠️ サーバーとの通信に失敗しました。ステータス: {response.status_code}")
    except Exception as e:
        await ctx.send(f"❌ ラズパイへの接続エラー: {e}\n※ラズパイのサーバーは起動していますか？")

# Bot起動
if TOKEN:
    bot.run(TOKEN)
else:
    print("⚠️ DISCORD_BOT_TOKENが設定されていません！.envを確認してください。")