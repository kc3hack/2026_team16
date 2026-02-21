import discord
from discord.ext import commands
import requests
import os
from datetime import datetime
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

async def register_schedule_from_mentions(ctx, content: str, command_name: str):
    mentions = ctx.message.mentions
    # メンションがあればその文字列を除去、なければ入力全文を使う
    text = content
    for user in mentions:
        text = text.replace(user.mention, "").strip()

    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        await ctx.send(f"⚠️ 形式が不正です。例: !{command_name} @user 2026-02-21 09:30 朝会")
        return

    date_str, time_str, title = parts[0], parts[1], parts[2].strip()

    # フォーマット検証
    try:
        datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        await ctx.send("⚠️ 日時形式が不正です。YYYY-MM-DD HH:MM で入力してください。")
        return

    url = f"{API_BASE_URL}/api/schedules/"

    target_ids = [str(u.id) for u in mentions] if mentions else [str(ctx.author.id)]

    payload = {
        "mentioned_discord_ids": target_ids,
        "date": date_str,
        "time": time_str,
        "title": title,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            await ctx.send(f"⚠️ サーバーとの通信に失敗しました。status={response.status_code}")
            return

        body = response.json()
        saved_ids = body.get("saved_ids", [])
        skipped_ids = body.get("skipped_ids", [])

        id_to_name = {str(u.id): u.display_name for u in mentions}
        if not mentions:
            id_to_name[str(ctx.author.id)] = ctx.author.display_name
        saved_names = [id_to_name.get(i, i) for i in saved_ids]
        skipped_names = [id_to_name.get(i, i) for i in skipped_ids]

        msg = [f"📅 {date_str} {time_str}", f"📝 {title}"]
        if saved_names:
            msg.append(f"✅ 保存しました: {', '.join(saved_names)}")
        if skipped_names:
            msg.append(f"⚠️ DB未登録のためスキップ: {', '.join(skipped_names)}")
        if not saved_names and not skipped_names:
            msg.append("⚠️ 対象ユーザーがありませんでした")

        await ctx.send("\n".join(msg))
    except Exception as e:
        await ctx.send(f"❌ ラズパイへの接続エラー: {e}")




@bot.command()
async def add(ctx, *, content: str):
    """
    使い方:
    !add @user1 @user2 2026-02-21 09:30 朝会
    """
    await register_schedule_from_mentions(ctx, content, command_name="add")

# Bot起動
if TOKEN:
    bot.run(TOKEN)
else:
    print("⚠️ DISCORD_BOT_TOKENが設定されていません！.envを確認してください。")
