# crud.py
from sqlalchemy.orm import Session
import models
import random

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

# ＝＝＝ ③ スマホ(BLE)から初期設定された時の処理 ＝＝＝
def register_user_from_ble(db: Session, discord_id: str):
    """
    BLE通信でDiscord IDが送られてきた時の処理。
    既存ユーザーなら設定を壊さないように何もしない。新規なら枠だけ作る。
    """
    setting = db.query(models.UserSetting).filter(models.UserSetting.discord_user_id == discord_id).first()
    
    if not setting:
        # まだデータベースにいない新規ユーザーなら、初期値で作成
        setting = models.UserSetting(
            discord_user_id=discord_id,
            mdm_device_id="",  # デバイスIDは未定なので空文字（またはNone）
            offset_minutes=0   # ズレ時間も初期値の0
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)
        print(f"✨ 新規ユーザー '{discord_id}' をDBに登録しました！")
    else:
        print(f"👍 ユーザー '{discord_id}' は既に存在するため、既存の設定を維持します。")
        
    return setting

def schedule_attack(db: Session, discord_id: str):
    # ユーザーを探す
    user_setting = db.query(models.UserSetting).filter(models.UserSetting.discord_user_id == discord_id).first()
    
    if user_setting:
        # 既にユーザーがいれば、攻撃予定フラグだけをONにする
        user_setting.is_attack_scheduled = True # type: ignore
    else:
        # もしDBにユーザーがいなければ、新規作成してフラグをONにする
        user_setting = models.UserSetting(
            discord_user_id=discord_id,
            mdm_device_id="",  # 初期値
            offset_minutes=0,  # 実行時に決めるので0でOK
            is_attack_scheduled=True
        )
        db.add(user_setting)
        
    db.commit()
    db.refresh(user_setting)
    
    # 以前は offset（ズレ時間）を返していましたが、
    # 今回からは「成功したかどうかのTrue」だけを返します
    return True

# ＝＝＝ ④ DiscordIDにGmailを紐付ける処理 ＝＝＝
def register_gmail(db: Session, discord_id: str, gmail: str):
    """
    DiscordIDに対してGmailアドレスを登録する。
    既存ユーザーならGmailを更新し、新規なら枠を作って登録する。
    """
    setting = db.query(models.UserSetting).filter(
        models.UserSetting.discord_user_id == discord_id
    ).first()

    if setting:
        # 既にいれば Gmail だけ上書き更新
        setting.gmail = gmail  # type: ignore
        print(f"📧 ユーザー '{discord_id}' のGmailを更新しました: {gmail}")
    else:
        # いなければ新規作成
        setting = models.UserSetting(
            discord_user_id=discord_id,
            gmail=gmail
        )
        db.add(setting)
        print(f"✨ 新規ユーザー '{discord_id}' をGmail '{gmail}' で登録しました！")

    db.commit()
    db.refresh(setting)
    return setting
