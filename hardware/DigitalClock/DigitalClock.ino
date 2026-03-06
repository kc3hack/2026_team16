#include <TM1637Display.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

// ===== TM1637 =====
constexpr uint8_t PIN_CLK = 10;
constexpr uint8_t PIN_DIO = 9;
TM1637Display display(PIN_CLK, PIN_DIO);

// ===== motor vibration (GPIO10 was already used for TM1637, need different pin) =====
// Note: GPIO10 is used for TM1637 CLK. Using GPIO11 instead for motor control
constexpr uint8_t MOTOR_PIN = 11;
constexpr uint8_t MOTOR_CHANNEL = 0;
constexpr uint8_t MOTOR_RES = 8;
constexpr uint8_t MOTOR_DUTY_PERCENT = 50;
bool motorPwmAttached = false;

void motorOn(uint16_t freq_hz = 1000)
{
  if (!motorPwmAttached)
  {
    ledcSetup(MOTOR_CHANNEL, freq_hz, MOTOR_RES);
    ledcAttachPin(MOTOR_PIN, MOTOR_CHANNEL);
    motorPwmAttached = true;
  }
  uint32_t maxDuty = (1u << MOTOR_RES) - 1;
  uint32_t dutyVal = (maxDuty * MOTOR_DUTY_PERCENT) / 100;
  ledcWrite(MOTOR_CHANNEL, dutyVal);
}

void motorOff()
{
  if (motorPwmAttached)
  {
    ledcDetachPin(MOTOR_PIN);
    motorPwmAttached = false;
  }
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);
}

// ===== buttons =====
constexpr uint8_t BTN1_PIN = 4; // モード切替/決定/スヌーズ
constexpr uint8_t BTN2_PIN = 5; // 値変更/ストップ
constexpr uint16_t DEBOUNCE_MS = 50;

// ボタン割り込みフラグ（volatile必須）
volatile bool btn1_pressed_flag = false;
volatile bool btn2_pressed_flag = false;
volatile uint32_t btn1_pressed_time = 0;
volatile uint32_t btn2_pressed_time = 0;

// Button構造体の前方宣言
typedef struct
{
  uint8_t pin;
  bool lastState;
  bool pressed;
  uint32_t lastChange;
  uint32_t pressStart; // 押開始時刻
} Button;

Button btn1 = {BTN1_PIN, HIGH, false, 0, 0};
Button btn2 = {BTN2_PIN, HIGH, false, 0, 0};

constexpr uint16_t LONG_PRESS_MS = 500;      // 長押し開始時間
constexpr uint16_t REPEAT_INTERVAL_MS = 100; // 長押し時の繰り返し間隔

// ボタン割り込みハンドラ
void IRAM_ATTR btn1_isr()
{
  btn1_pressed_time = millis();
  if (digitalRead(BTN1_PIN) == LOW && !btn1_pressed_flag)
  {
    btn1_pressed_flag = true;
  }
}

void IRAM_ATTR btn2_isr()
{
  btn2_pressed_time = millis();
  if (digitalRead(BTN2_PIN) == LOW && !btn2_pressed_flag)
  {
    btn2_pressed_flag = true;
  }
}

bool isButtonPressed(Button &btn);
bool isButtonLongPressed(Button &btn);
bool checkButtonRepeat(Button &btn);

// ===== buzzer =====
constexpr uint8_t BUZZ_PIN = 3;
constexpr uint8_t BUZZ_CHANNEL = 1;
constexpr uint8_t BUZZ_RES = 10;
constexpr uint8_t BUZZ_DUTY_PERCENT = 50;
bool pwmAttached = false;

