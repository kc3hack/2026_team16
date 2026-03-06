/*
  ============================================================================
  ESP32-S3 Super Mini
  BLE Wi-Fi Provisioning + Conditional Web OTA + BLE Debug Monitor

  Document: CreatePlan.md v0.1 / SpecifcationDoc.md v0.2
  ============================================================================
*/

#include <WiFi.h>
#include <Update.h>
#include <Preferences.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <esp32-hal-rgb-led.h>

// =============================================================================
// Constants & Configuration
// =============================================================================

#ifndef LOG_SERIAL_ENABLED
#define LOG_SERIAL_ENABLED 1
#endif
#define SERIAL_BAUD 115200

// Wi-Fi
#define WIFI_SSID_MAX 32
#define WIFI_PASS_MAX 64

// Time Broadcast via BLE (TimeFaker)
#define BROADCAST_INTERVAL_MS 5000

// NTP Time Synchronization
#include <time.h>
const char *ntpServer = "pool.ntp.org";
const long gmtOffset_sec = 9 * 3600; // Japan GMT+9
const int daylightOffset_sec = 0;

// Status LED (ESP32-S3 Super Mini compatibility)
#define STATUS_LED_GPIO_PIN 47
#define STATUS_LED_RGB_PIN 48

// NVS Namespace
const char *NVS_WIFI_NS = "wifi";
const char *NVS_SYSCFG_NS = "syscfg";

// BLE Debug Service UUID (128-bit from spec)
#define DEBUG_SERVICE_UUID "7f3f0001-6b7c-4f2e-9b8a-1a2b3c4d5e6f"
#define DEBUG_LOG_TX_UUID "7f3f0002-6b7c-4f2e-9b8a-1a2b3c4d5e6f"
#define DEBUG_CMD_RX_UUID "7f3f0003-6b7c-4f2e-9b8a-1a2b3c4d5e6f"
#define DEBUG_STAT_UUID "7f3f0005-6b7c-4f2e-9b8a-1a2b3c4d5e6f"

// BLE Provisioning Service UUID
#define PROV_SERVICE_UUID "8f4f0001-7c8d-5f3e-ac9b-2b3c4d5e6f70"
#define PROV_WIFI_CONFIG_UUID "8f4f0002-7c8d-5f3e-ac9b-2b3c4d5e6f70"

// BLE OTA Service UUID
#define OTA_SERVICE_UUID "9f5f0001-8d9e-6f4e-bd0c-3c4d5e6f7180"
#define OTA_CONTROL_UUID "9f5f0002-8d9e-6f4e-bd0c-3c4d5e6f7180"
#define OTA_DATA_UUID "9f5f0003-8d9e-6f4e-bd0c-3c4d5e6f7180"
#define OTA_STATUS_UUID "9f5f0004-8d9e-6f4e-bd0c-3c4d5e6f7180"

// =============================================================================
// Global Variables
// =============================================================================

Preferences nvs_wifi;
Preferences nvs_syscfg;

// TimeFaker Time Broadcast
volatile int8_t currentOffset = 0; // Current offset in minutes
volatile bool offsetChanged = false;
volatile int fixedHour = 0; // Fixed time when offset was received
volatile int fixedMinute = 0;
volatile int fixedSecond = 0;
volatile bool useFixedTime = false; // Whether to use fixed time or current time

// State
typedef enum
{
    STATE_FACTORY_RESET_DETECT,
    STATE_PROVISIONING,
    STATE_APP_RUNNING,
} system_state_t;

typedef enum
{
    WIFI_IDLE = 0,
    WIFI_CONNECTING,
    WIFI_CONNECTED,
    WIFI_FAILED,
} wifi_state_t;

struct
{
    system_state_t system_state;
    wifi_state_t wifi_state;
    char wifi_ip[16];
    char device_name[32];
} g_state = {STATE_FACTORY_RESET_DETECT, WIFI_IDLE, "", ""};

// BLE
BLEServer *pServer = NULL;
BLECharacteristic *pDebugLogTx = NULL;
BLECharacteristic *pDebugCmdRx = NULL;
BLECharacteristic *pDebugStat = NULL;
BLECharacteristic *pProvWifiConfig = NULL;
BLECharacteristic *pOtaControl = NULL;
BLECharacteristic *pOtaData = NULL;
BLECharacteristic *pOtaStatus = NULL;

// OTA via BLE state
bool ota_mode_active = false;
size_t ota_expected_size = 0;
size_t ota_received_size = 0;
size_t ota_last_reported_size = 0;
bool ota_in_progress = false;
bool ota_finalize_requested = false;
bool ota_abort_requested = false;
bool provisioning_in_progress = false;

// Reboot management
bool reboot_requested = false;
unsigned long reboot_timestamp = 0;
const unsigned long REBOOT_DELAY_MS = 2000;

