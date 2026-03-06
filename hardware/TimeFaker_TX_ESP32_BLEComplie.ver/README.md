# ESP32-S3 Super Mini - BLE COMPILER サンプルファームウェア

このファームウェアは、**BLE経由でファームウェアを書き込めるサンプルプログラム**です。

🌐 **WebApp:** https://ble-compiler.netlify.app/

## 📖 このファームウェアは何をするのか？

このプログラムは以下の機能を提供します：

1. **BLE接続** - iPadやスマホから接続可能
2. **Wi-Fiプロビジョニング** - BLE経由でWi-Fi設定を受信（オプション）
3. **BLE OTA** - BLE経由でファームウェアを更新（USBケーブル不要）
4. **デバッグモニタ** - BLE経由でログをリアルタイム配信
5. **サンプル動作** - 1秒ごとに「Hello World via BLE」を送信

**このサンプル動作（5番）を書き換えて、あなたの実装したい処理を追加できます！**

---

## 🚀 クイックスタート

### 1️⃣ 必要なもの

| 項目             | 詳細                              |
| ---------------- | --------------------------------- |
| **ハード**       | ESP32-S3 Super Mini + USBケーブル |
| **ソフトウェア** | Python 3.x + PlatformIO           |

### 2️⃣ PlatformIOのインストール

**VSCode拡張を使う場合（推奨）:**

1. VSCode をインストール
2. Extension で「PlatformIO」を検索・インストール
3. VSCode を再起動

**CLIを使う場合:**

```bash
pip install platformio
```

### 3️⃣ ファームウェアを書き込む

**方法1: VSCode + PlatformIO（推奨）**

1. VSCode で `MiconSide` フォルダを開く
2. PlatformIO ツールバー → **Build** をクリック
3. ESP32をUSBで接続
4. **Upload** をクリック

**方法2: CLI**

```bash
cd MiconSide
pio run --target upload
```

### 4️⃣ 動作確認

シリアルモニタで以下のようなログが表示されれば成功：

```
=== ESP32-S3 BOOT SEQUENCE STARTING ===
[System] ESP32-S3 Starting...
[Version] FW v1.0.0
[Setup] Initializing WiFi...
[Setup] Initializing BLE...
[I] BLE initialized successfully
[Setup] Initialization complete
```

### 5️⃣ WebAppから接続

1. https://ble-compiler.netlify.app/ を開く
2. **[Connect Device]** をクリックして「ESP32-S3-MICON」を選択
3. **Debug Monitor** パネルで **[Subscribe]** をクリック
4. 1秒ごとに「Hello World via BLE」が表示されることを確認

---

## 🔧 カスタマイズ方法（どこを書き換える？）

### ✅ 基本：サンプル動作を書き換える

`main.cpp` の `loop()` 関数の以下の部分を書き換えてください：

#### 📍 書き換え箇所1: BLE出力（1秒ごと）

```cpp
// ファイル: src/main.cpp
// 行: 1050付近

// BLE Output: Send "Hello World via BLE" every 1 second
static unsigned long last_ble_output = 0;
if (ble_device_connected && pDebugLogTx && millis() - last_ble_output >= BLE_OUTPUT_INTERVAL_MS)
{
    last_ble_output = millis();

    // ★★★ ここを書き換える ★★★
    const char *msg = "Hello World via BLE";
    pDebugLogTx->setValue((uint8_t *)msg, strlen(msg));
    pDebugLogTx->notify();

    // 例: センサー値を送信
    // char msg[64];
    // snprintf(msg, sizeof(msg), "Temperature: %.2f C", readTemperature());
    // pDebugLogTx->setValue((uint8_t *)msg, strlen(msg));
    // pDebugLogTx->notify();

    // Blink status LED when sending BLE message
    status_led_blink_aws();
}
```

**カスタマイズ例:**

