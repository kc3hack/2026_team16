from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

# --- 共通設定 ---
class UserBase(BaseModel):
    username: str

# --- ユーザー関連 ---
class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    current_offset_minutes: int
    is_active: bool
    # created_at: datetime  # 必要ならコメントアウト解除

    class Config:
        from_attributes = True

# --- 時間変更関連 ---
class TimeUpdate(BaseModel):
    offset_minutes: int

# --- 予定（スケジュール）関連 ---
# ★Botが送ってくるデータ
class ScheduleCreate(BaseModel):
    title: str
    original_start_time: datetime
    source: str = "discord"

# ★APIが返すデータ
class Schedule(BaseModel):
    id: int
    user_id: int
    title: str
    original_start_time: datetime
    hacked_start_time: Optional[datetime] = None
    source: str
    is_processed: bool

    class Config:
        from_attributes = True