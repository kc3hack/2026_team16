import os
import random
import time
import threading
import asyncio
from dotenv import load_dotenv

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from gpiozero import Button
from pydantic import BaseModel

# 自作モジュール
import models
import crud
import google_calendar
from database import SessionLocal, engine
from ble_test import run_ble_server 
import ble_beacon_tx
from mdm_client import MDMClient

# 環境変数の読み込み
load_dotenv()
PROFILE_TOKYO = os.getenv("MDM_PROFILE_TOKYO")
PROFILE_GMT9_5 = os.getenv("MDM_PROFILE_GMT9_5")
PROFILE_GMT10 = os.getenv("MDM_PROFILE_GMT10")
PROFILE_GMT10_5 = os.getenv("MDM_PROFILE_GMT10_5")
PROFILE_GMT11 = os.getenv("MDM_PROFILE_GMT11")

# DBテーブル作成
models.Base.metadata.create_all(bind=engine)

# ==========================
# WebSocket接続マネージャー
# ==========================
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"⚠️ WebSocket送信エラー: {e}")

manager = ConnectionManager()
loop = None

# ==========================
# GPIO ボタン設定
# ==========================
BUTTON_PIN = 17
button = None
press_start_time = 0

def on_press():
    global press_start_time
    press_start_time = time.time()
    print("🔘 [Button] 押されました。時間計測スタート...")

def change_timezone(profile_id):
    mdm_client = MDMClient()
    ok = mdm_client.change_timezone(profile_id)
    if not ok:
        print("⚠️ MDMタイムゾーン変更に失敗しました")
        return False
    return True

def execute_button_action(press_duration):
    if press_duration <= 3.0:
        print("⚡ 【短押し検知】ランダムに時間をずらす命令を送信します！")
        
        multiplier = random.randint(1, 4)
        offset = multiplier * 30
        print(f"🎲 ランダム決定: パターン{multiplier} -> {offset}分 ずらします")

        # 1. MDM（スマホ）
        match multiplier:
            case 1:
                change_timezone(PROFILE_GMT9_5)
            case 2:
                change_timezone(PROFILE_GMT10)
            case 3:
                change_timezone(PROFILE_GMT10_5)
            case 4:
                change_timezone(PROFILE_GMT11)
            case _:
                print("⚠️ ランダム決定に失敗しました。MDMは変更しません。")
        
        # 2. Windows PC (WebSocket)
        payload = {"action": "shift", "offset_minutes": offset}
        if loop:
            asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)
            
        # 3. 物理時計 (BLE)
        print(f"📡 物理時計へ {offset}分 のタイムリープ電波を発信します...")
        ble_beacon_tx.broadcast_time_burst(offset, repeat_count=3, interval_ms=100)
        
    else:
        print("🛡️ 【長押し検知】時間を元に戻す(復旧)命令を送信します！")
        
        # 1. MDM（スマホ）
        change_timezone(PROFILE_TOKYO)

        # 2. Windows PC (WebSocket)
        payload = {"action": "restore"}
        if loop:
            asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)

        # 3. 物理時計 (BLE)
        print("📡 物理時計へ復旧電波を発信します...")
        ble_beacon_tx.broadcast_time_burst(0, repeat_count=3, interval_ms=100)

def on_release():
    global press_start_time
    press_duration = time.time() - press_start_time
    print(f"🔘 [Button] 離されました。押下時間: {press_duration:.2f}秒")
    threading.Thread(target=execute_button_action, args=(press_duration,)).start()

