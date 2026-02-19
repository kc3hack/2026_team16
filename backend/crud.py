# crud.py
from sqlalchemy.orm import Session
import models

# ＝＝＝ ① Discord Botが動いた時に「保存」する処理 ＝＝＝
def upsert_user_setting(db: Session, discord_id: str, device_id: str, offset: int):
    """
    ユーザー設定を保存する。
    既に登録されているユーザーなら上書き更新し、新規なら新しく作成する。
    """
    setting = db.query(models.UserSetting).filter(models.UserSetting.discord_user_id == discord_id).first()
    
    if setting:
        # 既にいれば上書き更新
        setting.mdm_device_id = device_id # type: ignore
        setting.offset_minutes = offset # type: ignore
    else:
        # いなければ新規作成
        setting = models.UserSetting(
            discord_user_id=discord_id,
            mdm_device_id=device_id,
            offset_minutes=offset
        )
        db.add(setting)
    
    db.commit()
    db.refresh(setting)
    return setting

# ＝＝＝ ② 毎日0時に「取り出す」処理 ＝＝＝
def get_all_settings(db: Session):
    """
    登録されているすべてのユーザー設定をリストで取得する。
    深夜0時の自動実行時に使用する。
    """
    return db.query(models.UserSetting).all()