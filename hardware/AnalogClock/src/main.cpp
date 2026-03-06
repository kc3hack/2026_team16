#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

// ===== ESP32-S3 Super Mini オンボ�EドLED =====
constexpr uint8_t LED_PIN = 47;

// ===== 1つ目のスチE��ピングモータ (GPIO7-4) =====
constexpr uint8_t MOTOR1_PIN1 = 7;
constexpr uint8_t MOTOR1_PIN2 = 6;
constexpr uint8_t MOTOR1_PIN3 = 5;
constexpr uint8_t MOTOR1_PIN4 = 4;

// ===== 2つ目のスチE��ピングモータ (GPIO8-11) =====
constexpr uint8_t MOTOR2_PIN1 = 8;
constexpr uint8_t MOTOR2_PIN2 = 9;
constexpr uint8_t MOTOR2_PIN3 = 10;
constexpr uint8_t MOTOR2_PIN4 = 11;

// スチE��ピングモータのスチE��プパターン�E�E相励磁、低消費電力！E
const uint8_t STEP_PATTERN[4][4] = {
    {1, 0, 0, 0},
    {0, 1, 0, 0},
    {0, 0, 1, 0},
    {0, 0, 0, 1}};

// モータ状慁E
int motor1Position = 0;
int motor2Position = 0;
bool motorSequenceRunning = false;
int offsetMinutes = 0;
int targetMinutes = 0;        // 目標位置�E��E単位！E
int currentTargetMinutes = 0; // 現在の目標位置�E��E期位置からの相対値�E�E

// シリアル受信でのモータ2直接制御用
int serialMotor2Steps = 0;
int serialMotor2Direction = 0; // 1: 正転, -1: 送E��

// シーケンス状慁E
enum MotorSequence
{
  SEQ_IDLE,
  SEQ_MOTOR2_FORWARD,
  SEQ_MOTOR1_ROTATE,
  SEQ_MOTOR2_BACKWARD,
  SEQ_MOTOR2_SERIAL // シリアル受信でのモータ2制御
};
MotorSequence currentSequence = SEQ_IDLE;
int sequenceStep = 0;
uint32_t lastStepTime = 0;
constexpr uint16_t STEP_DELAY_MS = 2; // スチE��プ間隔！Es�E�E

// ===== internal clock base (0:00 start) =====
volatile uint32_t base_sec = 0;
volatile uint32_t base_ms = 0;
volatile bool time_valid = false;

// ===== BLE Broadcast Scanning =====
static const char *BLE_NAME = "TimeFaker_RX";
BLEScan *pBLEScan = nullptr;
volatile bool ackRequest = false;
volatile bool bleTaskRunning = false;

// BLE非同期スキャンタスク用
TaskHandle_t bleTaskHandle = nullptr;

// ☁E��回受け取った時刻�E�秒単位）とオフセチE��を記録して重褁E��新を防ぁE
static uint32_t lastReceivedTimeSeconds = 0xFFFFFFFF; // 初期値�E�無効
static int8_t lastReceivedOffset = 0x7F;              // 初期値�E�無効

volatile bool newDataReceived = false;

