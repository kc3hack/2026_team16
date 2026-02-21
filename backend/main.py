import os
import random
import time
import threading
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta
import ble_test

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from gpiozero import Button
from pydantic import BaseModel

# 自作モジュール
import models
import crud
import schemas
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
# GPIO ボタン設定 (マルチクリック判定)
# ==========================
BUTTON_PIN = 17
button = None
press_start_time = 0
click_count = 0
click_timer = None

def on_press():
    global press_start_time
    press_start_time = time.time()
    print("🔘 [Button] 押されました...")

def change_timezone(profile_id):
    mdm_client = MDMClient()
    ok = mdm_client.change_timezone(profile_id)
    if not ok:
        print("⚠️ MDMタイムゾーン変更に失敗しました")
        return False
    return True

# --- 各アクションの定義 ---

def execute_shift_action():
    """シングルクリック時：ランダムタイムリープ"""
    print("⚡ 【シングルクリック検知】時間をランダムにずらします！")
    multiplier = random.randint(1, 4)
    offset = multiplier * 30
    print(f"🎲 パターン{multiplier} -> {offset}分")

    # 1. MDM
    match multiplier:
        case 1: change_timezone(PROFILE_GMT9_5)
        case 2: change_timezone(PROFILE_GMT10)
        case 3: change_timezone(PROFILE_GMT10_5)
        case 4: change_timezone(PROFILE_GMT11)
    
    # 2. Windows 
    payload = {
        "action": "shift",
        "direction": "forward",
        "offset_minutes": offset
    }
    if loop:
        print(f"💻 Windows PCへ送信: {offset}分進める")
        asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)
            
    # 3. 物理時計
    ble_beacon_tx.broadcast_time_burst(offset, repeat_count=3, interval_ms=100)

def execute_pairing_mode():
    """ダブルクリック時：BLEペアリングモードON"""
    print("\n🔗 【ダブルクリック検知】ペアリングモードを起動します！")
    ble_test.pairing_mode_active = True  # type: ignore
    print("🔵 3分間、WebからのWi-Fi設定を受付開始します...")

    # 3分後に自動で閉じるタイマー
    def disable_mode():
        if ble_test.pairing_mode_active:  # type: ignore
            ble_test.pairing_mode_active = False  # type: ignore
            print("⏳ タイムアップ: ペアリングモードを終了しました。")
    
    threading.Timer(180.0, disable_mode).start()

def execute_restore_action():
    """長押し時：復旧"""
    print("\n🛡️ 【長押し検知】時間を元に戻す(復旧)命令を送信します！")
    
    # 1. MDM復旧
    if PROFILE_TOKYO:
        success = change_timezone(PROFILE_TOKYO)
        if success:
            print("✅ MDM復旧命令の送信に成功しました")
    else:
        print("❌ エラー: PROFILE_TOKYO が設定されていません。")

    # 2. Windows PC
    payload = {
        "action": "restore",
        "direction": "none",
        "offset_minutes": 0
    }
    if loop:
        print("💻 Windows PCへ送信: 時間を元に戻す")
        asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)
        
    # 3. 物理時計
    ble_beacon_tx.broadcast_time_burst(0, repeat_count=3, interval_ms=100)

# --- 判定ロジック ---

def evaluate_clicks():
    global click_count
    if click_count == 1:
        execute_shift_action()
    elif click_count >= 2:
        execute_pairing_mode()
    click_count = 0

def on_release():
    global press_start_time, click_count, click_timer
    press_duration = time.time() - press_start_time
    print(f"🔘 [Button] 離されました ({press_duration:.2f}s)")

    if press_duration >= 4.0:
        click_count = 0
        if click_timer:
            click_timer.cancel()
        execute_restore_action()
    else:
        click_count += 1
        if click_timer:
            click_timer.cancel()
        
        click_timer = threading.Timer(0.4, evaluate_clicks)
        click_timer.start()

# ==========================
# 定期実行タスク (深夜0時発動)
# ==========================
async def midnight_attack():
    print("🕛 深夜0時です。タイムリープを開始します...")
    db = SessionLocal()
    try:
        settings = db.query(models.UserSetting).filter(models.UserSetting.is_attack_scheduled.is_(True)).all()
        now = datetime.now()
        limit = now + timedelta(hours=24)

        user_ids = [user.id for user in settings]
        schedules_by_user_id = {}
        if user_ids:
            all_schedules = (
                db.query(models.Schedule)
                .filter(models.Schedule.user_id.in_(user_ids))
                .filter(models.Schedule.scheduled_at >= now)
                .filter(models.Schedule.scheduled_at <= limit)
                .order_by(models.Schedule.user_id, models.Schedule.scheduled_at.asc())
                .all()
            )
            for schedule in all_schedules:
                if schedule.user_id not in schedules_by_user_id:
                    schedules_by_user_id[schedule.user_id] = schedule
        for user in settings:
            upcoming_schedule = schedules_by_user_id.get(user.id)

            if not upcoming_schedule:
                print(f"⏭️ {user.discord_user_id} は予定がないためスキップ")
                user.is_attack_scheduled = False  # type: ignore
                continue
            multiplier = random.randint(1, 4)
            offset = multiplier * 30

            match multiplier:
                case 1: await asyncio.to_thread(change_timezone, PROFILE_GMT9_5)
                case 2: await asyncio.to_thread(change_timezone, PROFILE_GMT10)
                case 3: await asyncio.to_thread(change_timezone, PROFILE_GMT10_5)
                case 4: await asyncio.to_thread(change_timezone, PROFILE_GMT11)
            
            payload = {"action": "shift", "direction": "forward", "offset_minutes": offset}
            await manager.broadcast(payload)
            await asyncio.to_thread(ble_beacon_tx.broadcast_time_burst, offset, repeat_count=5)
            
            user.is_attack_scheduled = False  # type: ignore
            
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
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(midnight_attack, 'cron', minute='*') # テスト用
    scheduler.start()
    print("⏰ スケジューラーが起動しました")

    print("📡 BLEプロビジョニングサーバーを起動中...")
    ble_task = asyncio.create_task(run_ble_server())
    
    global button
    try:
        button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
        button.when_pressed = on_press
        button.when_released = on_release
        print(f"✅ GPIO {BUTTON_PIN} is ready.")
    except Exception as e:
        print(f"⚠️ GPIO Init Error: {e}")

    yield
    
    print("🛑 サーバー停止中。")
    ble_task.cancel()

# ==========================
# FastAPI アプリ定義
# ==========================
app = FastAPI(lifespan=lifespan)

@app.get("/setup")
def get_setup_page():
    # 🌟 ファイル名を setup.html に変更しました！
    return FileResponse("static/setup.html")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PlanRequest(BaseModel):
    discord_user_id: str

@app.post("/api/schedules/")
def create_schedule_from_mentions(req: schemas.ScheduleCreate, db: Session = Depends(get_db)):
    result = crud.add_schedules_for_mentions(
        db=db,
        mentioned_discord_ids=req.mentioned_discord_ids,
        date_str=req.date,
        time_str=req.time,
        title=req.title,
    )
    for discord_id in result["saved_ids"]:
        crud.schedule_attack(db, discord_id)
        print(f"🎯 [予約完了] DiscordID: {discord_id} 攻撃フラグON")
    return {"status": "success", "saved_ids": result["saved_ids"]}

@app.websocket("/ws/windows")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/api/plan/")
def register_plan(plan: PlanRequest, db: Session = Depends(get_db)):
    crud.schedule_attack(db, plan.discord_user_id)
    return {"status": "success"}