uint32_t dutyValue()
{
  uint32_t maxDuty = (1u << BUZZ_RES) - 1;
  return (maxDuty * BUZZ_DUTY_PERCENT) / 100;
}
void buzzerForceLow()
{
  if (pwmAttached)
  {
    ledcDetachPin(BUZZ_PIN);
    pwmAttached = false;
  }
  pinMode(BUZZ_PIN, OUTPUT);
  digitalWrite(BUZZ_PIN, LOW);
}
void buzzerOn(uint16_t freq_hz)
{
  if (freq_hz == 0)
  {
    buzzerForceLow();
    return;
  }
  if (!pwmAttached)
  {
    ledcSetup(BUZZ_CHANNEL, freq_hz, BUZZ_RES);
    ledcAttachPin(BUZZ_PIN, BUZZ_CHANNEL);
    pwmAttached = true;
  }
  else
  {
    ledcChangeFrequency(BUZZ_CHANNEL, freq_hz, BUZZ_RES);
  }
  ledcWrite(BUZZ_CHANNEL, dutyValue());
}
void buzzerOff() { buzzerForceLow(); }

// 音符データ構造
struct Note
{
  uint16_t f;
  uint16_t ms;
};

// ボタン押下音：短い単音のラ
constexpr uint16_t F_LA = 1760; // A6
constexpr Note BEEP[] = {{F_LA, 100}, {0, 0}};

// ACK音：ラ・ラ（ピピッ）
constexpr Note ACK[] = {{F_LA, 80}, {0, 60}, {F_LA, 80}, {0, 0}};

// アラーム音：ソファソ
constexpr uint16_t F_FA = 1397; // F6
constexpr uint16_t F_SO = 1568; // G6
constexpr uint16_t SEG_MS = 200;
constexpr Note ALARM_PATTERN[] = {
    {F_SO, SEG_MS},
    {F_FA, SEG_MS},
    {F_SO, SEG_MS},
    {0, SEG_MS},
};
constexpr uint8_t ALARM_REPEAT = 5;

// ===== 汎用サウンド再生 =====
bool soundPlaying = false;
const Note *soundPattern = nullptr;
uint8_t soundIdx = 0;
uint8_t soundRepeat = 0;
uint8_t soundRepeatLeft = 0;
uint32_t soundStart = 0;

// 振動状態
bool motorPlaying = false;
uint32_t motorStart = 0;

void startSound(const Note *pattern, uint8_t patternLen, uint8_t repeat = 1)
{
  soundPlaying = true;
  soundPattern = pattern;
  soundIdx = 0;
  soundRepeat = patternLen;
  soundRepeatLeft = repeat;
  soundStart = millis();
  buzzerOn(pattern[0].f);

  // アラーム音（周波数 > 0）ならモーターも開始
  if (pattern[0].f > 0)
  {
    motorPlaying = true;
    motorStart = millis();
    motorOn();
  }
}

void updateSound()
{
  if (!soundPlaying)
    return;
  uint32_t now = millis();
  uint16_t dur = soundPattern[soundIdx].ms;
  if (dur > 0 && (now - soundStart) < dur)
    return;

  soundStart = now;
  soundIdx++;

  if (soundIdx >= soundRepeat)
  {
    soundIdx = 0;
    // soundRepeatLeft == 255の場合は無限ループ
    if (soundRepeatLeft == 255)
    {
      buzzerOn(soundPattern[soundIdx].f);
      // アラーム音ならモーターも再開
      if (soundPattern[soundIdx].f > 0)
      {
        motorPlaying = true;
        motorStart = millis();
        motorOn();
      }
      return;
    }
    if (soundRepeatLeft > 0)
      soundRepeatLeft--;
    if (soundRepeatLeft == 0)
    {
      soundPlaying = false;
      buzzerOff();
      motorPlaying = false;
      motorOff();
      return;
    }
  }
  buzzerOn(soundPattern[soundIdx].f);

  // 音に合わせてモーター制御
  if (soundPattern[soundIdx].f > 0)
  {
    if (!motorPlaying)
    {
      motorPlaying = true;
      motorStart = millis();
      motorOn();
    }
  }
  else
  {
    motorPlaying = false;
    motorOff();
  }
}

void stopSound()
{
  soundPlaying = false;
  buzzerOff();
  motorPlaying = false;
  motorOff();
}

bool ackPlaying = false;
uint8_t ackIdx = 0;
uint32_t ackStart = 0;

