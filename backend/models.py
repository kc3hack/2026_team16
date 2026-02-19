# models.py
from sqlalchemy import Column, Integer, String
from database import Base

class UserSetting(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    # 1. ユーザーID（DiscordのIDを想定）
    discord_user_id = Column(String, unique=True, index=True) 
    
    # 2. 登録デバイス（MDMのデバイスIDなどを想定）
    mdm_device_id = Column(String, nullable=True) 
    
    # 3. 適用する時間のズレ（オフセット値、分単位）
    offset_minutes = Column(Integer, default=0)