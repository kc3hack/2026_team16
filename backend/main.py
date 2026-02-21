import os
import random
import time
import threading
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
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
        now = datetime.now()
        limit = now + timedelta(hours=24)

        # 事前に全ユーザー分の24時間以内の最も早い予定をまとめて取得しておく（N+1クエリ回避）
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
                # user_id, scheduled_at の順でソート済みなので、最初の一件がそのユーザーの最も早い予定
                if schedule.user_id not in schedules_by_user_id:
                    schedules_by_user_id[schedule.user_id] = schedule
        for user in settings:
            upcoming_schedule = schedules_by_user_id.get(user.id)

            if not upcoming_schedule:
                print(f"⏭️ {user.discord_user_id} は24時間以内に予定がないためスキップします")
                user.is_attack_scheduled = False  # type: ignore
                continue
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
    
    # スケジューラー起動
    scheduler = AsyncIOScheduler()
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

    # 🌟 🆕 予定が保存されたユーザー（saved_ids）全員の「攻撃フラグ」をONにする！
    for discord_id in result["saved_ids"]:
        crud.schedule_attack(db, discord_id)
        print(f"🎯 [予約完了] DiscordID: {discord_id} の攻撃フラグをONにしました！")

    return {
        "status": "success",
        "saved_ids": result["saved_ids"],
        "skipped_ids": result["skipped_ids"],
        "date": req.date,
        "time": req.time,
        "title": req.title,
    }

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
    print(f"🎯 [予約完了] DiscordID: {plan.discord_user_id} の攻撃フラグをONにしました！(ズレ時間は深夜0時に決定)")
    return {"status": "success", "message": "攻撃予約完了（ズレ時間は実行時にランダムで決まります）"}