// ブロードキャストパケチE��処琁E��Eanufacturer Data形式！E
// 2パターン対忁E
// パターン1: [0-1]:0x55 0xAA [2]:0x01 [3-5]:HH MM SS [6]:offset [7]:reserved (8bytes total)
// パターン2: [0]:0x01 [1-3]:HH MM SS [4]:offset [5]:reserved (6bytes total)
bool applyBroadcastPacket(const uint8_t *data, size_t len)
{
  // Raw data めE6進数で表示
  Serial.print("[BLE RX] Raw data (");
  Serial.print(len);
  Serial.print(" bytes): ");
  for (size_t i = 0; i < len; i++)
  {
    if (data[i] < 0x10)
      Serial.print("0");
    Serial.print(data[i], HEX);
    Serial.print(" ");
  }
  Serial.println();
  Serial.flush();

  int hh, mm, ss;
  int8_t offset;

  // パターン判宁E
  if (len >= 8 && data[0] == 0x55 && data[1] == 0xAA)
  {
    // パターン1�E�Manufacturer ID込み

    if (data[2] != 0x01)
    {
      return false;
    }

    hh = data[3];
    mm = data[4];
    ss = data[5];
    offset = (int8_t)data[6];
  }
  else if (len >= 6 && data[0] == 0x01)
  {
    // パターン2�E�Version ぁE[0]

    hh = data[1];
    mm = data[2];
    ss = data[3];
    offset = (int8_t)data[4];
  }
  else
  {
    return false;
  }

  // ペイロード表示�E�デバッグ�E�E

  Serial.print("[DEBUG] Parsed: ");
  if (hh < 10)
    Serial.print("0");
  Serial.print(hh);
  Serial.print(":");
  if (mm < 10)
    Serial.print("0");
  Serial.print(mm);
  Serial.print(":");
  if (ss < 10)
    Serial.print("0");
  Serial.print(ss);
  Serial.print(" offset=");
  if (offset >= 0)
    Serial.print("+");
  Serial.println(offset);
  Serial.flush();

  // 検証: 時刻が有効篁E��ぁE
  if (hh < 0 || hh > 23 || mm < 0 || mm > 59 || ss < 0 || ss > 59)
  {
    return false;
  }

  // ☁E��要E 同じ時刻とオフセチE��を受け取った場合�EスキチE�E�E�重褁E��新を防止�E�E
  uint32_t receivedTimeSeconds = hh * 3600 + mm * 60 + ss;
  if (receivedTimeSeconds == lastReceivedTimeSeconds && offset == lastReceivedOffset)
  {
    Serial.println("[BLE RX] Duplicate packet, skipped");
    Serial.flush();
    return false;
  }
  lastReceivedTimeSeconds = receivedTimeSeconds;
  lastReceivedOffset = offset;

  // 時刻適用�E�オフセチE��込み�E�E
  int32_t send_sec = hh * 3600 + mm * 60 + ss;
  int32_t adj = send_sec + (int32_t)offset * 60;
  adj %= 86400;
  if (adj < 0)
    adj += 86400;

  base_sec = (uint32_t)adj;
  base_ms = (uint32_t)millis();
  time_valid = true;

  // オフセチE���E��E�E�を保存してモータシーケンス開姁E
  targetMinutes = offset;
  offsetMinutes = targetMinutes - currentTargetMinutes; // 差刁E��計箁E

  Serial.print("[MOTOR] Target=");
  Serial.print(targetMinutes);
  Serial.print(" Current=");
  Serial.print(currentTargetMinutes);
  Serial.print(" Offset=");
  Serial.println(offsetMinutes);
  Serial.flush();

  newDataReceived = true;

  return true;
}