```cpp
// 例1: センサー値を送信
float temperature = analogRead(34) * 0.1; // 適当な変換
char msg[64];
snprintf(msg, sizeof(msg), "Temp: %.1f°C", temperature);
pDebugLogTx->setValue((uint8_t *)msg, strlen(msg));
pDebugLogTx->notify();

// 例2: ボタン状態を送信
if (digitalRead(BUTTON_PIN) == LOW) {
    const char *msg = "Button Pressed!";
    pDebugLogTx->setValue((uint8_t *)msg, strlen(msg));
    pDebugLogTx->notify();
}

// 例3: Wi-Fi経由で外部APIにアクセス
if (wifi_mgr_is_connected()) {
    // HTTPClient で外部APIにリクエスト
    // 結果をBLE経由で送信
}
```

#### 📍 書き換え箇所2: setup()関数での初期化

センサーやピンの初期化は `setup()` 関数の最後に追加してください：

```cpp
// ファイル: src/main.cpp
// 行: 900付近

void setup()
{
    // ... 既存の初期化コード ...

    log_println("[Setup] Initialization complete");

    // ★★★ ここにセンサー初期化を追加 ★★★
    // 例: I2Cセンサーの初期化
    // Wire.begin(SDA_PIN, SCL_PIN);
    // if (!sensor.begin()) {
    //     log_println("[E] Sensor init failed");
    // }

    // 例: GPIOピンの初期化
    // pinMode(BUTTON_PIN, INPUT_PULLUP);
    // pinMode(LED_PIN, OUTPUT);
}
```

### ✅ 応用：定数を変更する

#### BLE送信間隔を変更

```cpp
// ファイル: src/main.cpp
// 行: 30付近

#define BLE_OUTPUT_INTERVAL_MS 1000  // ← この値を変更（ミリ秒）

// 例: 5秒ごと
#define BLE_OUTPUT_INTERVAL_MS 5000
```

#### デバイス名を変更

```cpp
// ファイル: src/main.cpp
// 行: 777付近

void init_ble(void)
{
    log_println("[I] Starting BLE device init...");
    BLEDevice::init("ESP32-S3-MICON");  // ← ここを変更

    // 例: 自分の名前にする
    // BLEDevice::init("MyESP32-Device");
}
```

### ✅ 高度：新しいBLEコマンドを追加

`MyCharacteristicCallbacks::onWrite()` に新しいコマンドを追加できます：

```cpp
// ファイル: src/main.cpp
// 行: 250付近

class MyCharacteristicCallbacks : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *pCharacteristic)
    {
        std::string rxValue = pCharacteristic->getValue();
        if (rxValue.length() > 0)
        {
            String command = String(rxValue.c_str());
            command.trim();

            // ... 既存のコマンド処理 ...

            // ★★★ 新しいコマンドを追加 ★★★
            else if (command == "LED_ON")
            {
                digitalWrite(LED_PIN, HIGH);
                log_println("[I] LED turned ON");
            }
            else if (command == "LED_OFF")
            {
                digitalWrite(LED_PIN, LOW);
                log_println("[I] LED turned OFF");
            }
        }
    }
};
```

---

## 📂 ファイル構成

```
MiconSide/
├── src/
│   └── main.cpp                 # メインプログラム（ここを編集）
├── platformio.ini               # PlatformIO設定
├── partitions_ota_2m.csv        # OTA対応パーティションテーブル
├── partitions.csv               # 標準パーティションテーブル
└── README.md                    # このファイル
```

---

## 🔍 主要な関数とグローバル変数

| 関数/変数                 | 説明                                  |
| ------------------------- | ------------------------------------- |
| `setup()`                 | 起動時の初期化処理                    |
| `loop()`                  | メインループ（ここを主に書き換える）  |
| `log_println(msg)`        | BLE経由でログを送信                   |
| `ble_device_connected`    | BLE接続状態（true/false）             |
| `pDebugLogTx`             | BLE経由でログを送信するCharacteristic |
| `wifi_mgr_is_connected()` | Wi-Fi接続状態を取得                   |
| `wifi_mgr_get_ip_str()`   | IPアドレスを取得                      |
| `ota_mode_active`         | OTAモード中かどうか                   |

---

## 🛠 トラブルシューティング

### ❌ ビルドエラー

```bash
# キャッシュクリア
pio run --target clean

# 再ビルド
pio run
```

### ❌ 書き込みエラー

