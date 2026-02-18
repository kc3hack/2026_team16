import os
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import Dict, List
from dotenv import load_dotenv

# 自作モジュール
import models, schemas, crud
from database import SessionLocal, engine
from mdm_client import MDMClient  # 🆕 MDMクライアントをインポート

# 環境変数の読み込み (プロファイルID取得用)
load_dotenv()
PROFILE_TOKYO = os.getenv("MDM_PROFILE_TOKYO")
PROFILE_WARP = os.getenv("MDM_PROFILE_HONGKONG")  # 時空を歪ませる用（+8:00など）

# DBテーブル作成
models.Base.metadata.create_all(bind=engine)

# ==========================
#  MDM クライアント初期化
# ==========================
mdm_client = MDMClient()  # 🆕 インスタンス作成

# ==========================
#  WebSocket 接続管理マネージャー
# ==========================
class ConnectionManager:
    def __init__(self):
        # user_id ごとに接続されているデバイス(WebSocket)をリストで保持
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        print(f"[WebSocket] User {user_id} connected. Active devices: {len(self.active_connections[user_id])}")

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        print(f"[WebSocket] User {user_id} disconnected.")

    async def broadcast_to_user(self, user_id: int, message: dict):
        """特定のユーザーの全デバイスにJSON形式で命令を送る"""
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(message)
            print(f"[WebSocket] Broadcasted to User {user_id}: {message}")

manager = ConnectionManager()


# ==========================
#  バッチ処理: 0:00に時空を歪ませる
# ==========================
async def update_daily_offsets_and_push():
    print("🕛 0:00になりました。時空の歪みを計算します...")
    
    # 新しいDBセッションを作成
    db = SessionLocal()
    try:
        # 全ユーザーを取得
        users = crud.get_users(db)
        
        for user in users:
            # 1. 今日の予定があるかチェック
            has_plan = crud.has_plan_today(db, user.id)
            
            # 2. ズレ時間を決定 (予定ありなら60分進める、なしなら0分に戻す)
            new_offset = 60 if has_plan else 0
            
            # 3. DBを更新
            crud.update_offset(db, user_id=user.id, offset_minutes=new_offset)
            
            # 4. WebSocketでアプリ画面(React等)に指令を飛ばす
            message = {
                "type": "OFFSET_UPDATE",
                "offset_minutes": new_offset,
                "reason": "DAILY_UPDATE"
            }
            await manager.broadcast_to_user(user.id, message)
            
            # 5. 🆕 MDMで物理デバイスのタイムゾーンを強制変更
            # ズレがある(60分)ならWARP用、ない(0分)ならTOKYO用を適用
            target_profile = PROFILE_WARP if new_offset > 0 else PROFILE_TOKYO
            
            if target_profile:
                print(f"📱 MDM Sending: User {user.id} -> Profile {target_profile}")
                # ※注: 今回はデモ用として.envのDEVICE_IDに固定送信します
                # 複数ユーザー対応時はuserテーブルにdevice_idカラムを持たせて分岐させます
                mdm_client.change_timezone(target_profile)
            
            status = "歪ませました(+60min)" if has_plan else "正常に戻しました(0min)"
            print(f"User {user.id}: {status}")
            
    except Exception as e:
        print(f"❌ バッチ処理エラー: {e}")
    finally:
        db.close()

# --- スケジューラーの設定 ---
scheduler = AsyncIOScheduler()
scheduler.add_job(update_daily_offsets_and_push, 'cron', hour=0, minute=0)

# --- ライフスパンイベント（起動時と終了時の処理） ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Scheduler...")
    scheduler.start()
    yield
    print("Stopping Scheduler...")
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

# --- 依存関係 (DBセッション取得) ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================
#          API 定義
# ==========================

# 0. WebSocketエンドポイント
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)


# 1. ユーザー作成 (Botが自動登録する際にも使用)
@app.post("/users/", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    return crud.create_user(db=db, user=user)


# 2. Discord ID からユーザーを検索 (Bot用)
@app.get("/users/discord/{discord_user_id}", response_model=schemas.User)
def read_user_by_discord(discord_user_id: str, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_discord_id(db, discord_user_id=discord_user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


# 3. 現在のズレ時間を取得
@app.get("/offset/{user_id}", response_model=schemas.User)
def read_user_offset(user_id: int, db: Session = Depends(get_db)):
    db_user = crud.get_user(db, user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


# 4. 手動で時間をずらす (テスト用 & 即時反映)
@app.put("/offset/{user_id}")
async def update_time(user_id: int, time_data: schemas.TimeUpdate, db: Session = Depends(get_db)):
    # DB更新
    updated_user = crud.update_offset(db, user_id=user_id, offset_minutes=time_data.offset_minutes)
    if updated_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    # WebSocket通知（アプリ画面用）
    await manager.broadcast_to_user(user_id, {
        "type": "OFFSET_UPDATE",
        "offset_minutes": time_data.offset_minutes,
        "reason": "MANUAL_UPDATE"
    })

    # 🆕 MDMで物理デバイス変更
    # offsetが0なら東京、それ以外なら時空歪曲
    target_profile = PROFILE_WARP if time_data.offset_minutes > 0 else PROFILE_TOKYO
    if target_profile:
        print(f"📱 MDM Manual Update: Applying Profile {target_profile}")
        mdm_client.change_timezone(target_profile)
    
    return {"message": f"User {user_id}'s time has been shifted by {time_data.offset_minutes} minutes."}


# 5. 予定作成 (Bot用)
@app.post("/users/{user_id}/schedules/", response_model=schemas.Schedule)
def create_schedule(user_id: int, schedule: schemas.ScheduleCreate, db: Session = Depends(get_db)):
    return crud.create_schedule(db=db, schedule=schedule, user_id=user_id)

# 6. 🆕 デバッグ用エンドポイント (MDM疎通確認用)
@app.post("/debug/mdm/reset")
def debug_reset_timezone():
    """強制的に東京時間に戻す（デバッグ用）"""
    if PROFILE_TOKYO:
        mdm_client.change_timezone(PROFILE_TOKYO)
        return {"status": "Reset command sent", "profile": PROFILE_TOKYO}
    return {"status": "Error", "detail": "PROFILE_TOKYO not set in .env"}