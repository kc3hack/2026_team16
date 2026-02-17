from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from gpiozero import Button
from datetime import datetime
import os

# 自作モジュール
import models, schemas, crud, tasks
from database import SessionLocal, engine
# 攻撃実行用モジュールをインポート
import android_mdm

# DBテーブル作成
models.Base.metadata.create_all(bind=engine)

# --- スケジューラーの設定 ---
scheduler = BackgroundScheduler()

# 【設定】毎日 00:00 に tasks.update_daily_offsets を実行
scheduler.add_job(tasks.update_daily_offsets, 'cron', hour=0, minute=0)

# --- GPIO設定 ---
BUTTON_PIN = 17
button = None

def on_press():
    # 1. 送信時刻を取得
    push_time = datetime.now()
    print(f"\n🔴 [Button] Pressed at {push_time}")

    # 2. DBセッションを開いて設定値を読む
    db = SessionLocal()
    try:
        # DBから「何分ずらすか」を取得
        offset_minutes = crud.get_attack_config(db)
        print(f"📖 [DB] Attack Config Loaded: {offset_minutes} minutes")

        # 3. 時刻と設定値の「2値」を渡して攻撃実行
        android_mdm.execute_attack(offset_minutes=offset_minutes, timestamp=push_time)
        
    except Exception as e:
        print(f"⚠️ Attack Failed: {e}")
    finally:
        db.close()

def on_release():
    print("\n🟢 [Button] Released. Stopping attack...")
    android_mdm.stop_attack()

# --- ライフスパンイベント（起動時と終了時の処理） ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時
    print("Starting Scheduler...")
    scheduler.start()
    # GPIO初期化
    global button
    try:
        button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.1)
        button.when_pressed = on_press
        button.when_released = on_release
        print(f"✅ GPIO {BUTTON_PIN} is ready.")
    except Exception as e:
        print(f"⚠️ GPIO Init Error: {e}")
    yield
    # 終了時
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

# 1. ユーザー作成
@app.post("/users/", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    return crud.create_user(db=db, user=user)

# 2. 現在のズレ時間を取得 (デバイス監視用)
@app.get("/offset/{user_id}", response_model=schemas.User)
def read_user_offset(user_id: int, db: Session = Depends(get_db)):
    db_user = crud.get_user(db, user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

# 3. 手動で時間をずらす (テスト用)
@app.put("/offset/{user_id}")
def update_time(user_id: int, time_data: schemas.TimeUpdate, db: Session = Depends(get_db)):
    updated_user = crud.update_offset(db, user_id=user_id, offset_minutes=time_data.offset_minutes)
    if updated_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": f"User {user_id}'s time has been shifted by {time_data.offset_minutes} minutes."}

# 4. ★新機能: 予定を受け取り、自動で時間を計算する (Discord Bot用)
@app.post("/users/{user_id}/schedules/", response_model=schemas.Schedule)
def create_schedule(user_id: int, schedule: schemas.ScheduleCreate, db: Session = Depends(get_db)):
    # Step 1: 予定をDBに保存
    new_schedule = crud.create_schedule(db=db, schedule=schedule, user_id=user_id)
    
    #イベント発火のタイミングでは，いらないかもしれない
    # # Step 2: バックエンド側で判断（ロジック発動）
    # # 「24時間以内に予定があるか？」を確認
    # upcoming_event = crud.get_upcoming_events(db, user_id=user_id, hours_ahead=24)
    
    # # Step 3: 時間のズレを決定して更新
    # if upcoming_event:
    #     new_offset = 60 # 予定があるなら1時間進める
    #     print(f"Update: 予定あり。Offsetを {new_offset}分 に設定します。")
    # else:
    #     new_offset = 0  # 予定がないなら戻す（仕様による）
    #     print(f"Update: 直近の予定なし。Offsetを {new_offset}分 に設定します。")
        
    # crud.update_offset(db, user_id=user_id, offset_minutes=new_offset)
    
    return new_schedule