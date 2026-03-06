#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <WiFi.h>

// ===== マニュファクチャラーID（TimeFaker識別用）=====
#define MANUFACTURER_ID 0xAA55

// ===== LED =====
constexpr uint8_t LED_PIN = 2;

// ===== NTP時刻同期（オプション）=====
#include <time.h>
const char *ntpServer = "pool.ntp.org";
const long gmtOffset_sec = 9 * 3600; // Japan GMT+9
const int daylightOffset_sec = 0;

// ===== グローバル設定 =====
volatile int8_t currentOffset = 0; // 現在のオフセット（分単位）
volatile bool offsetChanged = false;

void setupWiFi()
{
  Serial.println("Connecting to WiFi...");

  // ⚠️ WiFi認証情報を設定してください
  const char *ssid = "LOCALHOUSE_SPACE";
  const char *password = "dadadada";

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20)
  {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED)
  {
    Serial.println("\nWiFi connected!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
  }
  else
  {
    Serial.println("\nWiFi failed - using local time");
  }
}

void setupNTP()
{
  Serial.println("Setting up NTP time synchronization...");

  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);

  time_t now = time(nullptr);
  int attempts = 0;
  while (now < 24 * 3600 && attempts < 30)
  {
    delay(500);
    Serial.print(".");
    now = time(nullptr);
    attempts++;
  }

  Serial.println();
  if (now > 24 * 3600)
  {
    Serial.print("NTP sync success: ");
    Serial.println(ctime(&now));
  }
  else
  {
    Serial.println("NTP sync timeout - using default time");
  }
}

void setupBLE()
{
  Serial.println("Initializing BLE...");

  BLEDevice::init("TimeFaker_TX");
  delay(100);

  BLEAdvertising *pAdv = BLEDevice::getAdvertising();

  // アドバタイズ設定（スキャン可能・非接続）
  pAdv->setAdvertisementType(0x02); // ADV_SCAN_IND
  pAdv->setMinInterval(0x20);       // 100ms間隔
  pAdv->setMaxInterval(0x20);

  BLEDevice::startAdvertising();

  Serial.println("BLE initialized - ready to broadcast");
}

void broadcastTime(int hh, int mm, int ss, int8_t offset_min)
{
  // Manufacturer Dataペイロード構成：
  // [0-1]: Manufacturer ID (0xAA55)
  // [2]:   Version (0x01)
  // [3]:   Hour (HH)
  // [4]:   Minute (MM)
  // [5]:   Second (SS)
  // [6]:   Offset in minutes (signed)
  // [7]:   Reserved

  uint8_t mfgData[8] = {
      (uint8_t)(MANUFACTURER_ID & 0xFF), // Manufacturer ID (little-endian)
      (uint8_t)((MANUFACTURER_ID >> 8) & 0xFF),
      0x01,                // Version
      (uint8_t)hh,         // Hour
      (uint8_t)mm,         // Minute
      (uint8_t)ss,         // Second
      (uint8_t)offset_min, // Offset (signed)
      0x01                 // Reserved (non-zero)
  };

  // BLEアドバタイズメントデータを作成
  BLEAdvertisementData advData;

  // Manufacturer Data をセット
  String payload((char *)mfgData, sizeof(mfgData));
  advData.setManufacturerData(payload);

  // ローカル名も追加（デバッグ用）
  advData.setName("TimeFaker_TX");

  // アドバタイズを更新
  BLEAdvertising *pAdv = BLEDevice::getAdvertising();
  BLEAdvertisementData scanData;
  scanData.setName("TimeFaker_TX");
  pAdv->stop();
  pAdv->setAdvertisementData(advData);
  pAdv->setScanResponseData(scanData);
  pAdv->start();

  // シリアル出力（デバッグ）
  Serial.print("[BROADCAST] ");
  Serial.print(hh < 10 ? "0" : "");
  Serial.print(hh);
  Serial.print(":");
  Serial.print(mm < 10 ? "0" : "");
  Serial.print(mm);
  Serial.print(":");
  Serial.print(ss < 10 ? "0" : "");
  Serial.print(ss);
  Serial.print(" offset=");
  if (offset_min >= 0)
    Serial.print("+");
  Serial.print(offset_min);
  Serial.print("min  [Payload: ");
  for (int i = 0; i < 8; i++)
  {
    if (mfgData[i] < 16)
      Serial.print("0");
    Serial.print(mfgData[i], HEX);
    Serial.print(" ");
  }
  Serial.println("]");
}

