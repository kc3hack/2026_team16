// ESP32-S3 Arduino
// LM393 OUT: Dark=HIGH, Bright=LOW
// Serial Monitor: 115200 bps

const int SENSOR_PIN = 12;          // ←接続したGPIO番号に変更
const unsigned long DEBOUNCE_MS = 50;

int lastStable = -1;
int lastRead = -1;
unsigned long lastChangeMs = 0;

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(SENSOR_PIN, INPUT);      // 外付けプルアップがあるなら INPUT でOK
  // pinMode(SENSOR_PIN, INPUT_PULLUP); // 外付けが無い/弱い場合の保険

  lastRead = digitalRead(SENSOR_PIN);
  lastStable = lastRead;
  Serial.println("=== LM393 Dark Trigger Test (ESP32-S3) ===");
  Serial.printf("SENSOR_PIN = GPIO%d  (Dark=HIGH)\n", SENSOR_PIN);
  Serial.printf("Initial: %s (%d)\n", lastStable ? "DARK" : "BRIGHT", lastStable);
}

void loop() {
  int v = digitalRead(SENSOR_PIN);

  // 変化を検出したらタイマーリセット（デバウンス）
  if (v != lastRead) {
    lastRead = v;
    lastChangeMs = millis();
  }

  // 一定時間同じ状態なら「確定」とみなす
  if ((millis() - lastChangeMs) > DEBOUNCE_MS && v != lastStable) {
    lastStable = v;
    Serial.printf("[%lu ms] %s (%d)\n", millis(), lastStable ? "Bright" : "Dark", lastStable);
  }

  delay(5);
}