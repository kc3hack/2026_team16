import os
import random
import time
import threading
import asyncio
import uvicorn
from dotenv import load_dotenv
from datetime import datetime, timedelta
import ble_test
import subprocess
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from pydantic import BaseModel

import RPi.GPIO as GPIO 

# 自作モジュール
import models
import crud
import google_calendar
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

def change_timezone(profile_id):
    mdm_client = MDMClient()
    ok = mdm_client.change_timezone(profile_id)
    if not ok:
        print("⚠️ MDMタイムゾーン変更に失敗しました")
        return False
    return True

# --- 各アクションの定義 ---

def execute_shift_action():
    print("⚡ 【シングルクリック検知】時間をランダムにずらします！")
    multiplier = random.randint(1, 4)
    offset = multiplier * 30
    print(f"🎲 パターン{multiplier} -> {offset}分")

    match multiplier:
        case 1: change_timezone(PROFILE_GMT9_5)
        case 2: change_timezone(PROFILE_GMT10)
        case 3: change_timezone(PROFILE_GMT10_5)
        case 4: change_timezone(PROFILE_GMT11)
    
    payload = {"action": "shift", "direction": "forward", "offset_minutes": offset}
    if loop:
        print(f"💻 Windows PCへ送信: {offset}分進める")
        asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)
            
    ble_beacon_tx.broadcast_time_burst(offset, repeat_count=3, interval_ms=100)

def execute_pairing_mode():
    print("\n🔗 【ダブルクリック検知】ペアリングモードを起動します！")
    ble_test.pairing_mode_active = True  # type: ignore
    print("🔵 3分間、WebからのWi-Fi設定を受付開始します...")

    def disable_mode():
        if ble_test.pairing_mode_active:  # type: ignore
            ble_test.pairing_mode_active = False  # type: ignore
            print("⏳ タイムアップ: ペアリングモードを終了しました。")
    threading.Timer(180.0, disable_mode).start()

def execute_restore_action():
    print("\n🛡️ 【長押し検知】時間を元に戻す(復旧)命令を送信します！")
    if PROFILE_TOKYO:
        success = change_timezone(PROFILE_TOKYO)
        if success:
            print("✅ MDM復旧命令の送信に成功しました")
    
    payload = {"action": "restore", "direction": "none", "offset_minutes": 0}
    if loop:
        print("💻 Windows PCへ送信: 時間を元に戻す")
        asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)
        
    ble_beacon_tx.broadcast_time_burst(0, repeat_count=3, interval_ms=100)

# ==========================
# GPIO: ボタンとセンサー (RPi.GPIO版)
# ==========================
BUTTON_PIN = 17  # 物理ピン 11番
SENSOR_PIN = 12  # 物理ピン 32番

click_count = 0
click_timer = None

def evaluate_clicks():
    global click_count
    if click_count == 1:
        execute_shift_action()
    elif click_count >= 2:
        execute_pairing_mode()
    click_count = 0

async def poll_button():
    """バックグラウンドでボタンを100%確実に監視するタスク"""
    global click_count, click_timer
    
    last_state = GPIO.HIGH
    press_start_time = 0

    while True:
        try:
            state = GPIO.input(BUTTON_PIN)
            
            if state != last_state:  # 状態が変化した！
                if state == GPIO.LOW:  # 押された
                    press_start_time = time.time()
                    print("🔘 [Button] 押されました...")
                else:  # 離された
                    if press_start_time != 0:
                        press_duration = time.time() - press_start_time
                        print(f"🔘 [Button] 離されました ({press_duration:.2f}s)")

                        if press_duration >= 4.0:
                            click_count = 0
                            if click_timer: click_timer.cancel()
                            execute_restore_action()
                        else:
                            click_count += 1
                            if click_timer: click_timer.cancel()
                            click_timer = threading.Timer(0.4, evaluate_clicks)
                            click_timer.start()
                        press_start_time = 0
                last_state = state

        except Exception as e:
            print(f"⚠️ ボタン監視エラー: {e}")
            
        await asyncio.sleep(0.05)  # 50ミリ秒ごとにチェック（チャタリング防止＆負荷軽減）

