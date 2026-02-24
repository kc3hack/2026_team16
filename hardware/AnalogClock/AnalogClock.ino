#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

// ===== ESP32-S3 Super Mini オンボードLED =====
constexpr uint8_t LED_PIN = 47;

// ===== 1つ目のステッピングモータ (GPIO7-4) =====
constexpr uint8_t MOTOR1_PIN1 = 7;
constexpr uint8_t MOTOR1_PIN2 = 6;
constexpr uint8_t MOTOR1_PIN3 = 5;
constexpr uint8_t MOTOR1_PIN4 = 4;

// ===== 2つ目のステッピングモータ (GPIO8-11) =====
constexpr uint8_t MOTOR2_PIN1 = 8;
constexpr uint8_t MOTOR2_PIN2 = 9;
constexpr uint8_t MOTOR2_PIN3 = 10;
constexpr uint8_t MOTOR2_PIN4 = 11;

// ステッピングモータのステップパターン（1相励磁、低消費電力）
const uint8_t STEP_PATTERN[4][4] = {
  {1, 0, 0, 0},
  {0, 1, 0, 0},
  {0, 0, 1, 0},
  {0, 0, 0, 1}
};

// モータ状態
int motor1Position = 0;
int motor2Position = 0;
bool motorSequenceRunning = false;
int offsetMinutes = 0;
int targetMinutes = 0;  // 目標位置（分単位）
int currentTargetMinutes = 0;  // 現在の目標位置（初期位置からの相対値）

// シリアル受信でのモータ2直接制御用
int serialMotor2Steps = 0;
int serialMotor2Direction = 0;  // 1: 正転, -1: 逆転

// シーケンス状態
enum MotorSequence {
  SEQ_IDLE,
  SEQ_MOTOR2_FORWARD,
  SEQ_MOTOR1_ROTATE,
  SEQ_MOTOR2_BACKWARD,
  SEQ_MOTOR2_SERIAL  // シリアル受信でのモータ2制御
};
MotorSequence currentSequence = SEQ_IDLE;
int sequenceStep = 0;
uint32_t lastStepTime = 0;
constexpr uint16_t STEP_DELAY_MS = 2; // ステップ間隔（ms）

// ===== internal clock base (0:00 start) =====
volatile uint32_t base_sec = 0;
volatile uint32_t base_ms  = 0;
volatile bool     time_valid = false;

// ===== BLE Broadcast Scanning =====
static const char* BLE_NAME = "TimeFaker_RX";
BLEScan* pBLEScan = nullptr;
volatile bool ackRequest = false;
volatile bool bleTaskRunning = false;

// BLE非同期スキャンタスク用
TaskHandle_t bleTaskHandle = nullptr;

// ★前回受け取った時刻（秒単位）を記録して重複更新を防ぐ
static uint32_t lastReceivedTimeSeconds = 0xFFFFFFFF;  // 初期値：無効

volatile bool newDataReceived = false;

