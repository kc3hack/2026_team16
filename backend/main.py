from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from gpiozero import Button
from datetime import datetime
import time
import threading
import asyncio

# 自作モジュール
import models, schemas, crud
from database import SessionLocal, engine

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

# --- ライフスパンイベント ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    loop = asyncio.get_running_loop()
    
    global button
    try:
        button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
        button.when_pressed = on_press
        button.when_released = on_release
        print(f"✅ GPIO {BUTTON_PIN} is ready.")
    except Exception as e:
        print(f"⚠️ GPIO Init Error: {e}")
    yield
    # アプリ終了時の処理（今は特になし）

app = FastAPI(lifespan=lifespan)

def get_db():
    db = SessionLocal()
    try:
        yield db
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
            # 接続維持のためだけに受信待機（変数は不要）
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