def read_sensor_state() -> dict:
    """センサーの現在の明暗状態を返すヘルパー"""
    try:
        val = GPIO.input(SENSOR_PIN)
        is_dark = (val == GPIO.HIGH) # HIGH=1=暗い, LOW=0=明るい
        return {
            "status": "ok",
            "gpio_pin": SENSOR_PIN,
            "physical_pin": 32,
            "state": "DARK" if is_dark else "BRIGHT",
            "raw": val,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
    
    # --- RPi.GPIO の初期設定 ---
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    
    # ボタン (プルアップ抵抗をONにして待機)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    print(f"✅ Button : GPIO{BUTTON_PIN} (物理ピン11番) ready.")
    
    # センサー
    GPIO.setup(SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    sensor_status = read_sensor_state()
    print(f"✅ Sensor : GPIO{SENSOR_PIN} (物理ピン32番) ready. 現在: {sensor_status.get('state')}")

    # ボタン監視用のバックグラウンドタスクを起動
    asyncio.create_task(poll_button())

    scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")
    scheduler.add_job(midnight_attack, 'cron', minute='*')
    scheduler.start()
    print("⏰ スケジューラーが起動しました")

    print("📡 BLEプロビジョニングサーバーを起動中...")
    ble_task = asyncio.create_task(run_ble_server())

    yield
    
    print("🛑 サーバー停止中。GPIOをクリーンアップします...")
    ble_task.cancel()
    GPIO.cleanup()

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
    date: Optional[str] = None
    time: Optional[str] = None
    task: Optional[str] = None

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
    user = db.query(models.UserSetting).filter(models.UserSetting.discord_user_id == plan.discord_user_id).first()

    if not user:
        return {"status": "error", "message": "ユーザーが未登録です。先に設定画面から登録してください。"}

    calendar_registered = False
    
    if (user.google_access_token is not None and user.google_refresh_token is not None and plan.date is not None and plan.time is not None and plan.task is not None):
        try:
            google_calendar.add_event_to_calendar(
                access_token=str(user.google_access_token),    # type: ignore
                refresh_token=str(user.google_refresh_token),  # type: ignore
                date=str(plan.date),
                time=str(plan.time),
                task=str(plan.task),
            )
            calendar_registered = True
        except Exception as e:
            print(f"⚠️ Googleカレンダー登録エラー: {e}")

    return {
        "status": "success",
        "message": "攻撃予約完了",
        "user_id": user.id,  # type: ignore
        "offset_minutes": user.offset_minutes,  # type: ignore
        "attack_scheduled": user.is_attack_scheduled,  # type: ignore
        "calendar_registered": calendar_registered,
    }

@app.get("/auth/google")
def google_auth(discord_user_id: str):
    auth_url = google_calendar.get_auth_url(discord_user_id)
    return {"auth_url": auth_url}

@app.get("/auth/callback")
def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    discord_user_id = state
    tokens = google_calendar.exchange_code_for_tokens(code)

    user = db.query(models.UserSetting).filter(models.UserSetting.discord_user_id == discord_user_id).first()
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
    return {"認証完了": "✅ Googleカレンダーへのアクセスが許可されました！"}

class RegisterRequest(BaseModel):
    discord_user_id: str
    gmail: str

@app.post("/api/register/")
def register_gmail_endpoint(req: RegisterRequest, db: Session = Depends(get_db)):
    user = crud.register_gmail(db, req.discord_user_id, req.gmail)
    return {"status": "success", "discord_user_id": user.discord_user_id, "gmail": user.gmail}

@app.get("/api/user/{discord_user_id}")
def get_user_info(discord_user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.UserSetting).filter(models.UserSetting.discord_user_id == discord_user_id).first()
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

@app.get("/api/schedule/{discord_user_id}")
def get_schedule(discord_user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.UserSetting).filter(models.UserSetting.discord_user_id == discord_user_id).first()
    if not user:
        return {"status": "not_found", "message": "DBに登録されていません。"}
    if user.google_access_token is None or user.google_refresh_token is None:
        return {"status": "not_authorized", "message": "Googleカレンダーの認証が完了していません。"}

    try:
        events = google_calendar.get_upcoming_events(
            access_token=str(user.google_access_token),    # type: ignore
            refresh_token=str(user.google_refresh_token),  # type: ignore
            max_results=5
        )
        return {"status": "success", "events": events}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/sensor/status")
def get_sensor_status():
    """LM393センサーの現在の明暗状態を返す"""
    return read_sensor_state()

@app.get("/api/wifi/ssids")
def get_wifi_ssids():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list", "--rescan", "yes"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr.strip() or "nmcli failed")

        seen = set()
        ssids = []
        for line in result.stdout.splitlines():
            s = line.strip()
            if s and s not in seen:
                seen.add(s)
                ssids.append(s)
        return {"ssids": ssids}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="wifi scan timeout")

@app.get("/setup")
def setup_page():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(BASE_DIR, "setup.html")
    if not os.path.exists(file_path):
        return {"error": f"ファイルが見つかりません: {file_path}"}
    return FileResponse(file_path)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)