// Power saving: WiFi/OTA timeout after boot
unsigned long boot_timestamp = 0;
const unsigned long WIFI_OTA_TIMEOUT_MS = 60000; // 1 minute
bool wifi_ota_timeout_passed = false;
bool wifi_ota_timeout_deferred_logged = false;

void status_led_init()
{
    pinMode(STATUS_LED_GPIO_PIN, OUTPUT);
    digitalWrite(STATUS_LED_GPIO_PIN, HIGH);
    neopixelWrite(STATUS_LED_RGB_PIN, 0, 0, 0);
}

void status_led_blink_aws()
{
    digitalWrite(STATUS_LED_GPIO_PIN, LOW);
    neopixelWrite(STATUS_LED_RGB_PIN, 0, 24, 0);
    delay(120);
    digitalWrite(STATUS_LED_GPIO_PIN, HIGH);
    neopixelWrite(STATUS_LED_RGB_PIN, 0, 0, 0);
}

bool ble_device_connected = false;

void log_println(const char *msg);

// =============================================================================
// Utility Functions
// =============================================================================

void log_println(const char *msg)
{
    if (LOG_SERIAL_ENABLED)
    {
        Serial.println(msg);
        Serial.flush();
    }

    // Send via BLE if connected (real-time only) - but NOT during OTA or provisioning
    if (ble_device_connected && pDebugLogTx && !ota_in_progress && !provisioning_in_progress)
    {
        size_t len = strlen(msg);
        if (len > 0)
        {
            // BLE can send up to 512 bytes, but keep it safe at 200
            if (len > 200)
                len = 200;
            pDebugLogTx->setValue((uint8_t *)msg, len);
            pDebugLogTx->notify();
            delay(10); // Small delay to avoid overwhelming BLE stack
        }
    }
}

void setupNTP()
{
    log_println("[I] Setting up NTP time synchronization...");

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
        char time_msg[64];
        snprintf(time_msg, sizeof(time_msg), "[I] NTP sync success: %s", ctime(&now));
        log_println(time_msg);
    }
    else
    {
        log_println("[W] NTP sync timeout - using default time");
    }
}

void broadcastTimeNoId(int hh, int mm, int ss, int8_t offset_min)
{
    // Manufacturer Data payload (ID-less pattern for reception side pattern 2):
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
    std::string payload((char *)mfgData, sizeof(mfgData));
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

    // Debug output - only to Serial
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
    for (int i = 0; i < 6; i++)
    {
        if (mfgData[i] < 16)
            Serial.print("0");
        Serial.print(mfgData[i], HEX);
        Serial.print(" ");
    }
    Serial.println("]");
}

void updateBroadcast()
{
    // Only broadcast if fixed time has been set (offset received)
    if (!useFixedTime)
    {
        return; // Do not broadcast until offset is received
    }

    // Use fixed time captured when offset was received
    int hh = fixedHour;
    int mm = fixedMinute;
    int ss = fixedSecond;

    // Broadcast (ID-less pattern only)
    broadcastTimeNoId(hh, mm, ss, currentOffset);
}

void wifi_mgr_init(void)
{
    // Initialize Wi-Fi manager (non-blocking setup)
    WiFi.mode(WIFI_STA);
    g_state.wifi_state = WIFI_IDLE;
}

esp_err_t wifi_mgr_connect(void)
{
    if (g_state.wifi_state == WIFI_CONNECTING || g_state.wifi_state == WIFI_CONNECTED)
    {
        return ESP_OK;
    }

    char ssid[WIFI_SSID_MAX] = {0};
    char pass[WIFI_PASS_MAX] = {0};

    nvs_wifi.begin(NVS_WIFI_NS, true);
    size_t ssid_len = nvs_wifi.getString("ssid", ssid, sizeof(ssid));
    size_t pass_len = nvs_wifi.getString("pass", pass, sizeof(pass));
    nvs_wifi.end();

    if (ssid_len == 0)
    {
        log_println("[E] No Wi-Fi config found");
        g_state.wifi_state = WIFI_FAILED;
        return ESP_FAIL;
    }

    // Debug: Show what we're trying to connect to
    char debug_msg[128];
    snprintf(debug_msg, sizeof(debug_msg), "[I] Connecting to SSID: '%s' (len=%d, pass_len=%d)",
             ssid, ssid_len, pass_len);
    log_println(debug_msg);

    log_println("[I] Starting Wi-Fi connection...");
    g_state.wifi_state = WIFI_CONNECTING;

    WiFi.begin(ssid, pass);
    return ESP_OK;
}

bool wifi_mgr_is_connected(void)
{
    return g_state.wifi_state == WIFI_CONNECTED;
}

const char *wifi_mgr_get_ip_str(void)
{
    return g_state.wifi_ip;
}

// =============================================================================
// BLE Callback Classes
// =============================================================================