1. USBケーブルがデータ転送対応か確認（充電専用ケーブルはNG）
2. ESP32のUSBポートを確認（デバイスマネージャーで確認）
3. ESP32をリセットボタンで再起動してから再試行

### ❌ シリアルモニタが開かない

```bash
# COMポートを確認
pio device list

# シリアルモニタを開く
pio device monitor --baud 115200
```

---

## 📚 関連ドキュメント

- [ルートREADME.md](../README.md) - システム全体の説明
- [WebAppSide/README.md](../WebAppSide/README.md) - WebAppの使い方
- [SpecifcationDoc.md](../SpecifcationDoc.md) - システム仕様書

---

## ⚡ 次のステップ

1. **サンプルを動かす** - まずはそのまま書き込んで動作確認
2. **メッセージを変更** - "Hello World"を自分のメッセージに変更
3. **センサーを追加** - 温度センサーなどを追加してデータ送信
4. **BLE OTAで更新** - WebAppからファームウェアを更新（USBケーブル不要！）

---

**最終更新**: 2026-03-06  
**対応WebApp**: https://ble-compiler.netlify.app/

### 1. AWS IoT Core 証明書の設定

main.cpp 内の以下の証明書を自分の AWS IoT Core 証明書に置き換えてください：

- `AWS_ROOT_CA` - Amazon Root CA
- `AWS_DEVICE_CERT` - デバイス証明書
- `AWS_PRIVATE_KEY` - デバイス秘密鍵

エンドポイントとトピックも必要に応じて変更：

```cpp
#define AWS_IOT_ENDPOINT "your-endpoint.iot.ap-northeast-1.amazonaws.com"
#define AWS_IOT_TOPIC "your/iot/topic"
```

### 2. ビルド・実行手順

#### 方法1: PlatformIO CLI（ターミナル）

```bash
# プロジェクトディレクトリに移動
cd c:\Users\naka6\Projects\iot-ai-agent\IotDevice

# ビルド
platformio run

# デバイスに書き込み
platformio run --target upload

# シリアルモニタを開く
platformio device monitor
```

#### 方法2: VSCode + PlatformIO GUI（推奨）

1. VSCode でプロジェクトフォルダを開く
2. 左下の PlatformIO アイコンをクリック
3. **Build** でコンパイル
4. **Upload** でデバイスに書き込み
5. **Open Serial Monitor** でシリアル出力を確認

### 3. COM ポートの確認

**Windows:**

```bash
# デバイスマネージャーで "COM3" などを確認
# または
platformio device list
```

**platformio.ini の修正（必要に応じて）**

```ini
upload_port = COM3  ; 自分のポートに変更
```

## 動作確認

シリアルモニタで以下のようなログが表示されれば成功：

```
[System] ESP32-S3 Starting...
[MPU6050] Initializing...
[MPU6050] OK
[AWS] Client ID: esp32-xxxxxxxxxxxx
[AWS] Setting up secure client certificates...
[AWS] Configuring MQTT client...
[AWS] MQTT client initialized
[BLE] Initialized
[Setup] Initialization complete
[AWS] Connecting to AWS IoT Core...
[AWS] Connected!
[AWS] Publishing: {"timestamp":1234567890,"client_id":"esp32-xxx","accel_x":0.00,...,"activity":"None"}
```

**MPU6050 センサー動作確認:**

- デバイスを動かすと加速度データが変化します
- 静止: "activity": "None"
- 歩く: "activity": "Walk"（加速度 > 20.0）
- 走る: "activity": "Run"（加速度 > 30.0）

**AWS IoT Core での確認:**
AWS IoT Core のコンソールで MQTT Test Client を使用し、設定したトピックをサブスクライブすると、5秒ごとにセンサーデータが受信できます。

## トラブルシューティング

### Port が見つからない

```bash
# デバイスリスト表示
platformio device list

# または Windows のデバイスマネージャーで COM ポートを確認
```

### コンパイルエラー

```bash
# キャッシュクリア
platformio run --target clean

# 再度ビルド
platformio run
```

### MPU6050 が初期化できない

- I2C 配線を確認（SDA: GPIO 12, SCL: GPIO 11）
- MPU6050 の電源（3.3V と GND）を確認
- I2C アドレス（0x68 または 0x69）を確認