void broadcastTimeNoId(int hh, int mm, int ss, int8_t offset_min)
{
  // Manufacturer Dataペイロード構成（IDなし・受信側パターン2）:
  // [0]:   Version (0x01)
  // [1]:   Hour (HH)
  // [2]:   Minute (MM)
  // [3]:   Second (SS)
  // [4]:   Offset in minutes (signed)
  // [5]:   Reserved
  uint8_t mfgData[6] = {
      0x01,                // Version
      (uint8_t)hh,         // Hour
      (uint8_t)mm,         // Minute
      (uint8_t)ss,         // Second
      (uint8_t)offset_min, // Offset (signed)
      0x01                 // Reserved (non-zero)
  };

  BLEAdvertisementData advData;
  String payload((char *)mfgData, sizeof(mfgData));
  advData.setManufacturerData(payload);
  advData.setName("TimeFaker_TX");

  BLEAdvertising *pAdv = BLEDevice::getAdvertising();
  BLEAdvertisementData scanData;
  scanData.setName("TimeFaker_TX");
  pAdv->stop();
  delay(5);
  pAdv->setAdvertisementData(advData);
  pAdv->setScanResponseData(scanData);
  pAdv->start();
}

void updateBroadcast()
{
  // 現在時刻を取得
  time_t now = time(nullptr);
  struct tm *timeinfo = localtime(&now);

  int hh = timeinfo->tm_hour;
  int mm = timeinfo->tm_min;
  int ss = timeinfo->tm_sec;

  // ブロードキャスト送信（IDなしパターンのみ）
  broadcastTimeNoId(hh, mm, ss, currentOffset);
}

void sendBroadcastBurst(uint16_t repeatCount = 3, uint16_t intervalMs = 100)
{
  // 複数回繰り返し送信（受信側のスキャン遭遇率向上）
  for (uint16_t i = 0; i < repeatCount; i++)
  {
    updateBroadcast();
    if (i < repeatCount - 1)
      delay(intervalMs);
  }
}

void setup()
{
  Serial.begin(115200);
  delay(1000);

  // LED初期化
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);

  Serial.println("======================");
  Serial.println("  TimeFaker TX (ESP32)");
  Serial.println("======================");
  Serial.print("Free heap: ");
  Serial.println(ESP.getFreeHeap());

  // WiFi接続（NTP同期用）
  setupWiFi();

  // NTP時刻同期
  setupNTP();

  // BLE初期化（10秒遅延）
  delay(10000);
  setupBLE();

  Serial.println("System ready!");
  Serial.println();
  Serial.println("=== 使用方法 ===");
  Serial.println("シリアルモニタからオフセット値（-120 ~ +120）を入力してください");
  Serial.println("例: 5 (5分進める), -10 (10分遅らせる), 0 (オフセットなし)");
  Serial.println();
}

void loop()
{
  // シリアル入力待機（オフセット入力時のみブロードキャスト）

  // ===== シリアル入力処理 =====
  if (Serial.available())
  {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (input.length() > 0)
    {
      // 入力値を整数に変換
      int offset = input.toInt();

      // オフセット範囲チェック
      if (offset < -120 || offset > 120)
      {
        Serial.println("エラー: オフセットは -120 ~ +120 の範囲で入力してください");
      }
      else
      {
        // オフセット設定とブロードキャスト送信
        currentOffset = offset;

        // LED点灯（送信確認用）
        digitalWrite(LED_PIN, HIGH);

        // 現在時刻取得とブロードキャスト（受信側のスキャンに合わせて短時間バースト送信）
        sendBroadcastBurst();

        Serial.print("オフセット設定: ");
        if (offset >= 0)
          Serial.print("+");
        Serial.print(offset);
        Serial.println(" 分 → BLE送信完了");

        // LED消灯
        delay(100);
        digitalWrite(LED_PIN, LOW);
      }
    }
  }

  delay(10);
}