// BLE非同期スキャンタスク
void bleScanTask(void *parameter)
{
  uint32_t scanCount = 0;
  uint32_t deviceCount = 0;
  uint32_t mfgCount = 0;
  uint32_t processedCount = 0;

  Serial.println("[BLE Task] Started");
  Serial.flush();

  while (bleTaskRunning)
  {
    if (!pBLEScan)
    {
      vTaskDelay(pdMS_TO_TICKS(500));
      continue;
    }

    // ☁E��ータ動作中はBLEスキャンをスキチE�E�E�割り込み防止�E�E
    if (motorSequenceRunning)
    {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }

    // スキャン実衁E
    BLEScanResults foundDevices = pBLEScan->start(2, false); // 2秒スキャン

    if (foundDevices.getCount() == 0)
    {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }

    scanCount++;
    int count = foundDevices.getCount();
    deviceCount += count;

    // スキャン結果を�E琁E
    bool found = false;
    for (int i = 0; i < count; i++)
    {
      BLEAdvertisedDevice device = foundDevices.getDevice(i);

      // ☁E��要E チE��イス名で「TimeFaker_TX」をフィルタリング
      String devName = device.getName().c_str();

      if (devName != "TimeFaker_TX")
      {
        continue; // TimeFaker_TX以外�E無要E
      }

      Serial.print("[BLE] Found TimeFaker_TX, RSSI: ");
      Serial.println(device.getRSSI());
      Serial.flush();

      if (device.haveManufacturerData())
      {
        mfgCount++;

        // ☁E��要E c_str() を使わず、length() を指定して取得！Ex00での刁E��詰めE��止�E�E
        std::string mfgString = device.getManufacturerData();
        size_t dataLen = mfgString.length();
        const uint8_t *raw = reinterpret_cast<const uint8_t *>(mfgString.data());

        // Raw dataめE6進数で表示�E��Eて�E�E
        Serial.print("[BLE ScanTask] Raw MFG data (");
        Serial.print(dataLen);
        Serial.print(" bytes): ");
        for (size_t i = 0; i < dataLen; i++)
        {
          if (raw[i] < 0x10)
            Serial.print("0");
          Serial.print(raw[i], HEX);
          Serial.print(" ");
        }
        Serial.println();

        // Manufacturer ID を含む可能性があめE [0-1]=0x55 0xAA
        // また�E Version ぁE[0]=0x01 かもしれなぁE
        // 両パターンチェチE��
        bool isTimeFaker = false;

        if (dataLen >= 8 && raw[0] == 0x55 && raw[1] == 0xAA)
        {
          isTimeFaker = true;
          Serial.println("[BLE ScanTask] Pattern 1 matched (0x55 0xAA)");
        }
        else if (dataLen >= 6 && raw[0] == 0x01)
        {
          isTimeFaker = true;
          Serial.println("[BLE ScanTask] Pattern 2 matched (0x01)");
        }
        else
        {
          Serial.println("[BLE ScanTask] No pattern matched");
        }

        if (isTimeFaker)
        {
          processedCount++;
          if (applyBroadcastPacket(raw, dataLen))
          {
            ackRequest = true;
            found = true;
            break;
          }
          else
          {
            Serial.println("[BLE ScanTask] applyBroadcastPacket returned false");
          }
        }
      }
    }

    if (scanCount % 10 == 0)
    {
      Serial.print("[BLE Stats] Scans:");
      Serial.print(scanCount);
      Serial.print(" Devices:");
      Serial.print(deviceCount);
      Serial.print(" MFG:");
      Serial.print(mfgCount);
      Serial.print(" Processed:");
      Serial.println(processedCount);
    }

    pBLEScan->clearResults(); // メモリ解放

    vTaskDelay(pdMS_TO_TICKS(500)); // 500ms征E��E
  }

  vTaskDelete(nullptr);
}

bool bleStarted = false;

void setMotor1Step(int step)
{
  step = step % 4;
  if (step < 0)
    step += 4;

  digitalWrite(MOTOR1_PIN1, STEP_PATTERN[step][0]);
  digitalWrite(MOTOR1_PIN2, STEP_PATTERN[step][1]);
  digitalWrite(MOTOR1_PIN3, STEP_PATTERN[step][2]);
  digitalWrite(MOTOR1_PIN4, STEP_PATTERN[step][3]);
}

void setMotor2Step(int step)
{
  step = step % 4;
  if (step < 0)
    step += 4;

  digitalWrite(MOTOR2_PIN1, STEP_PATTERN[step][0]);
  digitalWrite(MOTOR2_PIN2, STEP_PATTERN[step][1]);
  digitalWrite(MOTOR2_PIN3, STEP_PATTERN[step][2]);
  digitalWrite(MOTOR2_PIN4, STEP_PATTERN[step][3]);
}

void stopMotor1()
{
  digitalWrite(MOTOR1_PIN1, LOW);
  digitalWrite(MOTOR1_PIN2, LOW);
  digitalWrite(MOTOR1_PIN3, LOW);
  digitalWrite(MOTOR1_PIN4, LOW);
}

void stopMotor2()
{
  digitalWrite(MOTOR2_PIN1, LOW);
  digitalWrite(MOTOR2_PIN2, LOW);
  digitalWrite(MOTOR2_PIN3, LOW);
  digitalWrite(MOTOR2_PIN4, LOW);
}