class MyServerCallbacks : public BLEServerCallbacks
{
    void onConnect(BLEServer *pServer)
    {
        ble_device_connected = true;
        log_println("[I] BLE device connected");

        // Send initial status immediately on connection
        delay(100); // Give BLE stack time to settle

        char status[128];
        snprintf(status, sizeof(status), "[STATUS] WIFI=%d, OTA=%s",
                 g_state.wifi_state,
                 ota_mode_active ? "ACTIVE" : "IDLE");
        log_println(status);
    }

    void onDisconnect(BLEServer *pServer)
    {
        ble_device_connected = false;
        log_println("[I] BLE device disconnected");
    }
};

class MyCharacteristicCallbacks : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *pCharacteristic)
    {
        std::string rxValue = pCharacteristic->getValue();
        if (rxValue.length() > 0)
        {
            String command = String(rxValue.c_str());
            command.trim();

            // Log via BLE as well
            char ble_log[128];
            snprintf(ble_log, sizeof(ble_log), "[BLE RX] %s", command.c_str());
            log_println(ble_log);
            Serial.println("[BLE RX] Command received via Serial");

            // Check if this is an offset value (numeric input)
            bool is_numeric = true;
            if (command.length() > 0)
            {
                for (int i = 0; i < command.length(); i++)
                {
                    if (i == 0 && (command[i] == '-' || command[i] == '+'))
                        continue;
                    if (!isdigit(command[i]))
                    {
                        is_numeric = false;
                        break;
                    }
                }
            }

            if (is_numeric && command.length() > 0)
            {
                // Parse as offset value
                int offset = command.toInt();

                // Validate range
                if (offset < -120 || offset > 120)
                {
                    log_println("[E] Offset out of range (-120 to +120)");
                }
                else
                {
                    // Capture current time when offset is received
                    time_t now = time(nullptr);
                    struct tm *timeinfo = localtime(&now);
                    fixedHour = timeinfo->tm_hour;
                    fixedMinute = timeinfo->tm_min;
                    fixedSecond = timeinfo->tm_sec;

                    currentOffset = offset;
                    offsetChanged = true;
                    useFixedTime = true;

                    char offset_info[128];
                    snprintf(offset_info, sizeof(offset_info),
                             "[I] Time offset set to: %+d minutes at %02d:%02d:%02d",
                             offset, fixedHour, fixedMinute, fixedSecond);
                    log_println(offset_info);

                    // Blink status LED as confirmation
                    digitalWrite(STATUS_LED_GPIO_PIN, LOW);
                    delay(100);
                    digitalWrite(STATUS_LED_GPIO_PIN, HIGH);
                }
            }
            else if (command == "RESET_NVS" || command == "FACTORY_RESET")
            {
                log_println("[I] Factory reset requested via BLE");
                log_println("[I] Clearing NVS...");

                // Clear all NVS namespaces
                nvs_wifi.begin(NVS_WIFI_NS, false);
                nvs_wifi.clear();
                nvs_wifi.end();

                nvs_syscfg.begin(NVS_SYSCFG_NS, false);
                nvs_syscfg.clear();
                nvs_syscfg.end();

                log_println("[I] NVS cleared. Rebooting in 2 seconds...");

                // Schedule reboot
                reboot_requested = true;
                reboot_timestamp = millis();
            }
            else if (command == "STATUS")
            {
                log_println("[I] Status requested");
                char msg[128];
                snprintf(msg, sizeof(msg), "[I] STATE=%d,WIFI=%d,OTA_MODE=%d,IP=%s,OFFSET=%+d",
                         g_state.system_state, g_state.wifi_state, ota_mode_active ? 1 : 0,
                         g_state.wifi_ip, currentOffset);
                log_println(msg);
            }
            else if (command == "OTA_MODE")
            {
                log_println("[I] OTA mode activation requested via BLE");
                ota_mode_active = true;
                log_println("[I] OTA mode activated - ready to receive firmware data");
            }
        }
    }
};

