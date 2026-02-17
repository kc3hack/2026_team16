from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import models, schemas

def get_attack_config(db: Session) -> int:
    """
    DBの SystemConfig テーブルから攻撃設定（何分ずらすか）を取得する
    レコードがない場合はデフォルト値（60分）を返す
    """
    try:
        # 最新の設定を取得（通常は1行だけ入っている想定）
        config = db.query(models.SystemConfig).first()
        
        if config:
            return config.default_attack_offset_minutes # type: ignore
        else:
            # まだ設定がない場合は初期データを作成して返す
            new_config = models.SystemConfig(default_attack_offset_minutes=60)
            db.add(new_config)
            db.commit()
            return 60
    
    except Exception as e:
        print(f"⚠️ DB Read Error: {e}")
        return 60  # エラー時は安全策で60分

# --- ユーザー関連 ---
def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def create_user(db: Session, user: schemas.UserCreate):
    db_user = models.User(username=user.username)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# --- 時間操作関連 ---
def update_offset(db: Session, user_id: int, offset_minutes: int):
    db_user = get_user(db, user_id)
    if db_user:
        db_user.current_offset_minutes = offset_minutes # type: ignore
        db.commit()
        db.refresh(db_user)
    return db_user

# --- 予定（スケジュール）関連 ---

# 1. 予定を作成する
def create_schedule(db: Session, schedule: schemas.ScheduleCreate, user_id: int):
    # PydanticモデルをDBモデルに変換
    # ※ Pydantic v2の場合は model_dump(), v1の場合は dict() を使います
    # エラーが出る場合は schedule.dict() に変えてください
    db_schedule = models.Schedule(
        **schedule.model_dump(),
        user_id=user_id
    )
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    return db_schedule

# 2. 直近の予定を取得する（自動判定ロジック用）
# 「現在時刻〜24時間後」の間に予定があるかチェックします
def get_upcoming_events(db: Session, user_id: int, hours_ahead: int = 24):
    now = datetime.now()
    limit_time = now + timedelta(hours=hours_ahead)
    
    return db.query(models.Schedule).filter(
        models.Schedule.user_id == user_id,
        models.Schedule.original_start_time >= now,
        models.Schedule.original_start_time <= limit_time
    ).first()