### AWS IoT Core に接続できない

- Wi-Fi 接続を確認（BLE プロビジョニングが必要）
- 証明書（Root CA、Device Cert、Private Key）が正しく設定されているか確認
- AWS IoT エンドポイントが正しいか確認
- Thing のポリシーで接続・パブリッシュ権限が付与されているか確認

### シリアルモニタが開かない

- USB ドライバをインストール（[CH340 ドライバ](https://sparks.gogo.co.nz/ch340.html)など）
- ボーレート: 115200

## ファイル構成

```
IotDevice/
├── src/
│   └── main.cpp             # メインプログラム
├── platformio.ini           # PlatformIO 設定
├── partitions_ota_2m.csv    # OTA 対応パーティションテーブル
├── partitions.csv           # 通常パーティションテーブル
└── README.md               # このファイル
```

## 依存ライブラリ

platformio.ini で自動的にインストールされます：

- **Adafruit MPU6050** - 加速度センサー制御
- **Adafruit Unified Sensor** - センサー共通ライブラリ
- **PubSubClient** - MQTT クライアント
- **ArduinoJson** - JSON シリアライズ/デシリアライズ

## BLE サービス

### Debug Service

- Debug Service: `7f3f0001-6b7c-4f2e-9b8a-1a2b3c4d5e6f`
- DebugLogTx (Notify): `7f3f0002-6b7c-4f2e-9b8a-1a2b3c4d5e6f`
- DebugCmdRx (Write): `7f3f0003-6b7c-4f2e-9b8a-1a2b3c4d5e6f`
- DebugStat (Read/Notify): `7f3f0005-6b7c-4f2e-9b8a-1a2b3c4d5e6f`

### Provisioning Service

- Provisioning Service: `8f4f0001-7c8d-5f3e-ac9b-2b3c4d5e6f70`
- WiFi Config (Write): `8f4f0002-7c8d-5f3e-ac9b-2b3c4d5e6f70`

### OTA Service

- OTA Service: `9f5f0001-8d9e-6f4e-bd0c-3c4d5e6f7180`
- OTA Control (Write/Read): `9f5f0002-8d9e-6f4e-bd0c-3c4d5e6f7180`
- OTA Data (Write): `9f5f0003-8d9e-6f4e-bd0c-3c4d5e6f7180`
- OTA Status (Read/Notify): `9f5f0004-8d9e-6f4e-bd0c-3c4d5e6f7180`

BLE 経由でファームウェアの OTA アップデートが可能です。詳細は仕様書を参照してください。

## オプション設定

### ビルドオプション（platformio.ini）

**デバッグレベルの変更**

```ini
build_flags =
  -DCORE_DEBUG_LEVEL=5    ; 0=None, 5=Verbose
  -DLOG_SERIAL_ENABLED=1  ; シリアルログ有効化
```

**センサーデータ送信間隔の変更（main.cpp）**

```cpp
#define AWS_PUBLISH_INTERVAL_MS 5000        // AWS への送信間隔（ミリ秒）
#define SENSOR_SAMPLE_INTERVAL_MS 500       // センサーサンプリング間隔（ミリ秒）
#define SENSOR_SEND_INTERVAL_MS 10000       // BLE デバッグログへの送信間隔（ミリ秒）
```

**活動検知の閾値変更（main.cpp）**

```cpp
// activity_status_from_magnitude() 関数内
if (accel_magnitude > 30.0f) return "Run";     // 走り
if (accel_magnitude > 20.0f) return "Walk";    // 歩き
return "None";                                 // 静止
```

## 仕様書参照

詳細な仕様については、以下のドキュメントを参照してください：

- [IOT_DATA_SPECIFICATION.md](../IOT_DATA_SPECIFICATION.md) - IoT データ仕様
- プロジェクトルートの仕様書

## 関連プロジェクト

- AI Agent: [ai-agent/](../ai-agent/) - LangGraph による AI エージェント
- Watch App: [watch-app/](../watch-app/) - Apple Watch コントロールアプリ
- VSCode Extension: [vscode-extension/](../vscode-extension/) - VSCode 拡張機能