class ProvisioningCallbacks : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *pCharacteristic)
    {
        // Check if WiFi/OTA timeout has passed
        if (wifi_ota_timeout_passed)
        {
            log_println("[W] WiFi provisioning disabled after 60s timeout");
            return;
        }

        // Set flag to suppress BLE log output during provisioning
        provisioning_in_progress = true;

        std::string rxValue = pCharacteristic->getValue();
        if (rxValue.length() == 0)
        {
            log_println("[E] Empty provisioning data");
            provisioning_in_progress = false;
            return;
        }

        // Format: SSID\nPassword (separated by newline)
        String data = String(rxValue.c_str());
        int separatorIndex = data.indexOf('\n');

        if (separatorIndex == -1)
        {
            log_println("[E] Invalid provisioning format (no separator)");
            provisioning_in_progress = false;
            return;
        }

        String ssid = data.substring(0, separatorIndex);
        String password = data.substring(separatorIndex + 1);

        if (ssid.length() == 0 || ssid.length() > WIFI_SSID_MAX)
        {
            log_println("[E] Invalid SSID length");
            provisioning_in_progress = false;
            return;
        }

        if (password.length() > WIFI_PASS_MAX)
        {
            log_println("[E] Invalid password length");
            provisioning_in_progress = false;
            return;
        }

        log_println("[I] Received Wi-Fi credentials via BLE");

        // Log SSID and lengths (Serial only during provisioning)
        char ssid_info[128];
        snprintf(ssid_info, sizeof(ssid_info), "[I] SSID: %s", ssid.c_str());
        log_println(ssid_info);

        char len_info[64];
        snprintf(len_info, sizeof(len_info), "[I] SSID length: %d", ssid.length());
        log_println(len_info);

        snprintf(len_info, sizeof(len_info), "[I] Password length: %d", password.length());
        log_println(len_info);

        // Save to NVS
        nvs_wifi.begin(NVS_WIFI_NS, false);
        nvs_wifi.putString("ssid", ssid.c_str());
        nvs_wifi.putString("pass", password.c_str());
        nvs_wifi.end();

        // Verify what was saved
        char verify_ssid[WIFI_SSID_MAX] = {0};
        nvs_wifi.begin(NVS_WIFI_NS, true);
        size_t verify_len = nvs_wifi.getString("ssid", verify_ssid, sizeof(verify_ssid));
        nvs_wifi.end();

        char verify_info[128];
        snprintf(verify_info, sizeof(verify_info), "[I] Verified saved SSID: %s", verify_ssid);
        log_println(verify_info);

        snprintf(verify_info, sizeof(verify_info), "[I] Verified SSID length: %d", verify_len);
        log_println(verify_info);

        // Mark as provisioned
        nvs_syscfg.begin(NVS_SYSCFG_NS, false);
        nvs_syscfg.putUChar("prov", 1);
        nvs_syscfg.end();

        log_println("[I] Wi-Fi config saved! Device will reboot in 2 seconds...");

        // Clear flag to allow final log messages to be sent via BLE
        provisioning_in_progress = false;

        // Request reboot (will be executed in main loop after callback returns)
        // This ensures BLE write response is sent back to client before reboot
        reboot_requested = true;
        reboot_timestamp = millis();

        log_println("[I] Reboot scheduled...");
    }
};

// =============================================================================
// BLE OTA Callbacks
// =============================================================================

class OtaControlCallbacks : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *pCharacteristic)
    {
        std::string rxValue = pCharacteristic->getValue();
        if (rxValue.length() == 0)
        {
            log_println("[E] Empty OTA control data");
            return;
        }

        String command = String(rxValue.c_str());
        command.trim();

        String msg = "[OTA] Control command: " + command;
        log_println(msg.c_str());

        // Check if WiFi/OTA timeout has passed
        // Allow END/ABORT for in-progress session even after timeout
        bool is_end_or_abort = (command == "END" || command == "ABORT");
        if (wifi_ota_timeout_passed && !(is_end_or_abort && ota_in_progress))
        {
            log_println("[W] OTA mode disabled after 60s timeout");
            if (pOtaStatus)
            {
                pOtaStatus->setValue("ERROR:TIMEOUT");
                pOtaStatus->notify();
            }
            return;
        }

        // Format: START:<size> or END
        if (command.startsWith("START:"))
        {
            size_t size = command.substring(6).toInt();
            if (size == 0 || size > 2000000) // Max 2MB
            {
                log_println("[E] Invalid OTA size");
                if (pOtaStatus)
                {
                    pOtaStatus->setValue("ERROR:INVALID_SIZE");
                    pOtaStatus->notify();
                }
                return;
            }

            log_println("[OTA] Starting OTA update...");
            Serial.printf("[OTA] Expected size: %u bytes\n", size);

            ota_expected_size = size;
            ota_received_size = 0;
            ota_last_reported_size = 0;
            ota_in_progress = true;
            ota_finalize_requested = false;
            ota_abort_requested = false;

            if (!Update.begin(size, U_FLASH))
            {
                Update.printError(Serial);
                log_println("[E] Update.begin() failed");
                ota_in_progress = false;
                if (pOtaStatus)
                {
                    pOtaStatus->setValue("ERROR:BEGIN_FAILED");
                    pOtaStatus->notify();
                }
                return;
            }

            log_println("[I] OTA update started successfully");
            if (pOtaStatus)
            {
                pOtaStatus->setValue("READY");
                pOtaStatus->notify();
            }
        }
        else if (command == "END")
        {
            if (!ota_in_progress)
            {
                log_println("[E] OTA not in progress");
                if (pOtaStatus)
                {
                    pOtaStatus->setValue("ERROR:NOT_STARTED");
                    pOtaStatus->notify();
                }
                return;
            }

            if (ota_received_size != ota_expected_size)
            {
                char err[64];
                snprintf(err, sizeof(err), "[E] OTA incomplete: %u / %u", ota_received_size, ota_expected_size);
                log_println(err);
                if (pOtaStatus)
                {
                    pOtaStatus->setValue("ERROR:INCOMPLETE");
                    pOtaStatus->notify();
                }
                return;
            }

            log_println("[OTA] Finalize requested - will process in main loop");
            ota_finalize_requested = true;
        }
        else if (command == "ABORT")
        {
            log_println("[W] OTA abort requested by user");
            ota_abort_requested = true;
        }
    }
};