void startAck()
{
  ackPlaying = true;
  ackIdx = 0;
  ackStart = millis();
  buzzerOn(ACK[0].f);
}
void updateAck()
{
  if (!ackPlaying)
    return;
  uint32_t now = millis();
  uint16_t dur = ACK[ackIdx].ms;
  if (dur > 0 && (now - ackStart) < dur)
    return;

  ackStart = now;
  ackIdx++;
  if (ackIdx >= (sizeof(ACK) / sizeof(ACK[0])))
  {
    ackPlaying = false;
    buzzerOff();
    return;
  }
  buzzerOn(ACK[ackIdx].f);
}

// ===== internal clock base (0:00 start) =====
volatile uint32_t base_sec = 0;
volatile uint32_t base_ms = 0;
volatile bool time_valid = false;

// ===== アラーム機能 =====
enum Mode
{
  MODE_CLOCK,      // 通常時刻表示
  MODE_ALARM_VIEW, // アラーム時刻表示
  MODE_SET_HOUR,   // 時設定
  MODE_SET_MIN,    // 分設定
  MODE_ALARMING,   // アラーム鳴動中
  MODE_SNOOZE      // スヌーズ中
};

Mode currentMode = MODE_CLOCK;
uint8_t alarmHour = 7; // デフォルト7:00
uint8_t alarmMin = 0;
bool alarmEnabled = true;    // アラーム有効/無効
uint32_t snoozeUntil = 0;    // スヌーズ解除時刻（秒）
bool alarmTriggered = false; // アラームが鳴った履歴（同じ分に複数回鳴らないため）

// 設定値変更時の即座表示
uint32_t lastEditTime = 0;                // 最後に数字を変えた時刻
constexpr uint16_t EDIT_DISPLAY_MS = 800; // 変更後この時間は点滅を中断して表示

// ボタン押下振動
bool buttonVibrating = false;
uint32_t vibrationStart = 0;
uint16_t vibrationDuration = 0;

// ===== BLE Broadcast Scanning =====
static const char *BLE_NAME = "TimeFaker_RX";
BLEScan *pBLEScan = nullptr;
volatile bool ackRequest = false;
volatile bool bleTaskRunning = false;

// BLE非同期スキャンタスク
void bleScanTask(void *parameter)
{
  uint32_t scanCount = 0;
  uint32_t deviceCount = 0;
  uint32_t mfgCount = 0;
  uint32_t processedCount = 0;

  while (bleTaskRunning)
  {
    if (!pBLEScan)
    {
      vTaskDelay(pdMS_TO_TICKS(500));
      continue;
    }

    // スキャン実行
    BLEScanResults foundDevices = pBLEScan->start(2, false); // 2秒スキャン

    scanCount++;
    int count = foundDevices.getCount();
    deviceCount += count;

    // スキャン結果を処理
    bool found = false;
    for (int i = 0; i < count; i++)
    {
      BLEAdvertisedDevice device = foundDevices.getDevice(i);

      // ★重要: デバイス名で「TimeFaker_TX」をフィルタリング
      std::string devNameStd = device.getName();
      String devName = String(devNameStd.c_str());

      if (devName != "TimeFaker_TX")
      {
        continue; // TimeFaker_TX以外は無視
      }

      if (device.haveManufacturerData())
      {
        mfgCount++;

        // ★重要: c_str() を使わず、length() を指定して取得（0x00での切り詰め防止）
        std::string rawDataStd = device.getManufacturerData();
        size_t dataLen = rawDataStd.length();
        const uint8_t *raw = (const uint8_t *)rawDataStd.c_str();

        // Manufacturer ID を含む可能性がある: [0-1]=0x55 0xAA
        // または Version が [0]=0x01 かもしれない
        // 両パターンチェック
        bool isTimeFaker = false;

        if (dataLen >= 8 && raw[0] == 0x55 && raw[1] == 0xAA)
        {
          isTimeFaker = true;
        }
        else if (dataLen >= 6 && raw[0] == 0x01)
        {
          isTimeFaker = true;
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
        }
      }
    }

    pBLEScan->clearResults(); // メモリ解放

    vTaskDelay(pdMS_TO_TICKS(500)); // 500ms待機
  }
  vTaskDelete(nullptr);
}

