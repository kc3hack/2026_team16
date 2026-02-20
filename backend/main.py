from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from gpiozero import Button
from pydantic import BaseModel
import time
import threading
import asyncio

# 自作モジュール
import models
import schemas
import crud
from database import SessionLocal, engine, Base
from ble_test import run_ble_server  # BLEサーバーの関数

# DBテーブル作成
Base.metadata.create_all(bind=engine)

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

# --- GPIO設定 ---
BUTTON_PIN = 17
button = None
press_start_time = 0

def on_press():
    global press_start_time
    press_start_time = time.time()
    print("🔘 [Button] 押されました。時間計測スタート...")

def execute_button_action(press_duration):
    if press_duration <= 3.0:
        print("⚡ 【短押し検知】Windowsへ時間をずらす命令を送信します！")
        db = SessionLocal()
        try:
            settings = crud.get_all_settings(db)
            if not settings:
                print("⚠️ DBにターゲットがいません。")
                return
            
            offset = settings[0].offset_minutes 
            print(f"🎯 ターゲット設定値: {offset}分 ずらします")
            
            payload = {"action": "shift", "offset_minutes": offset}
            
            if loop:
                asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)
        finally:
            db.close()
    else:
        print("🛡️ 【長押し検知】Windowsへ時間を元に戻す命令を送信します！")
        payload = {"action": "restore"}
        if loop:
            asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)

def on_release():
    global press_start_time
    press_duration = time.time() - press_start_time
    print(f"🔘 [Button] 離されました。押下時間: {press_duration:.2f}秒")
    threading.Thread(target=execute_button_action, args=(press_duration,)).start()

# --- ライフスパンイベント (ここを1つに統合しました) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(midnight_attack, 'cron', minute='*') # テスト用
    # scheduler.add_job(midnight_attack, 'cron', hour=0, minute=0)  毎日0時に実行
    scheduler.start()
    print("⏰ スケジューラーが起動しました（毎日0時実行）")

    # 1. BLEサーバーをバックグラウンドで起動
    print("📡 BLEプロビジョニングサーバーを起動中...")
    ble_task = asyncio.create_task(run_ble_server())
    
    # 1. BLEサーバーをバックグラウンドで起動
    print("📡 BLEプロビジョニングサーバーを起動中...")
    ble_task = asyncio.create_task(run_ble_server())
    
    # 2. GPIOボタンの設定
    global button
    try:
        button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
        button.when_pressed = on_press
        button.when_released = on_release
        print(f"✅ GPIO {BUTTON_PIN} is ready.")
    except Exception as e:
        print(f"⚠️ GPIO Init Error: {e}")

    yield
    
    # --- 終了時の処理 ---
    print("🛑 サーバー停止中。BLEサーバーを終了します...")
    ble_task.cancel()
    try:
        await ble_task
    except asyncio.CancelledError:
        print("✅ BLEサーバーを正常に停止しました。")

# アプリ生成 (統合したlifespanを指定)
app = FastAPI(lifespan=lifespan)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def midnight_attack():
    print("🕛 深夜0時です。タイムリープを開始します...")
    db = SessionLocal()
    try:
        settings = db.query(models.UserSetting).filter(models.UserSetting.is_attack_scheduled == True).all()
        for user in settings:
            payload = {
                "action": "shift",
                "direction": "forward", 
                "offset_minutes": user.offset_minutes
            }
            await manager.broadcast(payload)
            print(f"🚀 {user.discord_user_id} の時間を {user.offset_minutes}分 進めました")
            
            # 攻撃が終わったらフラグを戻す
            user.is_attack_scheduled = False # type: ignore
        db.commit()
    finally:
        db.close()

# ==========================
#          API 定義
# ==========================

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

@app.post("/api/settings/")
def update_setting(setting: schemas.UserSettingCreate, db: Session = Depends(get_db)):
    updated_setting = crud.upsert_user_setting(
        db=db,
        discord_id=setting.discord_user_id,
        device_id=setting.mdm_device_id,
        offset=setting.offset_minutes
    )
    print(f"📥 [DB保存] DiscordID: {setting.discord_user_id}, 端末: {setting.mdm_device_id}, ズレ: {setting.offset_minutes}分")
    return {"status": "success", "message": "設定を保存しました"}

class PlanRequest(BaseModel):
    discord_user_id: str

@app.post("/api/plan/")
def register_plan(plan: PlanRequest, db: Session = Depends(get_db)):
    # crud.pyに作った関数を呼んで、ランダムな時間を生成＆フラグを立てる
    offset = crud.schedule_attack(db, plan.discord_user_id)
    
    print(f"🎯 [予約完了] DiscordID: {plan.discord_user_id} に {offset}分の攻撃をセットしました！")
    return {"status": "success", "message": f"攻撃予約完了（{offset}分）"}