class OtaDataCallbacks : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *pCharacteristic)
    {
        if (!ota_in_progress)
        {
            log_println("[E] OTA not started, ignoring data");
            return;
        }

        std::string rxValue = pCharacteristic->getValue();
        size_t len = rxValue.length();

        if (len == 0)
        {
            log_println("[E] Empty OTA data packet");
            return;
        }

        if (ota_received_size + len > ota_expected_size)
        {
            log_println("[E] OTA data overflow (received more than expected)");
            Update.abort();
            ota_in_progress = false;
            ota_mode_active = false;

            if (pOtaStatus)
            {
                pOtaStatus->setValue("ERROR:OVERFLOW");
                pOtaStatus->notify();
            }
            return;
        }

        // Write data to flash
        size_t written = Update.write((uint8_t *)rxValue.data(), len);
        if (written != len)
        {
            Update.printError(Serial);
            log_println("[E] OTA write failed");
            Update.abort();
            ota_in_progress = false;

            if (pOtaStatus)
            {
                pOtaStatus->setValue("ERROR:WRITE_FAILED");
                pOtaStatus->notify();
            }
            return;
        }

        ota_received_size += written;

        // Progress notification every 100KB or at completion (reduce overhead)
        if (ota_received_size - ota_last_reported_size >= 102400 || ota_received_size == ota_expected_size)
        {
            ota_last_reported_size = ota_received_size;
            Serial.printf("[OTA] Progress: %u / %u bytes (%.1f%%)\n",
                          ota_received_size, ota_expected_size,
                          (ota_received_size * 100.0) / ota_expected_size);

            // Only notify progress occasionally to reduce BLE stack load
            if (pOtaStatus && (ota_received_size % 204800 == 0 || ota_received_size == ota_expected_size))
            {
                char progress[32];
                snprintf(progress, sizeof(progress), "PROGRESS:%u/%u",
                         ota_received_size, ota_expected_size);
                pOtaStatus->setValue(progress);
                pOtaStatus->notify();
            }
        }
    }
};

// =============================================================================
// BLE Setup
// =============================================================================

void setup_ble_debug_service(void)
{
    BLEService *pService = pServer->createService(DEBUG_SERVICE_UUID);

    // DebugLogTx (Notify)
    pDebugLogTx = pService->createCharacteristic(
        DEBUG_LOG_TX_UUID,
        BLECharacteristic::PROPERTY_NOTIFY);
    pDebugLogTx->addDescriptor(new BLE2902());

    // DebugCmdRx (Write)
    pDebugCmdRx = pService->createCharacteristic(
        DEBUG_CMD_RX_UUID,
        BLECharacteristic::PROPERTY_WRITE |
            BLECharacteristic::PROPERTY_WRITE_NR);
    pDebugCmdRx->setCallbacks(new MyCharacteristicCallbacks());

    // DebugStat (Read/Notify)
    pDebugStat = pService->createCharacteristic(
        DEBUG_STAT_UUID,
        BLECharacteristic::PROPERTY_READ |
            BLECharacteristic::PROPERTY_NOTIFY);
    pDebugStat->addDescriptor(new BLE2902());

    pService->start();
}

void setup_ble_provisioning_service(void)
{
    BLEService *pProvService = pServer->createService(PROV_SERVICE_UUID);

    // WiFi Config (Write)
    pProvWifiConfig = pProvService->createCharacteristic(
        PROV_WIFI_CONFIG_UUID,
        BLECharacteristic::PROPERTY_WRITE |
            BLECharacteristic::PROPERTY_WRITE_NR);
    pProvWifiConfig->setCallbacks(new ProvisioningCallbacks());

    pProvService->start();
    log_println("[I] BLE Provisioning service started");
}