# ==========================
# 定期実行タスク (深夜0時発動)
# ==========================
async def midnight_attack():
    print("🕛 深夜0時です。タイムリープを開始します...")
    db = SessionLocal()
    try:
        settings = db.query(models.UserSetting).filter(models.UserSetting.is_attack_scheduled.is_(True)).all()
        
        for user in settings:
            multiplier = random.randint(1, 4)
            offset = multiplier * 30
            print(f"🎲 {user.discord_user_id} のランダム決定: パターン{multiplier} -> {offset}分")

            # 1. MDM（スマホ）
            match multiplier:
                case 1:
                    await asyncio.to_thread(change_timezone, PROFILE_GMT9_5)
                case 2:
                    await asyncio.to_thread(change_timezone, PROFILE_GMT10)
                case 3:
                    await asyncio.to_thread(change_timezone, PROFILE_GMT10_5)
                case 4:
                    await asyncio.to_thread(change_timezone, PROFILE_GMT11)
                case _:
                    print("⚠️ ランダム決定に失敗しました。MDMは変更しません。")
            
            # 2. Windows PC (WebSocket)
            payload = {
                "action": "shift",
                "direction": "forward", 
                "offset_minutes": offset
            }
            await manager.broadcast(payload)
            print(f"🚀 Windows時間を {offset}分 進めました")
            
            # 3. 物理時計 (BLE)
            print(f"📡 物理時計へ {offset}分 のタイムリープ電波を発信します...")
            await asyncio.to_thread(
                ble_beacon_tx.broadcast_time_burst,
                offset,
                repeat_count=5
            )
            
            # 攻撃フラグをリセット
            user.is_attack_scheduled = False # type: ignore
            
        db.commit()
    finally:
        db.close()

# ==========================
# ライフスパン (起動・終了処理)
# ==========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    loop = asyncio.get_running_loop()
    
    # スケジューラー起動（タイムゾーンを明示指定。Windowsのシステムタイムゾーンが書き換えられても動くように）
    scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")
    scheduler.add_job(midnight_attack, 'cron', minute='*') # テスト用（本番は hour=0, minute=0）
    scheduler.start()
    print("⏰ スケジューラーが起動しました")

    # BLEサーバー起動
    print("📡 BLEプロビジョニングサーバーを起動中...")
    ble_task = asyncio.create_task(run_ble_server())
    
    # GPIO初期化
    global button
    try:
        button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
        button.when_pressed = on_press
        button.when_released = on_release
        print(f"✅ GPIO {BUTTON_PIN} is ready.")
    except Exception as e:
        print(f"⚠️ GPIO Init Error: {e}")

    yield
    
    print("🛑 サーバー停止中。BLEサーバーを終了します...")
    ble_task.cancel()
    try:
        await ble_task
    except asyncio.CancelledError:
        print("✅ BLEサーバーを正常に停止しました。")

# ==========================
# FastAPI アプリ定義
# ==========================
app = FastAPI(lifespan=lifespan)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from typing import Optional

class PlanRequest(BaseModel):
    discord_user_id: str
    date: Optional[str] = None   # 予定日付 "YYYY-MM-DD"
    time: Optional[str] = None   # 予定時刻 "HH:MM"
    task: Optional[str] = None   # 予定名

@app.websocket("/ws/windows")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    print("💻 [WebSocket] Windows PCが接続しました！")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("🔌 [WebSocket] Windows PCが切断されました")

@app.post("/api/plan/")
def register_plan(plan: PlanRequest, db: Session = Depends(get_db)):
    crud.schedule_attack(db, plan.discord_user_id)
    
    # DBからユーザー情報を取得して一緒に返す
    user = db.query(models.UserSetting).filter(
        models.UserSetting.discord_user_id == plan.discord_user_id
    ).first()

    # Googleカレンダー登録（トークンと日時・予定名がある場合のみ）
    calendar_registered = False
    if (user and user.google_access_token and user.google_refresh_token
            and plan.date and plan.time and plan.task):
        try:
            google_calendar.add_event_to_calendar(
                access_token=user.google_access_token,
                refresh_token=user.google_refresh_token,
                date=plan.date,
                time=plan.time,
                task=plan.task,
            )
            calendar_registered = True
        except Exception as e:
            print(f"⚠️ Googleカレンダー登録エラー: {e}")

    return {
        "status": "success",
        "message": "攻撃予約完了",
        "user_id": user.id,
        "offset_minutes": user.offset_minutes,
        "attack_scheduled": user.is_attack_scheduled,
        "calendar_registered": calendar_registered,
    }

