/*
 * Physalix Spectrophotometer firmware
 * Target: official Arduino Nano A000005 / ATmega328P, 5 V, 16 MHz
 * Sensor: Adafruit AS7341 at I2C address 0x39
 * External white LED: D3 PWM through a 220-ohm series resistor
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_AS7341.h>

#include "firmware_metadata.h"

namespace {

constexpr uint8_t MAGIC_0 = 0xA5;
constexpr uint8_t MAGIC_1 = 0x5A;
constexpr uint8_t PROTOCOL_VERSION = PHYSALIX_SPECTRO_PROTOCOL_VERSION;
constexpr uint16_t MAX_WIRE_PAYLOAD = 512;
constexpr uint8_t RX_PAYLOAD_CAPACITY = 7;
constexpr uint32_t BAUD_RATE = 115200;

constexpr uint8_t SENSOR_ADDRESS = 0x39;
constexpr uint8_t SENSOR_TYPE = PHYSALIX_SPECTRO_SENSOR_AS7341;
constexpr uint8_t LED_PIN = 3;
constexpr uint32_t I2C_TIMEOUT_US = 25000UL;
constexpr uint32_t MEASUREMENT_TIMEOUT_MARGIN_MS = 2500UL;

constexpr uint8_t FIRMWARE_MAJOR = PHYSALIX_SPECTRO_FIRMWARE_VERSION_MAJOR;
constexpr uint8_t FIRMWARE_MINOR = PHYSALIX_SPECTRO_FIRMWARE_VERSION_MINOR;
constexpr uint8_t FIRMWARE_PATCH = PHYSALIX_SPECTRO_FIRMWARE_VERSION_PATCH;
constexpr uint32_t CAPABILITIES = PHYSALIX_SPECTRO_CAPABILITIES;

constexpr uint8_t HELLO_SIZE = 0;
constexpr uint8_t HELLO_ACK_SIZE = 12;
constexpr uint8_t CONFIG_SIZE = 7;
constexpr uint8_t MEASURE_SIZE = 5;
constexpr uint8_t DATA_SIZE = 31;
constexpr uint8_t ERROR_SIZE = 3;
constexpr uint8_t STOP_SIZE = 2;
constexpr uint8_t AS7341_READING_COUNT = 12;
constexpr uint8_t AS7341_MAX_GAIN_CODE = 10;
constexpr uint16_t AS7341_RESERVED_ASTEP = 0xFFFF;

enum MessageType : uint8_t {
  SPECTRO_HELLO = 32,
  SPECTRO_HELLO_ACK = 33,
  SPECTRO_CONFIG = 34,
  SPECTRO_CONFIG_ACK = 35,
  SPECTRO_MEASURE = 36,
  SPECTRO_DATA = 37,
  SPECTRO_ERROR = 38,
  SPECTRO_STOP = 39,
  SPECTRO_STOP_ACK = 40,
};

enum ErrorCode : uint8_t {
  ERR_PROTOCOL_VERSION = 1,
  ERR_INVALID_PAYLOAD = 2,
  ERR_UNKNOWN_COMMAND = 3,
  ERR_INVALID_CONFIG = 4,
  ERR_SENSOR_UNAVAILABLE = 5,
  ERR_CONFIG_APPLY_FAILED = 6,
  ERR_CONFIG_MISMATCH = 7,
  ERR_BUSY = 8,
  ERR_MEASUREMENT_START = 9,
  ERR_MEASUREMENT_TIMEOUT = 10,
  ERR_I2C = 11,
  ERR_CRC = 12,
  ERR_FRAME_TOO_LARGE = 13,
};

enum MeasurementState : uint8_t {
  MEASUREMENT_IDLE,
  MEASUREMENT_RUNNING,
};

struct SpectroConfig {
  uint16_t configId;
  uint8_t atime;
  uint16_t astep;
  uint8_t gainCode;
  uint8_t ledPwm;
};

Adafruit_AS7341 sensor;
bool sensorReady = false;
bool hasConfig = false;
SpectroConfig activeConfig{};
MeasurementState measurementState = MEASUREMENT_IDLE;
uint16_t activeRequestId = 0;
uint8_t activeIllumination = 0;
uint32_t measurementStartedMs = 0;
uint32_t measurementTimeoutMs = 0;
uint8_t rxPayload[RX_PAYLOAD_CAPACITY];

uint16_t crcUpdate(uint16_t crc, uint8_t value) {
  crc ^= static_cast<uint16_t>(value) << 8;
  for (uint8_t bit = 0; bit < 8; ++bit) {
    crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021)
                         : static_cast<uint16_t>(crc << 1);
  }
  return crc;
}

uint16_t crcBytes(uint16_t crc, const uint8_t *data, uint16_t length) {
  while (length-- != 0) {
    crc = crcUpdate(crc, *data++);
  }
  return crc;
}

uint16_t readU16(const uint8_t *data) {
  return static_cast<uint16_t>(data[0]) |
         (static_cast<uint16_t>(data[1]) << 8);
}

void writeU16(uint8_t *data, uint16_t value) {
  data[0] = static_cast<uint8_t>(value);
  data[1] = static_cast<uint8_t>(value >> 8);
}

void writeU32(uint8_t *data, uint32_t value) {
  data[0] = static_cast<uint8_t>(value);
  data[1] = static_cast<uint8_t>(value >> 8);
  data[2] = static_cast<uint8_t>(value >> 16);
  data[3] = static_cast<uint8_t>(value >> 24);
}

void setLedOff() {
  analogWrite(LED_PIN, 0);
  digitalWrite(LED_PIN, LOW);
}

void sendFrame(uint8_t type, const uint8_t *payload, uint16_t length) {
  const uint8_t header[4] = {
    PROTOCOL_VERSION,
    type,
    static_cast<uint8_t>(length),
    static_cast<uint8_t>(length >> 8),
  };
  uint16_t crc = crcBytes(0xFFFF, header, sizeof(header));
  crc = crcBytes(crc, payload, length);
  const uint8_t magic[2] = {MAGIC_0, MAGIC_1};
  const uint8_t crcWire[2] = {
    static_cast<uint8_t>(crc), static_cast<uint8_t>(crc >> 8),
  };
  Serial.write(magic, sizeof(magic));
  Serial.write(header, sizeof(header));
  if (length != 0) {
    Serial.write(payload, length);
  }
  Serial.write(crcWire, sizeof(crcWire));
}

void sendError(uint16_t requestId, ErrorCode code) {
  uint8_t payload[ERROR_SIZE];
  writeU16(payload, requestId);
  payload[2] = static_cast<uint8_t>(code);
  sendFrame(SPECTRO_ERROR, payload, sizeof(payload));
}

bool i2cTimedOut() {
  if (Wire.getWireTimeoutFlag()) {
    Wire.clearWireTimeoutFlag();
    return true;
  }
  return false;
}

bool sensorResponds() {
  Wire.beginTransmission(SENSOR_ADDRESS);
  const bool responds = Wire.endTransmission() == 0;
  return responds && !i2cTimedOut();
}

bool initializeSensor() {
  setLedOff();
  sensorReady = sensor.begin(SENSOR_ADDRESS, &Wire);
  if (i2cTimedOut()) {
    sensorReady = false;
  }
  return sensorReady;
}

void sendHelloAck() {
  uint8_t payload[HELLO_ACK_SIZE] = {
    'S', 'P', 'C', 'T',
    FIRMWARE_MAJOR, FIRMWARE_MINOR, FIRMWARE_PATCH,
    SENSOR_TYPE,
    0, 0, 0, 0,
  };
  writeU32(payload + 8, CAPABILITIES);
  sendFrame(SPECTRO_HELLO_ACK, payload, sizeof(payload));
}

bool decodeConfig(const uint8_t *payload, uint16_t length,
                  SpectroConfig &candidate) {
  if (length != CONFIG_SIZE) {
    return false;
  }
  candidate.configId = readU16(payload);
  candidate.atime = payload[2];
  candidate.astep = readU16(payload + 3);
  candidate.gainCode = payload[5];
  candidate.ledPwm = payload[6];
  return candidate.astep != AS7341_RESERVED_ASTEP &&
         candidate.gainCode <= AS7341_MAX_GAIN_CODE;
}

bool applySensorConfig(const SpectroConfig &config) {
  if (!sensorReady && !initializeSensor()) {
    return false;
  }
  const bool written = sensor.setATIME(config.atime) &&
                       sensor.setASTEP(config.astep) &&
                       sensor.setGain(static_cast<as7341_gain_t>(config.gainCode));
  if (!written || i2cTimedOut()) {
    sensorReady = false;
    return false;
  }
  const bool verified = sensor.getATIME() == config.atime &&
                        sensor.getASTEP() == config.astep &&
                        static_cast<uint8_t>(sensor.getGain()) == config.gainCode;
  if (!verified || i2cTimedOut() || !sensorResponds()) {
    sensorReady = false;
    return false;
  }
  return true;
}

void sendConfigAck(const SpectroConfig &config) {
  uint8_t payload[CONFIG_SIZE];
  writeU16(payload, config.configId);
  payload[2] = config.atime;
  writeU16(payload + 3, config.astep);
  payload[5] = config.gainCode;
  payload[6] = config.ledPwm;
  sendFrame(SPECTRO_CONFIG_ACK, payload, sizeof(payload));
}

uint32_t computeMeasurementTimeoutMs(const SpectroConfig &config) {
  const uint64_t cycles = static_cast<uint64_t>(config.atime + 1UL) *
                          static_cast<uint64_t>(config.astep + 1UL);
  // Two successive SMUX groups, 2.78 us per integration cycle, rounded up.
  const uint64_t integrationMs = (cycles * 2ULL * 278ULL + 99999ULL) / 100000ULL;
  const uint64_t timeout = integrationMs + MEASUREMENT_TIMEOUT_MARGIN_MS;
  return timeout > 0xFFFFFFFFULL ? 0xFFFFFFFFUL : static_cast<uint32_t>(timeout);
}

uint16_t adcFullScale(const SpectroConfig &config) {
  const uint32_t fullScale = static_cast<uint32_t>(config.atime + 1UL) *
                             static_cast<uint32_t>(config.astep + 1UL);
  return fullScale > 65535UL ? 65535U : static_cast<uint16_t>(fullScale);
}

void cancelMeasurement(bool disableSensor) {
  setLedOff();
  if (disableSensor && sensorReady) {
    sensor.enableSpectralMeasurement(false);
    if (i2cTimedOut()) {
      sensorReady = false;
    }
  }
  measurementState = MEASUREMENT_IDLE;
  activeRequestId = 0;
  activeIllumination = 0;
}

void sendStopAck(uint16_t requestId) {
  uint8_t payload[STOP_SIZE];
  writeU16(payload, requestId);
  sendFrame(SPECTRO_STOP_ACK, payload, sizeof(payload));
}

void startMeasurement(uint16_t requestId, uint8_t illumination) {
  activeRequestId = requestId;
  activeIllumination = illumination;
  if (illumination == 0) {
    setLedOff();
  } else {
    analogWrite(LED_PIN, activeConfig.ledPwm);
  }

  if (!sensor.startReading() || i2cTimedOut()) {
    setLedOff();
    sensorReady = false;
    activeRequestId = 0;
    activeIllumination = 0;
    sendError(requestId, ERR_MEASUREMENT_START);
    return;
  }
  measurementStartedMs = millis();
  measurementTimeoutMs = computeMeasurementTimeoutMs(activeConfig);
  measurementState = MEASUREMENT_RUNNING;
}

void sendData(const uint16_t readings[AS7341_READING_COUNT], uint32_t timestampMs) {
  // Adafruit buffer: F1..F4 at 0..3, duplicate Clear/NIR at 4..5,
  // F5..F8 at 6..9, and the final Clear/NIR pair at 10..11.
  const uint8_t sourceIndices[10] = {0, 1, 2, 3, 6, 7, 8, 9, 10, 11};
  uint8_t payload[DATA_SIZE];
  writeU16(payload, activeRequestId);
  writeU16(payload + 2, activeConfig.configId);
  payload[4] = activeIllumination;

  const uint16_t fullScale = adcFullScale(activeConfig);
  uint16_t saturationFlags = 0;
  for (uint8_t channel = 0; channel < 10; ++channel) {
    const uint16_t value = readings[sourceIndices[channel]];
    writeU16(payload + 5 + 2 * channel, value);
    if (value >= fullScale) {
      saturationFlags |= static_cast<uint16_t>(1U << channel);
    }
  }
  writeU16(payload + 25, saturationFlags);
  writeU32(payload + 27, timestampMs);
  sendFrame(SPECTRO_DATA, payload, sizeof(payload));
}

void serviceMeasurement() {
  if (measurementState != MEASUREMENT_RUNNING) {
    return;
  }

  if (sensor.checkReadingProgress()) {
    // Les deux groupes viennent d'être acquis : dater et éteindre sans attendre
    // les contrôles I2C et la sérialisation de la réponse.
    const uint32_t timestampMs = millis();
    setLedOff();
    if (i2cTimedOut() || !sensorResponds()) {
      const uint16_t requestId = activeRequestId;
      sensorReady = false;
      cancelMeasurement(false);
      sendError(requestId, ERR_I2C);
      return;
    }
    uint16_t readings[AS7341_READING_COUNT];
    if (!sensor.getAllChannels(readings)) {
      const uint16_t requestId = activeRequestId;
      cancelMeasurement(true);
      sendError(requestId, ERR_I2C);
      return;
    }
    sendData(readings, timestampMs);
    measurementState = MEASUREMENT_IDLE;
    activeRequestId = 0;
    activeIllumination = 0;
    return;
  }

  if (i2cTimedOut()) {
    const uint16_t requestId = activeRequestId;
    sensorReady = false;
    cancelMeasurement(false);
    sendError(requestId, ERR_I2C);
    return;
  }
  if (static_cast<uint32_t>(millis() - measurementStartedMs) > measurementTimeoutMs) {
    const uint16_t requestId = activeRequestId;
    cancelMeasurement(true);
    sendError(requestId, ERR_MEASUREMENT_TIMEOUT);
  }
}

void handleFrame(uint8_t version, uint8_t type,
                 const uint8_t *payload, uint16_t length) {
  if (version != PROTOCOL_VERSION) {
    sendError(0, ERR_PROTOCOL_VERSION);
    return;
  }

  if (type == SPECTRO_HELLO) {
    if (length != HELLO_SIZE) {
      sendError(0, ERR_INVALID_PAYLOAD);
    } else {
      sendHelloAck();
    }
    return;
  }

  if (type == SPECTRO_CONFIG) {
    if (measurementState != MEASUREMENT_IDLE) {
      sendError(0, ERR_BUSY);
      return;
    }
    SpectroConfig candidate{};
    if (!decodeConfig(payload, length, candidate)) {
      sendError(0, length == CONFIG_SIZE ? ERR_INVALID_CONFIG : ERR_INVALID_PAYLOAD);
      return;
    }
    if (!sensorReady && !initializeSensor()) {
      sendError(0, ERR_SENSOR_UNAVAILABLE);
      return;
    }
    if (!applySensorConfig(candidate)) {
      sendError(0, ERR_CONFIG_APPLY_FAILED);
      return;
    }
    activeConfig = candidate;
    hasConfig = true;
    setLedOff();
    sendConfigAck(activeConfig);
    return;
  }

  if (type == SPECTRO_MEASURE) {
    const uint16_t requestId = length >= 2 ? readU16(payload) : 0;
    if (length != MEASURE_SIZE) {
      sendError(requestId, ERR_INVALID_PAYLOAD);
      return;
    }
    const uint16_t configId = readU16(payload + 2);
    const uint8_t illumination = payload[4];
    if (illumination > 1) {
      sendError(requestId, ERR_INVALID_PAYLOAD);
    } else if (measurementState != MEASUREMENT_IDLE) {
      sendError(requestId, ERR_BUSY);
    } else if (!hasConfig || configId != activeConfig.configId) {
      sendError(requestId, ERR_CONFIG_MISMATCH);
    } else if (!sensorReady || !sensorResponds()) {
      sensorReady = false;
      sendError(requestId, ERR_SENSOR_UNAVAILABLE);
    } else {
      startMeasurement(requestId, illumination);
    }
    return;
  }

  if (type == SPECTRO_STOP) {
    const uint16_t requestId = length >= 2 ? readU16(payload) : 0;
    if (length != STOP_SIZE) {
      sendError(requestId, ERR_INVALID_PAYLOAD);
      return;
    }
    cancelMeasurement(measurementState == MEASUREMENT_RUNNING);
    sendStopAck(requestId);
    return;
  }

  sendError(0, ERR_UNKNOWN_COMMAND);
}

class FrameReceiver {
 public:
  void feed(uint8_t value) {
    switch (phase_) {
      case WAIT_MAGIC_0:
        if (value == MAGIC_0) phase_ = WAIT_MAGIC_1;
        break;
      case WAIT_MAGIC_1:
        phase_ = value == MAGIC_1 ? READ_VERSION
                                  : (value == MAGIC_0 ? WAIT_MAGIC_1 : WAIT_MAGIC_0);
        break;
      case READ_VERSION:
        version_ = value;
        crc_ = crcUpdate(0xFFFF, value);
        phase_ = READ_TYPE;
        break;
      case READ_TYPE:
        type_ = value;
        crc_ = crcUpdate(crc_, value);
        phase_ = READ_LENGTH_0;
        break;
      case READ_LENGTH_0:
        length_ = value;
        crc_ = crcUpdate(crc_, value);
        phase_ = READ_LENGTH_1;
        break;
      case READ_LENGTH_1:
        length_ |= static_cast<uint16_t>(value) << 8;
        crc_ = crcUpdate(crc_, value);
        payloadIndex_ = 0;
        payloadFits_ = length_ <= RX_PAYLOAD_CAPACITY;
        if (length_ > MAX_WIRE_PAYLOAD) {
          sendError(0, ERR_FRAME_TOO_LARGE);
          reset(value);
        } else {
          phase_ = length_ == 0 ? READ_CRC_0 : READ_PAYLOAD;
        }
        break;
      case READ_PAYLOAD:
        if (payloadFits_) {
          rxPayload[payloadIndex_] = value;
        }
        ++payloadIndex_;
        crc_ = crcUpdate(crc_, value);
        if (payloadIndex_ == length_) phase_ = READ_CRC_0;
        break;
      case READ_CRC_0:
        receivedCrc_ = value;
        phase_ = READ_CRC_1;
        break;
      case READ_CRC_1:
        receivedCrc_ |= static_cast<uint16_t>(value) << 8;
        if (receivedCrc_ != crc_) {
          sendError(0, ERR_CRC);
        } else if (!payloadFits_) {
          sendError(0, ERR_INVALID_PAYLOAD);
        } else {
          handleFrame(version_, type_, rxPayload, length_);
        }
        reset(value);
        break;
    }
  }

 private:
  enum Phase : uint8_t {
    WAIT_MAGIC_0,
    WAIT_MAGIC_1,
    READ_VERSION,
    READ_TYPE,
    READ_LENGTH_0,
    READ_LENGTH_1,
    READ_PAYLOAD,
    READ_CRC_0,
    READ_CRC_1,
  };

  void reset(uint8_t lastByte) {
    phase_ = lastByte == MAGIC_0 ? WAIT_MAGIC_1 : WAIT_MAGIC_0;
    length_ = 0;
    payloadIndex_ = 0;
    payloadFits_ = true;
  }

  Phase phase_ = WAIT_MAGIC_0;
  uint8_t version_ = 0;
  uint8_t type_ = 0;
  uint16_t length_ = 0;
  uint16_t payloadIndex_ = 0;
  uint16_t crc_ = 0xFFFF;
  uint16_t receivedCrc_ = 0;
  bool payloadFits_ = true;
};

FrameReceiver receiver;

static_assert(HELLO_ACK_SIZE == 4 + 3 + 1 + 4, "HELLO_ACK layout");
static_assert(CONFIG_SIZE == 2 + 1 + 2 + 1 + 1, "CONFIG layout");
static_assert(MEASURE_SIZE == 2 + 2 + 1, "MEASURE layout");
static_assert(DATA_SIZE == 2 + 2 + 1 + 10 * 2 + 2 + 4, "DATA layout");
static_assert(ERROR_SIZE == 2 + 1, "ERROR layout");
static_assert(STOP_SIZE == 2, "STOP layout");

}  // namespace

void setup() {
  pinMode(LED_PIN, OUTPUT);
  setLedOff();
  Serial.begin(BAUD_RATE);
  Wire.begin();
  Wire.setWireTimeout(I2C_TIMEOUT_US, true);
  initializeSensor();
}

void loop() {
  while (Serial.available() > 0) {
    receiver.feed(static_cast<uint8_t>(Serial.read()));
  }
  serviceMeasurement();
}