void setup_ble_ota_service(void)
{
    BLEService *pOtaService = pServer->createService(OTA_SERVICE_UUID);

    // OTA Control (Write) - for START, END, ABORT commands
    pOtaControl = pOtaService->createCharacteristic(
        OTA_CONTROL_UUID,
        BLECharacteristic::PROPERTY_WRITE |
            BLECharacteristic::PROPERTY_WRITE_NR);
    pOtaControl->setCallbacks(new OtaControlCallbacks());

    // OTA Data (Write) - for firmware binary data
    pOtaData = pOtaService->createCharacteristic(
        OTA_DATA_UUID,
        BLECharacteristic::PROPERTY_WRITE |
            BLECharacteristic::PROPERTY_WRITE_NR);
    pOtaData->setCallbacks(new OtaDataCallbacks());
    pOtaData->setValue((uint8_t *)"", 0); // Initialize empty

    // OTA Status (Read/Notify) - for progress and status updates
    pOtaStatus = pOtaService->createCharacteristic(
        OTA_STATUS_UUID,
        BLECharacteristic::PROPERTY_READ |
            BLECharacteristic::PROPERTY_NOTIFY);
    pOtaStatus->addDescriptor(new BLE2902());
    pOtaStatus->setValue("IDLE");

    pOtaService->start();
    log_println("[I] BLE OTA service started");
}

void init_ble(void)
{
    log_println("[I] Starting BLE device init...");
    BLEDevice::init("ESP32-S3-MICON");

    // Request larger MTU for better OTA throughput
    BLEDevice::setMTU(517);

    log_println("[I] BLE device initialized");

    delay(100);

    log_println("[I] Creating BLE server...");
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new MyServerCallbacks());
    log_println("[I] BLE server created");

    log_println("[I] Setting up debug service...");
    setup_ble_debug_service();
    log_println("[I] Debug service ready");

    // Setup OTA service (always available)
    log_println("[I] Setting up OTA service...");
    setup_ble_ota_service();

    // Setup provisioning service (always available for WiFi re-provisioning during operation)
    log_println("[I] Setting up provisioning service...");
    setup_ble_provisioning_service();

    log_println("[I] Starting advertising...");
    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(DEBUG_SERVICE_UUID);
    pAdvertising->addServiceUUID(OTA_SERVICE_UUID);
    pAdvertising->addServiceUUID(PROV_SERVICE_UUID); // Always advertise provisioning service
    pAdvertising->setScanResponse(true);
    pAdvertising->setMinPreferred(0x06);
    pAdvertising->setMaxPreferred(0x12);
    BLEDevice::startAdvertising();

    log_println("[I] BLE initialized successfully");
}

// =============================================================================
// Factory Reset / NVS Management
// =============================================================================

void config_store_init(void)
{
    nvs_wifi.begin(NVS_WIFI_NS, false);
    nvs_syscfg.begin(NVS_SYSCFG_NS, false);
}

void config_store_check_provisioned(void)
{
    nvs_wifi.begin(NVS_WIFI_NS, true);
    uint8_t is_provisioned = nvs_wifi.getUChar("prov", 0);
    nvs_wifi.end();

    if (is_provisioned)
    {
        log_println("[I] Wi-Fi config found, entering APP mode");
        g_state.system_state = STATE_APP_RUNNING;
    }
    else
    {
        log_println("[I] No Wi-Fi config, entering PROVISIONING mode");
        g_state.system_state = STATE_PROVISIONING;
    }
}

void factory_reset_check(void)
{
    // Simplified: Check if BOOT button held for 3 seconds
    // In real implementation, use GPIO interrupt
    // For now, just check a flag in preferences

    nvs_syscfg.begin(NVS_SYSCFG_NS, true);
    uint8_t factory_reset_flag = nvs_syscfg.getUChar("factory_reset", 0);
    nvs_syscfg.end();

    if (factory_reset_flag)
    {
        log_println("[W] Factory reset triggered!");
        nvs_wifi.begin(NVS_WIFI_NS, false);
        nvs_wifi.clear();
        nvs_wifi.end();

        nvs_syscfg.begin(NVS_SYSCFG_NS, false);
        nvs_syscfg.putUChar("factory_reset", 0);
        nvs_syscfg.end();

        log_println("[I] NVS cleared, rebooting...");
        delay(1000);
        ESP.restart();
    }
}

// =============================================================================
// Wi-Fi Event Handler
// =============================================================================

void wifi_event_handler(WiFiEvent_t event)
{
    switch (event)
    {
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
        log_println("[I] Wi-Fi connected");
        break;

    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
    {
        g_state.wifi_state = WIFI_CONNECTED;
        IPAddress ip = WiFi.localIP();
        snprintf(g_state.wifi_ip, sizeof(g_state.wifi_ip), "%d.%d.%d.%d",
                 ip[0], ip[1], ip[2], ip[3]);

        char msg[64];
        snprintf(msg, sizeof(msg), "[I] Got IP: %s", g_state.wifi_ip);
        log_println(msg);

        // Start NTP synchronization after WiFi is connected
        setupNTP();

        // If in provisioning mode, mark as provisioned
        if (g_state.system_state == STATE_PROVISIONING)
        {
            nvs_wifi.begin(NVS_WIFI_NS, false);
            nvs_wifi.putUChar("prov", 1);
            nvs_wifi.end();

            log_println("[I] WiFi provisioned successfully");
            g_state.system_state = STATE_APP_RUNNING;
        }
        break;
    }

    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
    {
        g_state.wifi_state = WIFI_FAILED;

        // Get detailed disconnect reason
        char reason_msg[128];
        snprintf(reason_msg, sizeof(reason_msg),
                 "[W] Wi-Fi disconnected (status=%d)", WiFi.status());
        log_println(reason_msg);

        // Additional debug info
        if (WiFi.status() == WL_NO_SSID_AVAIL)
        {
            log_println("[E] SSID not found - check if SSID is correct");
        }
        else if (WiFi.status() == WL_CONNECT_FAILED)
        {
            log_println("[E] Connection failed - check password");
        }
        break;
    }

    default:
        break;
    }
}

