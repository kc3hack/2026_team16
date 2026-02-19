import asyncio
import websockets
import json
import windows_utils  # 先ほど修正した呪文ファイルを読み込む

# ★ここにラズパイのIPアドレスを入れてください（例: "192.168.1.15" など）
RASPBERRY_PI_IP = "192.168.1.99"
WS_URL = f"ws://{RASPBERRY_PI_IP}:8000/ws/windows"

async def listen_to_pi():
    print(f"🔄 ラズパイ({WS_URL}) に接続を試みます...")
    try:
        # ラズパイのトンネルに接続
        async with websockets.connect(WS_URL) as websocket:
            print("✅ 接続成功！ラズパイからの命令を待機しています...\n")
            
            while True:
                # 永遠に命令を待ち続ける
                message = await websocket.recv()
                data = json.loads(message)
                
                action = data.get("action")
                
                # --- 攻撃命令（時間をずらす） ---
                if action == "shift":
                    offset = data.get("offset_minutes", 60)
                    print(f"🚨 【攻撃命令を受信】時計を {offset} 分進めます！")
                    try:
                        # 修正済みの windows_utils の関数を呼ぶ
                        windows_utils.set_timezone_offset(offset)
                        print(f"✅ 時間の書き換えに成功しました！（+{offset}分）")
                    except Exception as e:
                        print(f"❌ 書き換え失敗 (管理者権限で実行していますか？): {e}")
                        
                # --- 復旧命令（時間を戻す） ---
                elif action == "restore":
                    print("🛡️ 【復旧命令を受信】時計を元の日本標準時に戻します！")
                    try:
                        # 修正済みの 復旧用関数を呼ぶ
                        windows_utils.restore_timezone()
                        print("✅ 復旧に成功しました！(JSTに戻りました)")
                    except Exception as e:
                        print(f"❌ 復旧失敗: {e}")

    # 通信が途切れたり、ラズパイが再起動したときの処理
    except Exception as e:
        print(f"❌ 通信エラー: {e}")
        print("5秒後に再接続を試みます...")
        await asyncio.sleep(5)
        await listen_to_pi() # 自動で再接続ループに入る

if __name__ == "__main__":
    print("=====================================")
    print("  Time Hacker Client (Windows版)  ")
    print("=====================================")
    print("※ 注意: このプログラムは「管理者として実行」したコマンドプロンプトで動かしてください！\n")
    
    # 実行
    asyncio.run(listen_to_pi())