void startMotorSequence()
{
  if (motorSequenceRunning)
  {
    Serial.println("[MOTOR] Already running, skipped");
    Serial.flush();
    return;
  }

  Serial.println("[MOTOR] Sequence started");
  Serial.flush();
  motorSequenceRunning = true;
  currentSequence = SEQ_MOTOR2_FORWARD;
  sequenceStep = 0;
  lastStepTime = millis();
}

void startMotor2Serial(int degrees)
{
  if (motorSequenceRunning)
  {
    Serial.println("[WARN] Motor busy, ignoring serial command");
    return;
  }

  // 度数をスチE��プ数に変換�E�E048スチE��チE360度�E�E
  int steps = abs(degrees) * 2048 / 360;

  if (steps == 0)
  {
    Serial.println("[INFO] 0 degrees, no rotation");
    return;
  }

  serialMotor2Steps = steps;
  serialMotor2Direction = (degrees > 0) ? 1 : -1;

  motorSequenceRunning = true;
  currentSequence = SEQ_MOTOR2_SERIAL;
  sequenceStep = 0;
  lastStepTime = millis();

  Serial.print("[INFO] Motor2 rotating ");
  Serial.print(degrees);
  Serial.print(" degrees (");
  Serial.print(steps);
  Serial.println(" steps)");
}

void updateMotorSequence()
{
  if (!motorSequenceRunning)
    return;

  uint32_t now = millis();
  if ((now - lastStepTime) < STEP_DELAY_MS)
    return;

  lastStepTime = now;

  switch (currentSequence)
  {
  case SEQ_MOTOR2_FORWARD:
    // 20度回転�E�E048スチE��チE360度 ↁE20度 = 114スチE��プ！E
    if (sequenceStep < 114)
    {
      motor2Position++;
      setMotor2Step(motor2Position);
      sequenceStep++;
    }
    else
    {
      // 次のシーケンスへ
      stopMotor2();
      currentSequence = SEQ_MOTOR1_ROTATE;
      sequenceStep = 0;
    }
    break;

  case SEQ_MOTOR1_ROTATE:
  {
    // 60刁E= 550度、E刁E= 9.167度
    // 2048スチE��チE360度 ↁE1度 = 5.69スチE��チE
    // 1刁E9.167度) = 52.16スチE��チE≁E52スチE��チE
    int totalSteps = abs(offsetMinutes) * 52;

    if (totalSteps == 0)
    {
      // オフセチE��0の場合�EスキチE�E
      stopMotor1();
      currentSequence = SEQ_MOTOR2_BACKWARD;
      sequenceStep = 0;
    }
    else if (sequenceStep < totalSteps)
    {
      if (offsetMinutes > 0)
      {
        motor1Position--;
      }
      else if (offsetMinutes < 0)
      {
        motor1Position++;
      }
      setMotor1Step(motor1Position);
      sequenceStep++;
    }
    else
    {
      // 次のシーケンスへ
      stopMotor1();
      currentSequence = SEQ_MOTOR2_BACKWARD;
      sequenceStep = 0;
    }
  }
  break;

  case SEQ_MOTOR2_BACKWARD:
    // -20度回転�E�E14スチE��プ戻す！E
    if (sequenceStep < 114)
    {
      motor2Position--;
      setMotor2Step(motor2Position);
      sequenceStep++;
    }
    else
    {
      // シーケンス完亁E
      stopMotor1();
      stopMotor2();
      motorSequenceRunning = false;
      currentSequence = SEQ_IDLE;
      sequenceStep = 0;
      currentTargetMinutes = targetMinutes; // 現在の目標位置を更新
      Serial.print("[MOTOR] Sequence completed. Current position: ");
      Serial.println(currentTargetMinutes);
      Serial.flush();
    }
    break;

  case SEQ_MOTOR2_SERIAL:
    // シリアル受信によるモータ2の直接制御
    if (sequenceStep < serialMotor2Steps)
    {
      if (serialMotor2Direction > 0)
      {
        motor2Position++;
      }
      else
      {
        motor2Position--;
      }
      setMotor2Step(motor2Position);
      sequenceStep++;
    }
    else
    {
      // 回転完亁E
      stopMotor2();
      motorSequenceRunning = false;
      currentSequence = SEQ_IDLE;
      sequenceStep = 0;
    }
    break;

  case SEQ_IDLE:
    break;
  }
}