// =============================================================================
// Setup
// =============================================================================

void setup()
{
    boot_timestamp = millis(); // Record boot time for power-saving mode

    Serial.begin(SERIAL_BAUD);
    delay(500);

    // Boot sequence with repeated messages - allows time to catch output after USB reconnect
    Serial.println("\n\n=== ESP32-S3 BOOT SEQUENCE STARTING ===");
    Serial.println("=== Waiting 5 seconds for monitor to connect... ===\n");

    for (int i = 5; i > 0; i--)
    {
        Serial.print("[BOOT] ");
        Serial.print(i);
        Serial.println(" seconds until initialization continues...");
        delay(1000);
    }

    Serial.println("\n=== Proceeding with initialization ===\n");

    // Direct output to confirm serial is working
    Serial.println("=== ESP32-S3 Booting ===");
    Serial.println("=== If you see this, application started! ===");

#ifdef LOG_SERIAL_ENABLED
    Serial.println("LOG_SERIAL_ENABLED is defined");
#else
    Serial.println("WARNING: LOG_SERIAL_ENABLED is NOT defined");
#endif

    log_println("\n\n[System] ESP32-S3 Starting...");
    log_println("[Version] FW v1.0.0");

    // Initialize components - add checkpoint logging
    Serial.println("[CHECKPOINT] Calling config_store_init...");
    config_store_init();
    Serial.println("[CHECKPOINT] config_store_init done");

    Serial.println("[CHECKPOINT] Calling factory_reset_check...");
    factory_reset_check();
    Serial.println("[CHECKPOINT] factory_reset_check done");

    Serial.println("[CHECKPOINT] Calling config_store_check_provisioned...");
    config_store_check_provisioned();
    Serial.println("[CHECKPOINT] config_store_check_provisioned done");

    log_println("[Setup] Initializing WiFi...");
    wifi_mgr_init();

    // Setup status LED
    status_led_init();

    delay(500); // Give time for WiFi stack to initialize

    log_println("[Setup] Initializing BLE...");
    init_ble();

    delay(500); // Give time for BLE stack to initialize

    // WiFi event handler
    WiFi.onEvent(wifi_event_handler);

    snprintf(g_state.device_name, sizeof(g_state.device_name), "ESP32-S3-SUPERMINI");

    log_println("[Setup] Initialization complete");
    log_println("[Info] Waiting for BLE provisioning or app commands...");
}

// =============================================================================
// Loop
// =============================================================================

