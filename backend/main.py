from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from gpiozero import Button
from datetime import datetime
import time
import threading  # ★ 追加：別スレッドで裏作業をさせるため

# 自作モジュール
import models, schemas, crud
from database import SessionLocal, engine
import android_mdm

# DBテーブル作成
models.Base.metadata.create_all(bind=engine)

# --- スケジューラーの設定 ---
scheduler = BackgroundScheduler()

def midnight_job():
    print("🕛 深夜0時: 時間変更の定期処理が発動しました！")
    db = SessionLocal()
    try:
        settings = crud.get_all_settings(db)
        push_time = datetime.now()
        
        if not settings:
            print("⚠️ DBにターゲットがいません。処理をスキップします。")
            
        for user in settings:
            print(f"🎯 [定期実行] ターゲット: {user.discord_user_id} を {user.offset_minutes}分 ずらします")
            android_mdm.execute_attack(offset_minutes=user.offset_minutes, timestamp=push_time) # type: ignore
    except Exception as e:
        print(f"⚠️ 定期実行エラー: {e}")
    finally:
        db.close()

# --- GPIO設定 ---
BUTTON_PIN = 17
button = None
press_start_time = 0

def on_press():
    global press_start_time
    press_start_time = time.time()
    print("🔘 [Button] 押されました。時間計測スタート...")

# ★ 新規追加：ボタンが離された「後」に裏で走る重い処理
def execute_button_action(press_duration):
    if press_duration <= 3.0:
        print("⚡ 【短押し検知】時間をずらします（攻撃実行）")
        db = SessionLocal()
        try:
            settings = crud.get_all_settings(db)
            push_time = datetime.now()
            
            if not settings:
                print("⚠️ DBにターゲットがいません。攻撃をスキップします。")
                
            for user in settings:
                print(f"🎯 ターゲット: {user.discord_user_id} を {user.offset_minutes}分 ずらします")
                android_mdm.execute_attack(offset_minutes=user.offset_minutes, timestamp=push_time) # type: ignore
        finally:
            db.close()
    else:
        print("🛡️ 【長押し検知】時間を元に戻します（復旧実行）")
        android_mdm.stop_attack()

# ★ 修正：監視員は「押された時間を計算して、裏方に丸投げする」だけ！
def on_release():
    global press_start_time
    press_duration = time.time() - press_start_time
    print(f"🔘 [Button] 離されました。押下時間: {press_duration:.2f}秒")

    # 別スレッド（裏の作業員）に処理を任せて、ボタン監視自体は一瞬で終わらせる
    threading.Thread(target=execute_button_action, args=(press_duration,)).start()

# --- ライフスパンイベント ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Scheduler...")
    scheduler.start()
    global button
    try:
        # bounce_time を 0.1 から 0.05 に変更し、少しだけ敏感にしました
        button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
        button.when_pressed = on_press
        button.when_released = on_release
        print(f"✅ GPIO {BUTTON_PIN} is ready.")
    except Exception as e:
        print(f"⚠️ GPIO Init Error: {e}")
    yield
    print("Stopping Scheduler...")
    scheduler.shutdown()

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