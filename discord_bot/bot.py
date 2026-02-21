import discord
import asyncio
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
    print(f"登録コマンド: {', '.join(sorted(c.name for c in bot.commands))}")

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
        response = await asyncio.to_thread(requests.post, setting_url, json=payload)

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

# コマンド: !schedule （Googleカレンダーの直近予定を表示）
@bot.command()
async def schedule(ctx):
    """
    !schedule
    Googleカレンダーに登録されている直近5件の予定を表示する。
    事前に !auth で認証が必要。
    """
    discord_id = str(ctx.author.id)
    url = f"{API_BASE_URL}/api/schedule/{discord_id}"

    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()

            if data["status"] == "not_found":
                await ctx.send("⚠️ DBに登録されていません。まず `!auth` で認証してください。")
                return
            if data["status"] == "not_authorized":
                await ctx.send("⚠️ Googleカレンダーの認証が完了していません。`!auth` を実行してください。")
                return
            if data["status"] == "error":
                await ctx.send(f"❌ カレンダー取得エラー: {data['message']}")
                return

            events = data["events"]
            if not events:
                await ctx.send("📅 直近の予定はありません。")
                return

            msg = "📅 **あなたの直近の予定（Googleカレンダー）**\n──────────────────\n"
            for i, event in enumerate(events, 1):
                title = event.get("summary", "（タイトルなし）")
                start = event.get("start", {})
                # 終日イベントは "date"、時間指定イベントは "dateTime"
                start_str = start.get("dateTime", start.get("date", "不明"))
                # ISO形式を整形（"2026-03-01T10:00:00+09:00" → "2026-03-01 10:00"）
                if "T" in start_str:
                    start_str = start_str[:16].replace("T", " ")
                msg += f"{i}. `{start_str}` | {title}\n"
            msg += "──────────────────"

            await ctx.send(msg)
        else:
            await ctx.send(f"⚠️ 取得に失敗しました。ステータス: {response.status_code}")
    except Exception as e:
        await ctx.send(f"❌ サーバーへの接続エラー: {e}\n※サーバーは起動していますか？")
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
        response = await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
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