// ブロードキャストパケット処理（Manufacturer Data形式）
// 2パターン対応:
// パターン1: [0-1]:0x55 0xAA [2]:0x01 [3-5]:HH MM SS [6]:offset [7]:reserved (8bytes total)
// パターン2: [0]:0x01 [1-3]:HH MM SS [4]:offset [5]:reserved (6bytes total)
bool applyBroadcastPacket(const uint8_t* data, size_t len) {
  int hh, mm, ss;
  int8_t offset;
  
  // パターン判定
  if (len >= 8 && data[0] == 0x55 && data[1] == 0xAA) {
    // パターン1：Manufacturer ID込み
    
    if (data[2] != 0x01) {
      return false;
    }
    
    hh = data[3];
    mm = data[4];
    ss = data[5];
    offset = (int8_t)data[6];
    
  } else if (len >= 6 && data[0] == 0x01) {
    // パターン2：Version が [0]
    
    hh = data[1];
    mm = data[2];
    ss = data[3];
    offset = (int8_t)data[4];
    
  } else {
    return false;
  }
  
  // ペイロード表示（デバッグ）
  
  Serial.print("[DEBUG] Parsed: ");
  if (hh < 10) Serial.print("0");
  Serial.print(hh);
  Serial.print(":");
  if (mm < 10) Serial.print("0");
  Serial.print(mm);
  Serial.print(":");
  if (ss < 10) Serial.print("0");
  Serial.print(ss);
  Serial.print(" offset=");
  if (offset >= 0) Serial.print("+");
  Serial.println(offset);
  
  // 検証: 時刻が有効範囲か
  if (hh < 0 || hh > 23 || mm < 0 || mm > 59 || ss < 0 || ss > 59) {
    return false;
  }
  
  // ★重要: 同じ時刻を受け取った場合はスキップ（重複更新を防止）
  uint32_t receivedTimeSeconds = hh * 3600 + mm * 60 + ss;
  if (receivedTimeSeconds == lastReceivedTimeSeconds) {
    return false;
  }
  lastReceivedTimeSeconds = receivedTimeSeconds;
  
  // 時刻適用（オフセット込み）
  int32_t send_sec = hh * 3600 + mm * 60 + ss;
  int32_t adj = send_sec + (int32_t)offset * 60;
  adj %= 86400;
  if (adj < 0) adj += 86400;
  
  base_sec = (uint32_t)adj;
  base_ms = (uint32_t)millis();
  time_valid = true;
  
  // オフセット（分）を保存してモータシーケンス開始
  targetMinutes = offset;
  offsetMinutes = targetMinutes - currentTargetMinutes;  // 差分を計算
  newDataReceived = true;
  
  return true;
}

// BLE非同期スキャンタスク
void bleScanTask(void* parameter) {
  uint32_t scanCount = 0;
  uint32_t deviceCount = 0;
  uint32_t mfgCount = 0;
  uint32_t processedCount = 0;
  
  while (bleTaskRunning) {
    if (!pBLEScan) {
      vTaskDelay(pdMS_TO_TICKS(500));
      continue;
    }
    
    // ★モータ動作中はBLEスキャンをスキップ（割り込み防止）
    if (motorSequenceRunning) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    
    // スキャン実行
    BLEScanResults* foundDevices = pBLEScan->start(2, false);  // 2秒スキャン
    
    if (!foundDevices) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    
    scanCount++;
    int count = foundDevices->getCount();
    deviceCount += count;
    
    // スキャン結果を処理
    bool found = false;
    for (int i = 0; i < count; i++) {
      BLEAdvertisedDevice device = foundDevices->getDevice(i);
      
      // ★重要: デバイス名で「TimeFaker_TX」をフィルタリング
      String devName = device.getName();
      
      if (devName != "TimeFaker_TX") {
        continue;  // TimeFaker_TX以外は無視
      }
      
      if (device.haveManufacturerData()) {
        mfgCount++;
        
        // ★重要: c_str() を使わず、length() を指定して取得（0x00での切り詰め防止）
        String rawData = device.getManufacturerData();
        size_t dataLen = rawData.length();
        const uint8_t* raw = (const uint8_t*)rawData.c_str();
        
        // Manufacturer ID を含む可能性がある: [0-1]=0x55 0xAA
        // または Version が [0]=0x01 かもしれない
        // 両パターンチェック
        bool isTimeFaker = false;
        
        if (dataLen >= 8 && raw[0] == 0x55 && raw[1] == 0xAA) {
          isTimeFaker = true;
        } else if (dataLen >= 6 && raw[0] == 0x01) {
          isTimeFaker = true;
        }
        
        if (isTimeFaker) {
          processedCount++;
          if (applyBroadcastPacket(raw, dataLen)) {
            ackRequest = true;
            found = true;
            break;
          }
        }
      }
    }
    
    if (scanCount % 10 == 0) {
      Serial.print("[BLE Stats] Scans:");
      Serial.print(scanCount);
      Serial.print(" Devices:");
      Serial.print(deviceCount);
      Serial.print(" MFG:");
      Serial.print(mfgCount);
      Serial.print(" Processed:");
      Serial.println(processedCount);
    }
    
    if (scanCount % 10 == 0) {
      Serial.print("[BLE Stats] Scans:");
      Serial.print(scanCount);
      Serial.print(" Devices:");
      Serial.print(deviceCount);
      Serial.print(" MFG:");
      Serial.print(mfgCount);
      Serial.print(" Processed:");
      Serial.println(processedCount);
    }
    
    pBLEScan->clearResults();  // メモリ解放
    
    vTaskDelay(pdMS_TO_TICKS(500));  // 500ms待機
  }
  
  vTaskDelete(nullptr);
}

