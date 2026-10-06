/*
 * Physalix Acquisition firmware (version in firmware_metadata.h)
 * Target: Arduino Uno / ATmega328P at 16 MHz
 */

#include <Arduino.h>
#include <avr/interrupt.h>

#include "firmware_metadata.h"

namespace {

constexpr uint8_t MAGIC_0 = 0xA5;
constexpr uint8_t MAGIC_1 = 0x5A;
constexpr uint8_t PROTOCOL_VERSION = PHYSALIX_PROTOCOL_VERSION;
constexpr uint16_t MAX_PAYLOAD = 512;
constexpr uint32_t BAUD_RATE = 115200;

constexpr uint8_t FIRMWARE_MAJOR = PHYSALIX_FIRMWARE_VERSION_MAJOR;
constexpr uint8_t FIRMWARE_MINOR = PHYSALIX_FIRMWARE_VERSION_MINOR;
constexpr uint8_t FIRMWARE_PATCH = PHYSALIX_FIRMWARE_VERSION_PATCH;
constexpr uint32_t CAPABILITIES = PHYSALIX_REQUIRED_CAPABILITIES;

constexpr uint32_t MIN_PERIOD_US = 250;
constexpr uint32_t MAX_PERIOD_US = 4194304UL;
constexpr uint8_t ADC_RING_SIZE = 64;            // Must remain a power of two.
constexpr uint8_t DATA_VALUES_PER_FRAME = 48;

enum MessageType : uint8_t {
  HELLO = 1,
  HELLO_ACK = 2,
  CONFIG = 3,
  CONFIG_ACK = 4,
  START = 5,
  STOP = 6,
  DATA = 7,
  END = 8,
  ERROR_MESSAGE = 9,
};

enum FirmwareState : uint8_t {
  IDLE,
  CONFIGURED,
  ACQUIRING,
};

enum ErrorCode : uint16_t {
  ERR_PROTOCOL = 1,
  ERR_CONFIGURATION = 2,
  ERR_STATE = 3,
  ERR_OVERFLOW = 4,
  ERR_ADC_BUSY = 5,
};

struct AcquisitionConfig {
  uint32_t periodUs;
  uint32_t sampleCount;
  uint8_t analogChannel;
  uint8_t outputPin;
  uint8_t levels;
  uint32_t transitionIndex;
};

FirmwareState state = IDLE;
AcquisitionConfig activeConfig{};
bool hasConfig = false;
uint16_t timerCompare = 0;
uint8_t timerClockBits = 0;

volatile uint16_t adcRing[ADC_RING_SIZE];
volatile uint8_t ringHead = 0;
volatile uint8_t ringTail = 0;
volatile uint8_t ringCount = 0;
volatile uint32_t acquiredCount = 0;
volatile bool samplingActive = false;
volatile bool endPending = false;
volatile uint16_t faultPending = 0;

uint32_t sessionId = 0;
uint32_t sequenceNumber = 0;
uint32_t sentSampleCount = 0;
bool safeLevelApplied = true;

volatile uint8_t *stepOutputRegister = nullptr;
uint8_t stepBitMask = 0;

uint8_t rxPayload[MAX_PAYLOAD];

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

uint32_t readU32(const uint8_t *data) {
  return static_cast<uint32_t>(data[0]) |
         (static_cast<uint32_t>(data[1]) << 8) |
         (static_cast<uint32_t>(data[2]) << 16) |
         (static_cast<uint32_t>(data[3]) << 24);
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

void sendFrame(uint8_t type, const uint8_t *payload, uint16_t length) {
  uint8_t header[4] = {
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

void sendError(uint16_t code, const char *text) {
  uint8_t payload[42];
  writeU16(payload, code);
  uint8_t length = 2;
  while (*text != '\0' && length < sizeof(payload)) {
    payload[length++] = static_cast<uint8_t>(*text++);
  }
  sendFrame(ERROR_MESSAGE, payload, length);
}

bool initialLevelHigh() {
  return (activeConfig.levels & 0x01) != 0;
}

bool finalLevelHigh() {
  return (activeConfig.levels & 0x02) != 0;
}

void setStepLevelDirect(bool high) {
  if (high) {
    *stepOutputRegister |= stepBitMask;
  } else {
    *stepOutputRegister &= static_cast<uint8_t>(~stepBitMask);
  }
}

void applySafeLevel() {
  if (hasConfig) {
    digitalWrite(activeConfig.outputPin, initialLevelHigh() ? HIGH : LOW);
  } else {
    digitalWrite(8, LOW);
  }
  safeLevelApplied = true;
}

void stopSampling() {
  const uint8_t savedSreg = SREG;
  cli();
  TCCR1B = 0;
  TIMSK1 = 0;
  ADCSRA &= static_cast<uint8_t>(~(_BV(ADIE) | _BV(ADEN)));
  samplingActive = false;
  SREG = savedSreg;
}

bool chooseTimer(uint32_t requestedUs, uint32_t &actualUs,
                 uint16_t &compare, uint8_t &clockBits) {
  if (requestedUs < MIN_PERIOD_US) {
    requestedUs = MIN_PERIOD_US;
  }
  if (requestedUs > MAX_PERIOD_US) {
    return false;
  }

  const uint16_t divisors[] = {1, 8, 64, 256, 1024};
  const uint8_t bits[] = {
    _BV(CS10), _BV(CS11), static_cast<uint8_t>(_BV(CS11) | _BV(CS10)),
    _BV(CS12), static_cast<uint8_t>(_BV(CS12) | _BV(CS10)),
  };
  const uint64_t requestedCycles = static_cast<uint64_t>(requestedUs) * 16ULL;
  for (uint8_t i = 0; i < 5; ++i) {
    const uint64_t ticks = (requestedCycles + divisors[i] / 2) / divisors[i];
    if (ticks >= 1 && ticks <= 65536ULL) {
      compare = static_cast<uint16_t>(ticks - 1);
      clockBits = bits[i];
      actualUs = static_cast<uint32_t>((ticks * divisors[i] + 8) / 16);
      return true;
    }
  }
  return false;
}

bool decodeAndValidateConfig(const uint8_t *payload, uint16_t length,
                             AcquisitionConfig &candidate,
                             uint16_t &compare, uint8_t &clockBits) {
  if (length != 15) {
    return false;
  }
  candidate.periodUs = readU32(payload);
  candidate.sampleCount = readU32(payload + 4);
  candidate.analogChannel = payload[8];
  candidate.outputPin = payload[9];
  candidate.levels = payload[10];
  candidate.transitionIndex = readU32(payload + 11);

  if (candidate.sampleCount == 0 || candidate.sampleCount > 1000000UL ||
      candidate.analogChannel != 0 || candidate.outputPin < 2 ||
      candidate.outputPin > 13 || (candidate.levels & 0xFC) != 0 ||
      (candidate.levels & 0x01) == ((candidate.levels >> 1) & 0x01) ||
      candidate.transitionIndex >= candidate.sampleCount) {
    return false;
  }
  uint32_t actualUs = 0;
  if (!chooseTimer(candidate.periodUs, actualUs, compare, clockBits)) {
    return false;
  }
  candidate.periodUs = actualUs;
  return true;
}

void encodeConfig(const AcquisitionConfig &config, uint8_t *payload) {
  writeU32(payload, config.periodUs);
  writeU32(payload + 4, config.sampleCount);
  payload[8] = config.analogChannel;
  payload[9] = config.outputPin;
  payload[10] = config.levels;
  writeU32(payload + 11, config.transitionIndex);
}

void configureAdcAndPrime() {
  ADMUX = _BV(REFS0);  // AVcc reference, ADC0 input, right adjusted.
  DIDR0 |= _BV(ADC0D);
  ADCSRB = 0;
  ADCSRA = _BV(ADEN) | _BV(ADPS2) | _BV(ADPS1) | _BV(ADPS0);
  ADCSRA |= _BV(ADSC);
  while ((ADCSRA & _BV(ADSC)) != 0) {
    // One priming conversion outside the timed acquisition.
  }
  (void)ADC;
}

void sendHelloAck() {
  uint8_t payload[7] = {FIRMWARE_MAJOR, FIRMWARE_MINOR, FIRMWARE_PATCH, 0, 0, 0, 0};
  writeU32(payload + 3, CAPABILITIES);
  sendFrame(HELLO_ACK, payload, sizeof(payload));
}

uint8_t copyDataFromRing(uint16_t *values) {
  uint8_t savedSreg = SREG;
  cli();
  uint8_t count = ringCount;
  if (count > DATA_VALUES_PER_FRAME) {
    count = DATA_VALUES_PER_FRAME;
  }
  if (count != 0) {
    values[0] = adcRing[ringTail];
    ringTail = static_cast<uint8_t>((ringTail + 1) & (ADC_RING_SIZE - 1));
    --ringCount;
  }
  SREG = savedSreg;
  for (uint8_t i = 1; i < count; ++i) {
    // Release each slot only after reading it. Keeping this critical section to
    // one value prevents Timer1/ADC latency even at the minimum period.
    savedSreg = SREG;
    cli();
    values[i] = adcRing[ringTail];
    ringTail = static_cast<uint8_t>((ringTail + 1) & (ADC_RING_SIZE - 1));
    --ringCount;
    SREG = savedSreg;
  }
  return count;
}

void sendOneDataFrame() {
  uint16_t values[DATA_VALUES_PER_FRAME];
  const uint8_t count = copyDataFromRing(values);
  if (count == 0) {
    return;
  }
  uint8_t payload[14 + DATA_VALUES_PER_FRAME * 2];
  writeU32(payload, sessionId);
  writeU32(payload + 4, sequenceNumber);
  writeU32(payload + 8, sentSampleCount);
  writeU16(payload + 12, count);
  for (uint8_t i = 0; i < count; ++i) {
    writeU16(payload + 14 + 2 * i, values[i]);
  }
  sendFrame(DATA, payload, static_cast<uint16_t>(14 + 2 * count));
  ++sequenceNumber;
  sentSampleCount += count;
}

uint8_t currentRingCount() {
  const uint8_t savedSreg = SREG;
  cli();
  const uint8_t count = ringCount;
  SREG = savedSreg;
  return count;
}

void resetAcquisitionCounters() {
  const uint8_t savedSreg = SREG;
  cli();
  ringHead = 0;
  ringTail = 0;
  ringCount = 0;
  acquiredCount = 0;
  endPending = false;
  faultPending = 0;
  SREG = savedSreg;
  sequenceNumber = 0;
  sentSampleCount = 0;
}

void startAcquisition(uint32_t newSessionId) {
  resetAcquisitionCounters();
  sessionId = newSessionId;
  pinMode(activeConfig.outputPin, OUTPUT);
  digitalWrite(activeConfig.outputPin, initialLevelHigh() ? HIGH : LOW);
  stepOutputRegister = portOutputRegister(digitalPinToPort(activeConfig.outputPin));
  stepBitMask = digitalPinToBitMask(activeConfig.outputPin);
  safeLevelApplied = false;

  configureAdcAndPrime();
  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1 = 0;
  OCR1A = timerCompare;
  TIFR1 = _BV(OCF1A);
  TIMSK1 = _BV(OCIE1A);

  const uint8_t savedSreg = SREG;
  cli();
  samplingActive = true;
  state = ACQUIRING;
  if (activeConfig.transitionIndex == 0) {
    setStepLevelDirect(finalLevelHigh());
  }
  ADCSRA = _BV(ADEN) | _BV(ADIE) | _BV(ADIF) |
            _BV(ADPS2) | _BV(ADPS1) | _BV(ADPS0);
  ADCSRA |= _BV(ADSC);  // Start sample 0 before the timer epoch.
  // Starting Timer1 last guarantees that sample 1 cannot begin less than Te
  // after sample 0; later samples are exactly one CTC period apart.
  TCCR1B = static_cast<uint8_t>(_BV(WGM12) | timerClockBits);
  SREG = savedSreg;
}

void finishWithEnd() {
  uint8_t payload[8];
  writeU32(payload, sessionId);
  writeU32(payload + 4, sentSampleCount);
  sendFrame(END, payload, sizeof(payload));
  state = CONFIGURED;
  endPending = false;
}

void abortActiveWithError(uint16_t code, const char *text) {
  stopSampling();
  applySafeLevel();
  while (currentRingCount() != 0) {
    sendOneDataFrame();
  }
  sendError(code, text);
  state = hasConfig ? CONFIGURED : IDLE;
  endPending = false;
  faultPending = 0;
}

void handleFrame(uint8_t version, uint8_t type, const uint8_t *payload, uint16_t length) {
  if (version != PROTOCOL_VERSION) {
    if (state == ACQUIRING) {
      abortActiveWithError(ERR_PROTOCOL, "protocol version");
    } else {
      sendError(ERR_PROTOCOL, "protocol version");
    }
    return;
  }

  if (type == HELLO) {
    if (length == 0) {
      sendHelloAck();
    } else if (state == ACQUIRING) {
      abortActiveWithError(ERR_PROTOCOL, "HELLO payload");
    } else {
      sendError(ERR_PROTOCOL, "HELLO payload");
    }
    return;
  }

  if (type == CONFIG) {
    if (state == ACQUIRING) {
      abortActiveWithError(ERR_STATE, "CONFIG while active");
      return;
    }
    AcquisitionConfig candidate{};
    uint16_t candidateCompare = 0;
    uint8_t candidateClockBits = 0;
    if (!decodeAndValidateConfig(payload, length, candidate,
                                 candidateCompare, candidateClockBits)) {
      sendError(ERR_CONFIGURATION, "invalid CONFIG");
      return;
    }
    if (hasConfig && activeConfig.outputPin != candidate.outputPin) {
      digitalWrite(activeConfig.outputPin, initialLevelHigh() ? HIGH : LOW);
      pinMode(activeConfig.outputPin, INPUT);
    } else if (!hasConfig && candidate.outputPin != 8) {
      pinMode(8, INPUT);
    }
    activeConfig = candidate;
    timerCompare = candidateCompare;
    timerClockBits = candidateClockBits;
    hasConfig = true;
    pinMode(activeConfig.outputPin, OUTPUT);
    applySafeLevel();
    configureAdcAndPrime();
    ADCSRA &= static_cast<uint8_t>(~_BV(ADEN));
    uint8_t ack[15];
    encodeConfig(activeConfig, ack);
    sendFrame(CONFIG_ACK, ack, sizeof(ack));
    state = CONFIGURED;
    return;
  }

  if (type == START) {
    if (length != 4 || state != CONFIGURED || !hasConfig) {
      if (state == ACQUIRING) {
        abortActiveWithError(ERR_STATE, "invalid START");
      } else {
        sendError(ERR_STATE, "invalid START");
      }
      return;
    }
    startAcquisition(readU32(payload));
    return;
  }

  if (type == STOP) {
    if (length != 4) {
      if (state == ACQUIRING) {
        abortActiveWithError(ERR_STATE, "invalid STOP");
      } else {
        sendError(ERR_STATE, "invalid STOP");
      }
      return;
    }
    if (state != ACQUIRING) {
      return;  // STOP is deliberately idempotent at rest.
    }
    if (readU32(payload) != sessionId) {
      abortActiveWithError(ERR_STATE, "STOP session");
      return;
    }
    stopSampling();
    applySafeLevel();
    endPending = true;
    return;
  }

  if (state == ACQUIRING) {
    abortActiveWithError(ERR_STATE, "unexpected command");
  } else {
    sendError(ERR_STATE, "unexpected command");
  }
}

class FrameReceiver {
 public:
  void feed(uint8_t value) {
    switch (phase_) {
      case WAIT_MAGIC_0:
        if (value == MAGIC_0) phase_ = WAIT_MAGIC_1;
        break;
      case WAIT_MAGIC_1:
        if (value == MAGIC_1) {
          phase_ = READ_VERSION;
        } else if (value != MAGIC_0) {
          phase_ = WAIT_MAGIC_0;
        }
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
        if (length_ > MAX_PAYLOAD) {
          reset(value);
        } else if (length_ == 0) {
          phase_ = READ_CRC_0;
        } else {
          payloadIndex_ = 0;
          phase_ = READ_PAYLOAD;
        }
        break;
      case READ_PAYLOAD:
        rxPayload[payloadIndex_++] = value;
        crc_ = crcUpdate(crc_, value);
        if (payloadIndex_ == length_) phase_ = READ_CRC_0;
        break;
      case READ_CRC_0:
        receivedCrc_ = value;
        phase_ = READ_CRC_1;
        break;
      case READ_CRC_1:
        receivedCrc_ |= static_cast<uint16_t>(value) << 8;
        if (receivedCrc_ == crc_) {
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
    phase_ = (lastByte == MAGIC_0) ? WAIT_MAGIC_1 : WAIT_MAGIC_0;
    payloadIndex_ = 0;
    length_ = 0;
  }

  Phase phase_ = WAIT_MAGIC_0;
  uint8_t version_ = 0;
  uint8_t type_ = 0;
  uint16_t length_ = 0;
  uint16_t payloadIndex_ = 0;
  uint16_t crc_ = 0xFFFF;
  uint16_t receivedCrc_ = 0;
};

FrameReceiver receiver;

void serviceAcquisition() {
  if (state != ACQUIRING) {
    return;
  }
  if (!safeLevelApplied && (!samplingActive || endPending || faultPending != 0)) {
    applySafeLevel();
  }
  const uint8_t buffered = currentRingCount();
  if (buffered != 0 && (!samplingActive || buffered >= DATA_VALUES_PER_FRAME)) {
    sendOneDataFrame();
    return;
  }
  if (samplingActive) {
    return;
  }
  uint16_t fault = 0;
  bool shouldEnd = false;
  const uint8_t savedSreg = SREG;
  cli();
  fault = faultPending;
  shouldEnd = endPending;
  SREG = savedSreg;
  if (fault != 0) {
    sendError(fault, fault == ERR_OVERFLOW ? "sample overflow" : "ADC busy");
    faultPending = 0;
    state = CONFIGURED;
  } else if (shouldEnd) {
    finishWithEnd();
  }
}

}  // namespace

ISR(TIMER1_COMPA_vect) {
  if (!samplingActive) {
    return;
  }
  if ((ADCSRA & _BV(ADSC)) != 0) {
    TCCR1B = 0;
    TIMSK1 = 0;
    samplingActive = false;
    faultPending = ERR_ADC_BUSY;
    return;
  }
  if (acquiredCount == activeConfig.transitionIndex) {
    setStepLevelDirect(finalLevelHigh());
  }
  ADCSRA |= _BV(ADSC);
}

ISR(ADC_vect) {
  const uint16_t value = ADC;
  if (!samplingActive) {
    return;
  }
  if (ringCount >= ADC_RING_SIZE) {
    TCCR1B = 0;
    TIMSK1 = 0;
    samplingActive = false;
    faultPending = ERR_OVERFLOW;
    return;
  }
  adcRing[ringHead] = value;
  ringHead = static_cast<uint8_t>((ringHead + 1) & (ADC_RING_SIZE - 1));
  ++ringCount;
  ++acquiredCount;
  if (acquiredCount >= activeConfig.sampleCount) {
    TCCR1B = 0;
    TIMSK1 = 0;
    samplingActive = false;
    endPending = true;
  }
}

void setup() {
  pinMode(8, OUTPUT);
  digitalWrite(8, LOW);
  Serial.begin(BAUD_RATE);
}

void loop() {
  while (Serial.available() > 0) {
    receiver.feed(static_cast<uint8_t>(Serial.read()));
  }
  serviceAcquisition();
}