# ==========================
# Google OAuth2 認証
# ==========================
@app.get("/auth/google")
def google_auth(discord_user_id: str):
    """
    !auth コマンドから呼ばれる。
    このURLをユーザーにDMで送る。
    """
    auth_url = google_calendar.get_auth_url(discord_user_id)
    return {"auth_url": auth_url}

@app.get("/auth/callback")
def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Googleがリダイレクトするエンドポイント。
    コードをトークンに交換してDBに保存する。
    stateにDiscordIDが入っている。
    """
    discord_user_id = state

    # 認証コードをトークンに交換
    tokens = google_calendar.exchange_code_for_tokens(code)

    # DBにトークンを保存
    user = db.query(models.UserSetting).filter(
        models.UserSetting.discord_user_id == discord_user_id
    ).first()
    if user:
        user.google_access_token = tokens["access_token"]   # type: ignore
        user.google_refresh_token = tokens["refresh_token"]  # type: ignore
    else:
        user = models.UserSetting(
            discord_user_id=discord_user_id,
            google_access_token=tokens["access_token"],
            google_refresh_token=tokens["refresh_token"],
        )
        db.add(user)
    db.commit()
    print(f"✅ [Google認証完了] DiscordID: {discord_user_id} のトークンを保存しました")

    # ブラウザに表示する完了メッセージ
    return {"認証完了": "✅ Googleカレンダーへのアクセスが許可されました！Discordに戻って!planを試してみてください。"}

class RegisterRequest(BaseModel):
    discord_user_id: str
    gmail: str

@app.post("/api/register/")
def register_gmail_endpoint(req: RegisterRequest, db: Session = Depends(get_db)):
    """
    DiscordIDとGmailを紐付けてDBに保存する。
    !register コマンドから呼ばれる。
    """
    user = crud.register_gmail(db, req.discord_user_id, req.gmail)
    print(f"📧 [Gmail登録] DiscordID: {req.discord_user_id} → {req.gmail}")
    return {
        "status": "success",
        "discord_user_id": user.discord_user_id,
        "gmail": user.gmail
    }

# ==========================
# ユーザー情報取得API（テスト用）
# ==========================
@app.get("/api/user/{discord_user_id}")
def get_user_info(discord_user_id: str, db: Session = Depends(get_db)):
    """
    DiscordIDを元にDBの全情報を返す。
    !myinfo コマンドから呼ばれる。
    """
    user = db.query(models.UserSetting).filter(
        models.UserSetting.discord_user_id == discord_user_id
    ).first()

    if not user:
        return {"status": "not_found", "message": "このユーザーはDBに登録されていません。"}

    return {
        "status": "success",
        "id": user.id,
        "discord_user_id": user.discord_user_id,
        "gmail": user.gmail,
        "mdm_device_id": user.mdm_device_id,
        "offset_minutes": user.offset_minutes,
        "is_attack_scheduled": user.is_attack_scheduled,
    }

# ==========================
# Googleカレンダー予定取得API
# ==========================
@app.get("/api/schedule/{discord_user_id}")
def get_schedule(discord_user_id: str, db: Session = Depends(get_db)):
    """
    DiscordIDを元にDBからトークンを取得し、
    Googleカレンダーの直近5件の予定を返す。
    !schedule コマンドから呼ばれる。
    """
    user = db.query(models.UserSetting).filter(
        models.UserSetting.discord_user_id == discord_user_id
    ).first()

    if not user:
        return {"status": "not_found", "message": "DBに登録されていません。!auth で認証してください。"}

    if not user.google_access_token or not user.google_refresh_token:
        return {"status": "not_authorized", "message": "Googleカレンダーの認証が完了していません。!auth で認証してください。"}

    try:
        events = google_calendar.get_upcoming_events(
            access_token=user.google_access_token,
            refresh_token=user.google_refresh_token,
            max_results=5
        )
        return {"status": "success", "events": events}
    except Exception as e:
        print(f"⚠️ カレンダー取得エラー: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":

    uvicorn.run(app, host="127.0.0.1", port=8000)
    