bool bleStarted = false;

void setMotor1Step(int step) {
  step = step % 4;
  if (step < 0) step += 4;
  
  digitalWrite(MOTOR1_PIN1, STEP_PATTERN[step][0]);
  digitalWrite(MOTOR1_PIN2, STEP_PATTERN[step][1]);
  digitalWrite(MOTOR1_PIN3, STEP_PATTERN[step][2]);
  digitalWrite(MOTOR1_PIN4, STEP_PATTERN[step][3]);
}

void setMotor2Step(int step) {
  step = step % 4;
  if (step < 0) step += 4;
  
  digitalWrite(MOTOR2_PIN1, STEP_PATTERN[step][0]);
  digitalWrite(MOTOR2_PIN2, STEP_PATTERN[step][1]);
  digitalWrite(MOTOR2_PIN3, STEP_PATTERN[step][2]);
  digitalWrite(MOTOR2_PIN4, STEP_PATTERN[step][3]);
}

void stopMotor1() {
  digitalWrite(MOTOR1_PIN1, LOW);
  digitalWrite(MOTOR1_PIN2, LOW);
  digitalWrite(MOTOR1_PIN3, LOW);
  digitalWrite(MOTOR1_PIN4, LOW);
}

void stopMotor2() {
  digitalWrite(MOTOR2_PIN1, LOW);
  digitalWrite(MOTOR2_PIN2, LOW);
  digitalWrite(MOTOR2_PIN3, LOW);
  digitalWrite(MOTOR2_PIN4, LOW);
}

void startMotorSequence() {
  if (motorSequenceRunning) return;
  
  motorSequenceRunning = true;
  currentSequence = SEQ_MOTOR2_FORWARD;
  sequenceStep = 0;
  lastStepTime = millis();
}