// BLE非同期スキャンタスク用
TaskHandle_t bleTaskHandle = nullptr;

// ★前回受け取った時刻（秒単位）を記録して重複更新を防ぐ
static uint32_t lastReceivedTimeSeconds = 0xFFFFFFFF; // 初期値：無効

// ブロードキャストパケット処理（Manufacturer Data形式）
// 2パターン対応:
// パターン1: [0-1]:0x55 0xAA [2]:0x01 [3-5]:HH MM SS [6]:offset [7]:reserved (8bytes total)
// パターン2: [0]:0x01 [1-3]:HH MM SS [4]:offset [5]:reserved (6bytes total)
bool applyBroadcastPacket(const uint8_t *data, size_t len)
{
  int hh, mm, ss;
  int8_t offset;

  // パターン判定
  if (len >= 8 && data[0] == 0x55 && data[1] == 0xAA)
  {
    // パターン1：Manufacturer ID込み
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
    // パターン2：Version が [0]
    hh = data[1];
    mm = data[2];
    ss = data[3];
    offset = (int8_t)data[4];
  }
  else
  {
    return false;
  }

  // 検証: 時刻が有効範囲か
  if (hh < 0 || hh > 23 || mm < 0 || mm > 59 || ss < 0 || ss > 59)
  {
    return false;
  }

  // ★重要: 同じ時刻を受け取った場合はスキップ（重複更新を防止）
  uint32_t receivedTimeSeconds = hh * 3600 + mm * 60 + ss;
  if (receivedTimeSeconds == lastReceivedTimeSeconds)
  {
    return false;
  }
  lastReceivedTimeSeconds = receivedTimeSeconds;

  // 時刻適用（オフセット込み）
  int32_t send_sec = hh * 3600 + mm * 60 + ss;
  int32_t adj = send_sec + (int32_t)offset * 60;
  adj %= 86400;
  if (adj < 0)
    adj += 86400;

  base_sec = (uint32_t)adj;
  base_ms = (uint32_t)millis();
  time_valid = true;

  return true;
}

bool bleStarted = false;

// ===== Sleep mode =====
bool asleep = false;
bool sleepWaitingForRelease = false; // wait for button release before allowing wake
uint32_t sleepEnteredAt = 0;

void enterSleep()
{
  if (asleep)
    return;
  asleep = true;
  sleepWaitingForRelease = true; // require button release before wake
  sleepEnteredAt = millis();

  // clear display and dim
  display.clear();
  display.setBrightness(0);

  // BLE scanning will continue in background (low power)

  // stop any sounds/vibration
  stopSound();
}

void exitSleep()
{
  if (!asleep)
    return;
  asleep = false;
  sleepWaitingForRelease = false;

  // restore display brightness (will be refreshed by normal loop)
  display.setBrightness(7);

  // BLE scanning continues
}