void loop()
{
    // Handle reboot request (e.g., after WiFi provisioning)
    if (reboot_requested)
    {
        unsigned long elapsed = millis() - reboot_timestamp;
        if (elapsed >= REBOOT_DELAY_MS)
        {
            log_println("[I] Rebooting now...");
            delay(100); // Give time for final log to be sent
            ESP.restart();
        }
        // Don't process other operations while reboot is pending
        return;
    }

    // Handle OTA finalization request (moved from BLE callback to avoid stack issues)
    if (ota_finalize_requested)
    {
        ota_finalize_requested = false;

        log_println("[OTA] Finalizing update...");
        Serial.printf("[OTA] Received: %u bytes / Expected: %u bytes\n", ota_received_size, ota_expected_size);

        if (Update.end(true)) // true = do checksum validation
        {
            Serial.printf("[OTA] Update Success: %u bytes\n", ota_received_size);
            log_println("[I] OTA update successful!");
            ota_in_progress = false;
            ota_mode_active = false;

            if (pOtaStatus)
            {
                pOtaStatus->setValue("SUCCESS");
                pOtaStatus->notify();
            }

            delay(1000);
            log_println("[I] Rebooting...");
            delay(500);
            ESP.restart();
        }
        else
        {
            Serial.println("\n=== Update.end() FAILED ===");
            Serial.printf("[OTA] ota_received_size = %u\n", ota_received_size);
            Serial.printf("[OTA] ota_expected_size = %u\n", ota_expected_size);
            Update.printError(Serial);
            log_println("[E] Update.end() failed");
            ota_in_progress = false;

            if (pOtaStatus)
            {
                pOtaStatus->setValue("ERROR:END_FAILED");
                pOtaStatus->notify();
            }
        }
    }

    // Handle OTA abort request
    if (ota_abort_requested)
    {
        ota_abort_requested = false;
        log_println("[W] OTA aborted by user");
        if (ota_in_progress)
        {
            Update.abort();
            ota_in_progress = false;
        }
        ota_mode_active = false;

        if (pOtaStatus)
        {
            pOtaStatus->setValue("ABORTED");
            pOtaStatus->notify();
        }
    }

    // Check if WiFi/OTA timeout has passed (60 seconds after boot)
    if (!wifi_ota_timeout_passed && (millis() - boot_timestamp >= WIFI_OTA_TIMEOUT_MS))
    {
        // Do not interrupt ongoing OTA write. Defer timeout activation.
        if (ota_in_progress)
        {
            if (!wifi_ota_timeout_deferred_logged)
            {
                log_println("[I] OTA timeout deferred while write is in progress");
                wifi_ota_timeout_deferred_logged = true;
            }
        }
        else
        {
            wifi_ota_timeout_passed = true;
            log_println("[I] === OTA timeout activated ===");
            log_println("[I] OTA and WiFi provisioning disabled after 60s");
            log_println("[I] WiFi connection will be maintained");

            // Disable OTA mode if active (only when not writing)
            if (ota_mode_active)
            {
                log_println("[W] Disabling OTA mode (timeout)");
                ota_mode_active = false;
            }
        }
    }

    // If OTA mode is active, stop normal app operation
    if (ota_mode_active)
    {
        // Only handle BLE and OTA processing
        delay(10); // Reduced delay for faster response
        return;
    }

    // Wi-Fi state monitoring and auto-reconnect management
    static unsigned long last_wifi_check = 0;
    static unsigned long last_wifi_reconnect_try = 0;
    static unsigned long wifi_connect_start_time = 0;

    if (millis() - last_wifi_check > 5000) // Check WiFi state every 5 seconds
    {
        last_wifi_check = millis();

        if (g_state.wifi_state == WIFI_CONNECTING)
        {
            if (WiFi.status() == WL_CONNECTED)
            {
                // Will be handled by event handler
            }
            else
            {
                // Check for connection timeout (30 seconds)
                if (wifi_connect_start_time > 0 &&
                    (millis() - wifi_connect_start_time > 30000))
                {
                    log_println("[E] WiFi connection timeout - marking as failed");
                    g_state.wifi_state = WIFI_FAILED;
                    wifi_connect_start_time = 0;
                    WiFi.disconnect();
                }
            }
        }

        // Auto-reconnect: if WiFi config exists but not connected, try to connect
        if ((g_state.wifi_state == WIFI_IDLE || g_state.wifi_state == WIFI_FAILED) &&
            (millis() - last_wifi_reconnect_try > 30000)) // Retry every 30 seconds
        {
            char ssid[WIFI_SSID_MAX] = {0};
            nvs_wifi.begin(NVS_WIFI_NS, true);
            size_t ssid_len = nvs_wifi.getString("ssid", ssid, sizeof(ssid));
            nvs_wifi.end();

            if (ssid_len > 0) // WiFi config exists
            {
                log_println("[I] Loop: WiFi config found, initiating connection...");
                last_wifi_reconnect_try = millis();
                wifi_connect_start_time = millis();
                wifi_mgr_connect();
            }
        }
        else if (g_state.wifi_state == WIFI_CONNECTING && wifi_connect_start_time == 0)
        {
            // Initialize connection start time if not set
            wifi_connect_start_time = millis();
        }
    }

    // BLE Output: Broadcast current time with offset via BLE every 5 seconds
    static unsigned long last_broadcast = 0;
    if (millis() - last_broadcast >= BROADCAST_INTERVAL_MS)
    {
        last_broadcast = millis();
        updateBroadcast();
        offsetChanged = false;

        // Blink status LED when broadcasting
        status_led_blink_aws();
    }

    // Every 10 seconds, update BLE debug stat
    static unsigned long last_stat_update = 0;
    if (millis() - last_stat_update > 10000)
    {
        last_stat_update = millis();

        if (ble_device_connected && pDebugStat)
        {
            char stat_str[128];
            snprintf(stat_str, sizeof(stat_str),
                     "STATE:BLE=%d,WIFI=%d,OTA_MODE=%d,IP=%s,OFFSET=%+d",
                     ble_device_connected ? 1 : 0,
                     g_state.wifi_state,
                     ota_mode_active ? 1 : 0,
                     g_state.wifi_ip,
                     currentOffset);
            pDebugStat->setValue((uint8_t *)stat_str, strlen(stat_str));
            pDebugStat->notify();
        }
    }

    delay(100);
}
