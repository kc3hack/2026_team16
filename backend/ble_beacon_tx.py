import subprocess
import time
from datetime import datetime
import sys

# ===== 設定 =====
DEVICE_NAME = b"TimeFaker_TX"

def execute_cmd(cmd):
    """コマンドを実行し、エラーを無視して続行する"""
    try:
        subprocess.run(cmd, shell=True, capture_output=True, check=False)
    except Exception as e:
        print(f"Command Error: {e}")

def build_adv_payload(hh, mm, ss, offset_min):
    """BLEアドバタイズメントのペイロード（生データ）を構築する"""
    
    # Pythonでマイナスの値を8ビットの符号付き整数（2の補数）に変換
    offset_hex = offset_min & 0xFF
    
    # 1. Manufacturer Specific Data (ESP32のコードと完全一致)
    # [Length, Type(0xFF), Version, HH, MM, SS, Offset, Reserved]
    mfg_data = [
        0x07,  # 長さ (7バイト)
        0xFF,  # タイプ: Manufacturer Specific Data
        0x01,  # Version
        hh,    # Hour
        mm,    # Minute
        ss,    # Second
        offset_hex, # Offset (signed)
        0x01   # Reserved
    ]
    
    # 2. Local Name (デバイス名 "TimeFaker_TX")
    name_data = [len(DEVICE_NAME) + 1, 0x09] + list(DEVICE_NAME)
    
    # データを結合
    adv_payload = mfg_data + name_data
    total_active_len = len(adv_payload)
    
    # hcitoolの仕様に合わせて、合計31バイトになるように0x00でパディング(埋める)
    adv_payload += [0x00] * (31 - len(adv_payload))
    
    return total_active_len, adv_payload

def broadcast_time_burst(offset_min, repeat_count=3, interval_ms=100):
    """現在時刻を取得し、バースト送信（複数回連続で電波を更新）する"""
    
    for i in range(repeat_count):
        # ラズパイのシステム時刻を取得！
        now = datetime.now()
        hh, mm, ss = now.hour, now.minute, now.second
        
        total_len, payload_bytes = build_adv_payload(hh, mm, ss, offset_min)
        
        # バイト配列を16進数の文字列(例: "07 FF 01...")に変換
        hex_payload = " ".join([f"{b:02X}" for b in payload_bytes])
        
        # hcitool用のコマンドを作成 (OGF: 0x08, OCF: 0x0008 -> LE Set Advertising Data)
        cmd_set_data = f"hcitool -i hci0 cmd 0x08 0x0008 {total_len:02X} {hex_payload}"
        
        # 一旦BLE送信を停止 -> データをセット -> 再開
        execute_cmd("hciconfig hci0 noleadv")
        execute_cmd(cmd_set_data)
        execute_cmd("hciconfig hci0 leadv 3") # 3 = スキャン可能・非接続モード
        
        if i == 0: # 最初の1回だけ画面に詳細を出す
            sign = "+" if offset_min >= 0 else ""
            print(f"📡 [BROADCAST] {hh:02}:{mm:02}:{ss:02} offset={sign}{offset_min}min")
            print(f"   [Payload] {hex_payload[:total_len*3]}")
            
        time.sleep(interval_ms / 1000.0)

def main():
    print("==================================")
    print("  TimeFaker TX (Raspberry Pi版)")
    print("==================================")
    
    # 初期化：BluetoothアダプタをリセットしてONにする
    execute_cmd("hciconfig hci0 reset")
    execute_cmd("hciconfig hci0 up")
    
    print("System ready!\n")
    print("=== 使用方法 ===")
    print("オフセット値（-120 ~ +120）を入力してEnterを押してください")
    print("例: 5 (5分進める), -10 (10分遅らせる), 0 (オフセットなし)")
    print("終了するには Ctrl+C を押してください\n")
    
    try:
        while True:
            user_input = input("> オフセットを入力: ").strip()
            
            if not user_input:
                continue
                
            try:
                offset = int(user_input)
                if offset < -120 or offset > 120:
                    print("⚠️ エラー: オフセットは -120 ~ +120 の範囲で入力してください")
                else:
                    sign = "+" if offset >= 0 else ""
                    print(f"🔄 オフセット設定: {sign}{offset} 分 → BLE送信準備中...")
                    
                    # 3回バースト送信
                    broadcast_time_burst(offset, repeat_count=3, interval_ms=100)
                    print("✅ BLE送信完了\n")
                    
            except ValueError:
                print("⚠️ エラー: 数字を入力してください")
                
    except KeyboardInterrupt:
        print("\n🛑 プログラムを終了します。Bluetoothを元の状態に戻します...")
        execute_cmd("hciconfig hci0 noleadv") # 電波を止める
        sys.exit(0)

if __name__ == "__main__":
    main()