void startBLE()
{
  BLEDevice::init(BLE_NAME);
  delay(100);

  pBLEScan = BLEDevice::getScan();
  pBLEScan->setActiveScan(false); // パッシブスキャン
  pBLEScan->setInterval(97);      // 約100ms
  pBLEScan->setWindow(97);        // 約100ms（intervalと同じで追踪スキャン）
  // pBLEScan->setDuplicateFilter(true); // 重複鑑別有効 (not supported in this version)

  // BLEスキャンを非同期タスクで実行
  bleTaskRunning = true;
  xTaskCreatePinnedToCore(
      bleScanTask,
      "BLETask",
      3072, // スタック量を異常処理用に拡大
      nullptr,
      1, // 優先度（低優先度）
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
  Serial.begin(115200);
  delay(1000); // ESP32-S3の安定待ち（BLE用に延長）

  // ボタン初期化（内部プルアップ）
  pinMode(BTN1_PIN, INPUT_PULLUP);
  pinMode(BTN2_PIN, INPUT_PULLUP);

  // ボタン割り込みハンドラ設定
  attachInterrupt(digitalPinToInterrupt(BTN1_PIN), btn1_isr, FALLING);
  attachInterrupt(digitalPinToInterrupt(BTN2_PIN), btn2_isr, FALLING);

  // モーター初期化
  motorOff();

  display.setBrightness(7);
  display.clear();

  // 起動=0:00
  base_sec = 0;
  base_ms = millis();
  time_valid = true;

  buzzerOff();

  display.showNumberDecEx(0, 0x40, true);

  // BLE初期化（起動時に実行）
  delay(500); // 安定待ち
  startBLE();
  bleStarted = true;
}

void loop()
{
  // ボタン状態を毎回チェック（割り込みフラグではなく生のピン状態）
  bool btn1Press = isButtonPressed(btn1);
  bool btn2Press = isButtonPressed(btn2);
  bool btn2Repeat = checkButtonRepeat(btn2);

  // 時刻取得
  uint32_t s = nowSeconds();
  uint32_t hh = s / 3600;
  uint32_t mm = (s / 60) % 60;
  uint32_t ss = s % 60;

  // ACK音が必要なら再生
  if (ackRequest)
  {
    ackRequest = false;
    startAck();
  }

  // サウンドと振動更新
  updateAck();
  updateSound();

  // ボタン押下振動の更新
  if (buttonVibrating)
  {
    uint32_t now = millis();
    if ((now - vibrationStart) >= vibrationDuration)
    {
      motorOff();
      buttonVibrating = false;
    }
  }

  // 同時押しでスリープ（両方が安定してLOW）
  bool rawBtn1 = (digitalRead(BTN1_PIN) == LOW);
  bool rawBtn2 = (digitalRead(BTN2_PIN) == LOW);
  uint32_t tnow = millis();
  bool stableBoth = rawBtn1 && rawBtn2 && ((tnow - btn1.lastChange) > DEBOUNCE_MS) && ((tnow - btn2.lastChange) > DEBOUNCE_MS);

  if (!asleep && stableBoth)
  {
    enterSleep();
  }

  // スリープ中: ボタン放されるまで待機、その後押されたら復帰
  if (asleep)
  {
    if (sleepWaitingForRelease)
    {
      // 両ボタンが離されるまで待つ
      if (!rawBtn1 && !rawBtn2)
      {
        sleepWaitingForRelease = false; // release detected
      }
    }
    else
    {
      // ボタンが離された後、いずれかが押されたら復帰
      if (rawBtn1 || rawBtn2)
      {
        exitSleep();
      }
    }
    delay(50);
    return; // skip mode processing while asleep
  }

  // ボタン押下時のビープ音と振動
  if (btn1Press || btn2Press)
  {
    startSound(BEEP, sizeof(BEEP) / sizeof(BEEP[0]), 1);
    // ボタン音と同じ長さ（100ms）で振動
    buttonVibrating = true;
    vibrationStart = millis();
    vibrationDuration = 100;
    motorOn();
  }

  // モード別処理
  switch (currentMode)
  {
  case MODE_CLOCK:
    if (btn1Press)
    {
      // アラーム時刻表示モードへ
      currentMode = MODE_ALARM_VIEW;
      pauseBLEScan(); // 設定UI中はBLEスキャンを停止
    }
    // アラームチェック
    if (alarmEnabled && hh == alarmHour && mm == alarmMin && ss == 0 && !alarmTriggered)
    {
      currentMode = MODE_ALARMING;
      alarmTriggered = true;
      // アラーム音を無限ループ（255 = 無限）
      startSound(ALARM_PATTERN, sizeof(ALARM_PATTERN) / sizeof(ALARM_PATTERN[0]), 255);
    }
    // 分が変わったらトリガーリセット
    if (mm != alarmMin)
    {
      alarmTriggered = false;
    }
    break;

  case MODE_ALARM_VIEW:
    if (btn1Press)
    {
      // 時設定モードへ
      currentMode = MODE_SET_HOUR;
      lastEditTime = millis();
    }
    else if (btn2Press)
    {
      // アラーム有効/無効切り替え
      alarmEnabled = !alarmEnabled;
    }
    break;

  case MODE_SET_HOUR:
    if (btn1Press)
    {
      // 分設定モードへ
      currentMode = MODE_SET_MIN;
      lastEditTime = millis();
    }
    else if (btn2Press || btn2Repeat)
    {
      // 時を+1
      alarmHour = (alarmHour + 1) % 24;
      lastEditTime = millis();
    }
    break;

  case MODE_SET_MIN:
    if (btn1Press)
    {
      // 設定完了→通常表示へ
      currentMode = MODE_CLOCK;
      alarmTriggered = false; // 設定変更したのでリセット
      resumeBLEScan();        // BLEスキャン再開
    }
    else if (btn2Press || btn2Repeat)
    {
      // 分を+1
      alarmMin = (alarmMin + 1) % 60;
      lastEditTime = millis();
    }
    break;

  case MODE_ALARMING:
    if (btn1Press)
    {
      // スヌーズ（5分後に再度鳴らす）
      currentMode = MODE_SNOOZE;
      snoozeUntil = s + 300; // 5分 = 300秒
      stopSound();
    }
    else if (btn2Press)
    {
      // ストップ
      currentMode = MODE_CLOCK;
      stopSound();
    }
    break;

  case MODE_SNOOZE:
    // スヌーズ時刻チェック
    if (s >= snoozeUntil)
    {
      currentMode = MODE_ALARMING;
      // アラーム音を無限ループ（255 = 無限）
      startSound(ALARM_PATTERN, sizeof(ALARM_PATTERN) / sizeof(ALARM_PATTERN[0]), 255);
    }
    else if (btn1Press)
    {
      // スヌーズ中にボタン1でスヌーズ再開（新たに5分延長）
      snoozeUntil = s + 300;
    }
    else if (btn2Press)
    {
      // スヌーズ中にボタン2でストップ
      currentMode = MODE_CLOCK;
      stopSound();
    }
    break;
  }

  // 設定モード終了時のBLEスキャン再開チェック
  if (currentMode == MODE_CLOCK || currentMode == MODE_ALARMING || currentMode == MODE_SNOOZE)
  {
    // これらのモードではBLEスキャンが有効
    if (!bleTaskRunning && bleStarted)
    {
      resumeBLEScan();
    }
  }
  else if (currentMode == MODE_ALARM_VIEW || currentMode == MODE_SET_HOUR || currentMode == MODE_SET_MIN)
  {
    // これらのモード（設定UI）ではBLEスキャンを停止
    if (bleTaskRunning)
    {
      pauseBLEScan();
    }
  }

  // 表示更新
  uint16_t displayValue;
  uint8_t colonMask = (ss % 2 == 0) ? 0x40 : 0x00;
  bool leadingZero = true;
  uint32_t now = millis();
  bool inEditWindow = (now - lastEditTime) < EDIT_DISPLAY_MS;

  switch (currentMode)
  {
  case MODE_CLOCK:
  case MODE_ALARMING:
  case MODE_SNOOZE:
    displayValue = (uint16_t)(hh * 100 + mm);
    display.showNumberDecEx(displayValue, colonMask, leadingZero);
    break;

  case MODE_ALARM_VIEW:
    // ON/OFF選択表示
    {
      uint8_t segments[4] = {0x00, 0x00, 0x00, 0x00};
      if (alarmEnabled)
      {
        // ON表示：非表示 非表示 0 n
        segments[0] = 0x00;                   // 非表示
        segments[1] = 0x00;                   // 非表示
        segments[2] = display.encodeDigit(0); // 0
        segments[3] = 0x37;                   // n のセグメント値
      }
      else
      {
        // OFF表示：非表示 0 F F
        segments[0] = 0x00;                   // 非表示
        segments[1] = display.encodeDigit(0); // 0
        segments[2] = 0x71;                   // F のセグメント値
        segments[3] = 0x71;                   // F のセグメント値
      }
      display.setSegments(segments);
    }
    break;

  case MODE_SET_HOUR:
    displayValue = (uint16_t)(alarmHour * 100 + alarmMin);
    // 変更直後は常時表示、その後は上2桁（時）のみ点滅
    if (inEditWindow)
    {
      // 編集直後：全体を常時表示
      display.showNumberDecEx(displayValue, 0x00, leadingZero);
    }
    else
    {
      // 通常点滅：時の両桁を点滅
      if (ss % 2 == 0)
      {
        // 時と分を表示
        display.showNumberDecEx(displayValue, 0x00, leadingZero);
      }
      else
      {
        // 時を消す（分のみ表示）
        uint8_t segments[4] = {0x00, 0x00, 0x00, 0x00};
        uint8_t minTens = alarmMin / 10;
        uint8_t minOnes = alarmMin % 10;
        segments[2] = display.encodeDigit(minTens);
        segments[3] = display.encodeDigit(minOnes);
        display.setSegments(segments);
      }
    }
    break;

  case MODE_SET_MIN:
    displayValue = (uint16_t)(alarmHour * 100 + alarmMin);
    // 変更直後は常時表示、その後は下2桁（分）を非表示切り替え
    if (inEditWindow)
    {
      // 編集直後：全体を常時表示
      display.showNumberDecEx(displayValue, 0x00, leadingZero);
    }
    else
    {
      // 通常表示：分の両桁を点滅
      if (ss % 2 == 0)
      {
        // 分を表示
        display.showNumberDecEx(displayValue, 0x00, leadingZero);
      }
      else
      {
        // 分を消す（時のみ表示）
        uint8_t segments[4] = {0x00, 0x00, 0x00, 0x00};
        uint8_t hourTens = alarmHour / 10;
        uint8_t hourOnes = alarmHour % 10;
        segments[0] = display.encodeDigit(hourTens);
        segments[1] = display.encodeDigit(hourOnes);
        display.setSegments(segments);
      }
    }
    break;
  }

  delay(20);
}

// ===== BLE スキャン制御 =====
void pauseBLEScan()
{
  if (bleTaskRunning)
  {
    bleTaskRunning = false;
    vTaskDelay(pdMS_TO_TICKS(100)); // タスク停止を待機
  }
}

void resumeBLEScan()
{
  if (!bleTaskRunning && bleStarted)
  {
    bleTaskRunning = true;
    xTaskCreatePinnedToCore(
        bleScanTask,
        "BLETask",
        3072,
        nullptr,
        1,
        &bleTaskHandle,
        0);
  }
}

// ===== ボタン関数実装 =====
bool isButtonPressed(Button &btn)
{
  bool current = digitalRead(btn.pin);
  uint32_t now = millis();

  // 状態が変わった場合、時刻を記録
  if (current != btn.lastState)
  {
    btn.lastChange = now;
    btn.lastState = current;
  }

  // デバウンス完了後に確認
  if ((now - btn.lastChange) > DEBOUNCE_MS)
  {
    // LOW に安定した＆まだ pressed フラグが立っていない → 押下検出
    if (current == LOW && !btn.pressed)
    {
      btn.pressed = true;
      btn.pressStart = now;
      return true; // 押下イベント
    }
    // HIGH に戻った ＆ pressed フラグが立っていた → 解放
    else if (current == HIGH && btn.pressed)
    {
      btn.pressed = false;
    }
  }
  return false;
}

bool isButtonLongPressed(Button &btn)
{
  if (!btn.pressed)
    return false;
  uint32_t now = millis();
  return (now - btn.pressStart) >= LONG_PRESS_MS;
}

bool checkButtonRepeat(Button &btn)
{
  if (!btn.pressed)
    return false;
  // 長押し判定に達しているか確認
  if (!isButtonLongPressed(btn))
    return false;

  uint32_t now = millis();
  uint32_t elapsed = now - btn.pressStart;
  // 500ms以降、100ms間隔で繰り返し
  if (elapsed >= LONG_PRESS_MS && ((elapsed - LONG_PRESS_MS) % REPEAT_INTERVAL_MS) < 20)
  {
    return true;
  }
  return false;
}
