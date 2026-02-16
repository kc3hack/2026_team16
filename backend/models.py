from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base # FastAPI標準のBase

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    discord_user_id = Column(String, unique=True, nullable=True) # Discord ID連携
    
    # 核心機能: 現在適用されている「時間のズレ」（分単位）
    # 例: 60なら「実時間より60分進める」
    current_offset_minutes = Column(Integer, default=0)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # リレーション
    devices = relationship("Device", back_populates="owner")
    schedules = relationship("Schedule", back_populates="owner")

class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    device_name = Column(String) # "Living Room Clock", "Main PC"
    device_type = Column(String) # "windows", "android", "physical_clock"
    ip_address = Column(String, nullable=True)
    
    status = Column(String, default="offline") # status管理用
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="devices")

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    title = Column(String)
    original_start_time = Column(DateTime) # 本来の開始時間
    
    source = Column(String) # "discord", "google_calendar"
    is_processed = Column(Boolean, default=False) # 既にこの予定に合わせて時間をずらしたか

    owner = relationship("User", back_populates="schedules")