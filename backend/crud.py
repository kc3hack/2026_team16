from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
import models, schemas

# --- ユーザー関連 ---
def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_users(db: Session, skip: int = 0, limit: int = 100):
    """全ユーザーを取得する（バッチ処理用）"""
    return db.query(models.User).offset(skip).limit(limit).all()

def create_user(db: Session, user: schemas.UserCreate):
    db_user = models.User(name=user.name)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_offset(db: Session, user_id: int, offset_minutes: int):
    db_user = get_user(db, user_id)
    if db_user:
        db_user.current_offset_minutes = offset_minutes
        db.commit()
        db.refresh(db_user)
    return db_user

# --- スケジュール関連 ---

def create_schedule(db: Session, schedule: schemas.ScheduleCreate, user_id: int):
    db_schedule = models.Schedule(**schedule.dict(), user_id=user_id)
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    return db_schedule

def get_user_schedules(db: Session, user_id: int, skip: int = 0, limit: int = 100):
    return db.query(models.Schedule).filter(models.Schedule.user_id == user_id).offset(skip).limit(limit).all()

def has_plan_today(db: Session, user_id: int) -> bool:
    """
    そのユーザーに今日の予定があるかどうかを判定する
    """
    today = date.today()
    # 00:00:00 から 23:59:59 までの範囲で検索
    start_of_day = datetime.combine(today, datetime.min.time())
    end_of_day = datetime.combine(today, datetime.max.time())
    
    # 予定を検索
    return db.query(models.Schedule).filter(
        models.Schedule.user_id == user_id,
        models.Schedule.scheduled_time >= start_of_day,
        models.Schedule.scheduled_time <= end_of_day
    ).first() is not None