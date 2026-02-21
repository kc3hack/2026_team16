from datetime import datetime, timedelta
from database import SessionLocal
import models

# ★これが「深夜0時」に実行される関数
def update_daily_offsets():
    print("=== [Scheduler] Daily Time Hacking Started ===")
    
    # DBセッションを新しく作る（APIの外で動くため）
    db = SessionLocal()
    
    try:
        # 全ユーザーを取得
        users = db.query(models.User).all()
        
        # 明日の日付範囲を設定
        tomorrow = datetime.now() + timedelta(days=1)
        start_of_tomorrow = tomorrow.replace(hour=0, minute=0, second=0)
        end_of_tomorrow = tomorrow.replace(hour=23, minute=59, second=59)

        for user in users:
            # そのユーザーの「明日の予定」があるか探す
            upcoming_schedules = db.query(models.Schedule).filter(
                models.Schedule.user_id == user.id,
                models.Schedule.original_start_time >= start_of_tomorrow,
                models.Schedule.original_start_time <= end_of_tomorrow
            ).first()

            if upcoming_schedules:
                # 予定があるなら、時空を歪める（例: +60分）
                print(f"User {user.username}: 明日予定あり。時間を進めます。")
                user.current_offset_minutes = 60 # type: ignore
            else:
                # 予定がないなら、時間を元に戻す
                print(f"User {user.username}: 明日予定なし。時間を戻します。")
                user.current_offset_minutes = 0 # type: ignore
            
        # 変更を保存
        db.commit()
        print("=== [Scheduler] All users updated successfully ===")

    except Exception as e:
        print(f"Error in scheduler: {e}")
        db.rollback()
    finally:
        db.close()