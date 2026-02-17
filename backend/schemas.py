from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# --- 共通設定 ---
class UserBase(BaseModel):
    username: str
    # DiscordのID（文字列）を受け取れるように追加
    discord_user_id: Optional[str] = None 

# --- ユーザー関連 ---
class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    current_offset_minutes: int
    is_active: bool
    
    class Config:
        from_attributes = True

# --- 時間変更関連 ---
class TimeUpdate(BaseModel):
    offset_minutes: int

# --- 予定（スケジュール）関連 ---
class ScheduleCreate(BaseModel):
    title: str
    original_start_time: datetime
    source: str = "discord"

class Schedule(BaseModel):
    id: int
    user_id: int
    title: str
    original_start_time: datetime
    # models.py に hacked_start_time がないので、ここは削除しておきます（整合性重視）
    source: str
    is_processed: bool

    class Config:
        from_attributes = True