void startBLE()
{
  BLEDevice::init(BLE_NAME);
  delay(100);

  pBLEScan = BLEDevice::getScan();
  pBLEScan->setActiveScan(false); // パッシブスキャン
  pBLEScan->setInterval(97);      // 紁E00ms
  pBLEScan->setWindow(97);        // 紁E00ms�E�Entervalと同じで連続スキャン�E�E
  // pBLEScan->setDuplicateFilter(true); // Not available in this BLE library version

  // BLEスキャンを非同期タスクで実衁E
  bleTaskRunning = true;
  xTaskCreatePinnedToCore(
      bleScanTask,
      "BLETask",
      3072, // スタチE��量を例外�E琁E��に拡張
      nullptr,
      1, // 優先度�E�低優先度�E�E
      &bleTaskHandle,
      0 // Core 0
  );
}

uint32_t nowSeconds()
{
  if (!time_valid)
    return (millis() / 1000) % 86400;
  uint32_t elapsed = (millis() - base_ms) / 1000;
  return (base_sec + elapsed) % 86400;
}

void setup()
{
  // LED初期化：ハードウェア動作確認用
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH); // 起動時点灯

  // シリアル初期匁E
  Serial.begin(115200);

  // USB CDCモード対応：デバイスがシリアルポ�Eトとして認識されるまで征E��E
  uint32_t startTime = millis();
  while (!Serial && (millis() - startTime) < 10000)
  {
    digitalWrite(LED_PIN, !digitalRead(LED_PIN)); // LED点滁E��征E��中を表示
    delay(200);
  }

  digitalWrite(LED_PIN, HIGH); // LED点灯に戻ぁE
  delay(500);
  Serial.flush();

  // 起動確誁E
  Serial.println("\n\n");
  Serial.println("========================================");
  Serial.println("AnalogClock Started - USB CDC Ready");
  Serial.println("========================================");
  Serial.flush();

  // モータ1初期匁E
  pinMode(MOTOR1_PIN1, OUTPUT);
  pinMode(MOTOR1_PIN2, OUTPUT);
  pinMode(MOTOR1_PIN3, OUTPUT);
  pinMode(MOTOR1_PIN4, OUTPUT);
  stopMotor1();

  // モータ2初期匁E
  pinMode(MOTOR2_PIN1, OUTPUT);
  pinMode(MOTOR2_PIN2, OUTPUT);
  pinMode(MOTOR2_PIN3, OUTPUT);
  pinMode(MOTOR2_PIN4, OUTPUT);
  stopMotor2();

  // 起勁E0:00
  base_sec = 0;
  base_ms = millis();
  time_valid = true;

  // BLE初期化（起動時に実行！E
  delay(500); // 安定征E��
  Serial.println("[SETUP] Initializing BLE...");
  Serial.flush();
  startBLE();
  bleStarted = true;
  Serial.println("[SETUP] BLE started successfully");
  Serial.flush();
}

void loop()
{
  static uint32_t lastHeartbeat = 0;
  uint32_t now = millis();

  // ハ�Eトビート�E力！E秒ごと�E�E
  if (now - lastHeartbeat > 5000)
  {
    lastHeartbeat = now;
    Serial.print("[LOOP] Heartbeat: ");
    Serial.print(now / 1000);
    Serial.print("s, Motor running=");
    Serial.println(motorSequenceRunning);
    Serial.flush();
  }

  // シリアル受信処琁E��モータ2直接制御�E�E
  if (Serial.available() > 0)
  {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (input.length() > 0)
    {
      int degrees = input.toInt();
      if (degrees != 0 || input == "0")
      {
        // 有効な数値を受信
        startMotor2Serial(degrees);
      }
      else
      {
        Serial.println("[ERROR] Invalid input. Enter degrees (e.g., 45, -30)");
      }
    }
  }

  // BLEチE�Eタ受信時�Eモータシーケンス開姁E
  if (newDataReceived)
  {
    newDataReceived = false;
    startMotorSequence();
  }

  // モータシーケンス更新
  updateMotorSequence();

  delay(1);
}