void startMotor2Serial(int degrees) {
  if (motorSequenceRunning) {
    Serial.println("[WARN] Motor busy, ignoring serial command");
    return;
  }
  
  // 度数をステップ数に変換（2048ステップ/360度）
  int steps = abs(degrees) * 2048 / 360;
  
  if (steps == 0) {
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

void updateMotorSequence() {
  if (!motorSequenceRunning) return;
  
  uint32_t now = millis();
  if ((now - lastStepTime) < STEP_DELAY_MS) return;
  
  lastStepTime = now;
  
  switch (currentSequence) {
    case SEQ_MOTOR2_FORWARD:
      // 20度回転（2048ステップ/360度 → 20度 = 114ステップ）
      if (sequenceStep < 114) {
        motor2Position++;
        setMotor2Step(motor2Position);
        sequenceStep++;
      } else {
        // 次のシーケンスへ
        stopMotor2();
        currentSequence = SEQ_MOTOR1_ROTATE;
        sequenceStep = 0;
      }
      break;
      
    case SEQ_MOTOR1_ROTATE:
      {
        // 60分 = 550度、1分 = 9.167度
        // 2048ステップ/360度 → 1度 = 5.69ステップ
        // 1分(9.167度) = 52.16ステップ ≈ 52ステップ
        int totalSteps = abs(offsetMinutes) * 52;
        
        if (totalSteps == 0) {
          // オフセット0の場合はスキップ
          stopMotor1();
          currentSequence = SEQ_MOTOR2_BACKWARD;
          sequenceStep = 0;
        } else if (sequenceStep < totalSteps) {
          if (offsetMinutes > 0) {
            motor1Position--;
          } else if (offsetMinutes < 0) {
            motor1Position++;
          }
          setMotor1Step(motor1Position);
          sequenceStep++;
        } else {
          // 次のシーケンスへ
          stopMotor1();
          currentSequence = SEQ_MOTOR2_BACKWARD;
          sequenceStep = 0;
        }
      }
      break;
      
    case SEQ_MOTOR2_BACKWARD:
      // -20度回転（114ステップ戻す）
      if (sequenceStep < 114) {
        motor2Position--;
        setMotor2Step(motor2Position);
        sequenceStep++;
      } else {
        // シーケンス完了
        stopMotor1();
        stopMotor2();
        motorSequenceRunning = false;
        currentSequence = SEQ_IDLE;
        sequenceStep = 0;
        currentTargetMinutes = targetMinutes;  // 現在の目標位置を更新
      }
      break;
      
    case SEQ_MOTOR2_SERIAL:
      // シリアル受信によるモータ2の直接制御
      if (sequenceStep < serialMotor2Steps) {
        if (serialMotor2Direction > 0) {
          motor2Position++;
        } else {
          motor2Position--;
        }
        setMotor2Step(motor2Position);
        sequenceStep++;
      } else {
        // 回転完了
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

void startBLE() {
  BLEDevice::init(BLE_NAME);
  delay(100);

  pBLEScan = BLEDevice::getScan();
  pBLEScan->setActiveScan(false);     // パッシブスキャン
  pBLEScan->setInterval(97);          // 約100ms
  pBLEScan->setWindow(97);            // 約100ms（intervalと同じで連続スキャン）
  pBLEScan->setDuplicateFilter(true); // 重複鑑別有効

  // BLEスキャンを非同期タスクで実行
  bleTaskRunning = true;
  xTaskCreatePinnedToCore(
    bleScanTask,
    "BLETask",
    3072,           // スタック量を例外処理用に拡張
    nullptr,
    1,              // 優先度（低優先度）
    &bleTaskHandle,
    0               // Core 0
  );
}

uint32_t nowSeconds() {
  if (!time_valid) return (millis() / 1000) % 86400;
  uint32_t elapsed = (millis() - base_ms) / 1000;
  return (base_sec + elapsed) % 86400;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  // LED初期化
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH); // 起動時点灯

  // モータ1初期化
  pinMode(MOTOR1_PIN1, OUTPUT);
  pinMode(MOTOR1_PIN2, OUTPUT);
  pinMode(MOTOR1_PIN3, OUTPUT);
  pinMode(MOTOR1_PIN4, OUTPUT);
  stopMotor1();

  // モータ2初期化
  pinMode(MOTOR2_PIN1, OUTPUT);
  pinMode(MOTOR2_PIN2, OUTPUT);
  pinMode(MOTOR2_PIN3, OUTPUT);
  pinMode(MOTOR2_PIN4, OUTPUT);
  stopMotor2();

  // 起動=0:00
  base_sec = 0;
  base_ms  = millis();
  time_valid = true;

  // BLE初期化（起動時に実行）
  delay(500);  // 安定待ち
  startBLE();
  bleStarted = true;
}

void loop() {
  // シリアル受信処理（モータ2直接制御）
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    
    if (input.length() > 0) {
      int degrees = input.toInt();
      if (degrees != 0 || input == "0") {
        // 有効な数値を受信
        startMotor2Serial(degrees);
      } else {
        Serial.println("[ERROR] Invalid input. Enter degrees (e.g., 45, -30)");
      }
    }
  }
  
  // BLEデータ受信時のモータシーケンス開始
  if (newDataReceived) {
    newDataReceived = false;
    startMotorSequence();
  }

  // モータシーケンス更新
  updateMotorSequence();

  delay(1);
}
