# schemas.py
from pydantic import BaseModel

# ★Discord Botが送ってくるデータの「型」定義
class UserSettingCreate(BaseModel):
    discord_user_id: str
    mdm_device_id: str
    offset_minutes: int