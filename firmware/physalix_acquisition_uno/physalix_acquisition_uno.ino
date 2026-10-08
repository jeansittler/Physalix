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
constexpr uint8_t LEGACY_CONFIG_SIZE = 15;
constexpr uint8_t EXTENDED_CONFIG_SIZE = 20;
constexpr uint8_t GENERATOR_CONFIG_SIZE = 8;
constexpr uint8_t GENERATOR_PIN = 8;
constexpr uint8_t GENERATOR_LEVELS = 0x02;
constexpr uint16_t GENERATOR_PRESCALER = 64;
constexpr uint32_t GENERATOR_MIN_HALF_PERIOD_TICKS = 125UL;
constexpr uint32_t GENERATOR_MAX_HALF_PERIOD_TICKS = 1250000UL;
constexpr uint32_t GENERATOR_KEEPALIVE_TIMEOUT_MS = 2500UL;

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
  GEN_CONFIG = 10,
  GEN_CONFIG_ACK = 11,
  GEN_START = 12,
  GEN_START_ACK = 13,
  GEN_STOP = 14,
  GEN_STOP_ACK = 15,
  GEN_STATUS = 16,
  GEN_STATUS_ACK = 17,
  GEN_KEEPALIVE = 18,
  ACQ_STARTED = 19,
  DATA_GBF = 20,
};

enum FirmwareState : uint8_t {
  IDLE,
  CONFIGURED,
  ARMED,
  ACQUIRING,
};

enum ErrorCode : uint16_t {
  ERR_PROTOCOL = 1,
  ERR_CONFIGURATION = 2,
  ERR_STATE = 3,
  ERR_OVERFLOW = 4,
  ERR_ADC_BUSY = 5,
  ERR_GENERATOR = 6,
  ERR_TRIGGER_CANCELLED = 7,
};

enum GeneratorState : uint8_t {
  GENERATOR_STOPPED = 0,
  GENERATOR_RUNNING = 1,
};

enum GenerationType : uint8_t {
  GENERATION_STEP = 0,
  GENERATION_SQUARE_BURST = 1,
};

struct AcquisitionConfig {
  uint32_t periodUs;
  uint32_t sampleCount;
  uint8_t analogChannel;
  uint8_t generationType;
  uint8_t outputPin;
  uint8_t levels;
  uint32_t parameter1;
  uint32_t parameter2;
};

struct GeneratorConfig {
  uint8_t outputPin;
  uint8_t levels;
  uint16_t prescaler;
  uint32_t halfPeriodTicks;
};

volatile FirmwareState state = IDLE;
AcquisitionConfig activeConfig{};
bool hasConfig = false;
bool activeConfigExtended = false;
uint16_t timerCompare = 0;
uint8_t timerClockBits = 0;

volatile uint16_t adcRing[ADC_RING_SIZE];
volatile uint8_t generatorLevelRing[ADC_RING_SIZE];
volatile uint8_t ringHead = 0;
volatile uint8_t ringTail = 0;
volatile uint8_t ringCount = 0;
volatile uint32_t acquiredCount = 0;
volatile bool samplingActive = false;
volatile bool endPending = false;
volatile uint16_t faultPending = 0;
volatile bool pendingSampleLevelHigh = false;
volatile bool acquisitionStartedPending = false;

uint32_t sessionId = 0;
uint32_t sequenceNumber = 0;
uint32_t sentSampleCount = 0;
bool safeLevelApplied = true;
uint32_t nextSquareTransitionIndex = 0;
volatile bool acquisitionUsesContinuousGenerator = false;

volatile uint8_t *stepOutputRegister = nullptr;
uint8_t stepBitMask = 0;

GeneratorConfig generatorConfig{};
bool hasGeneratorConfig = false;
volatile GeneratorState generatorState = GENERATOR_STOPPED;
volatile uint32_t generatorRemainingTicks = 0;
volatile uint16_t generatorActiveChunkTicks = 0;
volatile bool generatorLevelHigh = false;
volatile bool generatorFaultPending = false;
uint32_t generatorLastKeepaliveMs = 0;
volatile uint8_t *generatorOutputRegister = nullptr;
volatile uint8_t *generatorInputRegister = nullptr;
uint8_t generatorBitMask = 0;

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

bool lowLevelHigh() {
  return (activeConfig.levels & 0x01) != 0;
}

bool highLevelHigh() {
  return (activeConfig.levels & 0x02) != 0;
}

void setStepLevelDirect(bool high) {
  if (high) {
    *stepOutputRegister |= stepBitMask;
  } else {
    *stepOutputRegister &= static_cast<uint8_t>(~stepBitMask);
  }
}

constexpr uint16_t generatorChunkTicks(uint32_t remainingTicks) {
  return remainingTicks > 256UL ? 256U : static_cast<uint16_t>(remainingTicks);
}

constexpr uint8_t generatorCompareForChunk(uint16_t chunkTicks) {
  return static_cast<uint8_t>(chunkTicks - 1U);
}

static_assert(generatorChunkTicks(1) == 1, "Timer2 one-tick chunk");
static_assert(generatorCompareForChunk(1) == 0, "Timer2 OCR2A one tick");
static_assert(generatorChunkTicks(125) == 125, "Timer2 125-tick chunk");
static_assert(generatorCompareForChunk(125) == 124, "Timer2 OCR2A 125 ticks");
static_assert(generatorChunkTicks(256) == 256, "Timer2 256-tick chunk");
static_assert(generatorCompareForChunk(256) == 255, "Timer2 OCR2A 256 ticks");
static_assert(generatorChunkTicks(257) == 256, "Timer2 extended chunk");

void setGeneratorLevelDirect(bool high) {
  if (high) {
    *generatorOutputRegister |= generatorBitMask;
  } else {
    *generatorOutputRegister &= static_cast<uint8_t>(~generatorBitMask);
  }
  generatorLevelHigh = high;
}

bool generatorPinIsHigh() {
  return (*generatorInputRegister & generatorBitMask) != 0;
}

bool acquisitionSessionActive() {
  return state == ARMED || state == ACQUIRING;
}

void stopGeneratorFromIsr() {
  TCCR2B = 0;
  TIMSK2 = 0;
  setGeneratorLevelDirect(false);
  generatorState = GENERATOR_STOPPED;
  generatorRemainingTicks = 0;
  generatorActiveChunkTicks = 0;
}

void stopGenerator() {
  const uint8_t savedSreg = SREG;
  cli();
  stopGeneratorFromIsr();
  SREG = savedSreg;
}

void startGenerator() {
  generatorLastKeepaliveMs = millis();
  const uint8_t savedSreg = SREG;
  cli();
  TCCR2A = _BV(WGM21);  // CTC, TOP = OCR2A.
  TCCR2B = 0;
  setGeneratorLevelDirect(false);
  TCNT2 = 0;
  generatorRemainingTicks = generatorConfig.halfPeriodTicks;
  generatorActiveChunkTicks = generatorChunkTicks(generatorRemainingTicks);
  OCR2A = generatorCompareForChunk(generatorActiveChunkTicks);
  TIFR2 = _BV(OCF2A);
  TIMSK2 = _BV(OCIE2A);
  // HIGH precedes the Timer2 clock start, so the first half-period is complete.
  setGeneratorLevelDirect(true);
  generatorState = GENERATOR_RUNNING;
  TCCR2B = _BV(CS22);  // Prescaler 64 at 16 MHz: one tick is 4 us.
  SREG = savedSreg;
}

void applySafeLevel() {
  if (acquisitionUsesContinuousGenerator) {
    if (generatorState != GENERATOR_RUNNING) {
      setGeneratorLevelDirect(false);
    }
    // Timer2 owns D8, or the continuous generator has already stopped LOW.
  } else if (generatorState == GENERATOR_RUNNING && hasConfig &&
             activeConfig.outputPin == GENERATOR_PIN) {
    // Acquisition configuration must not overwrite the active Timer2 output.
  } else if (hasConfig) {
    digitalWrite(activeConfig.outputPin, lowLevelHigh() ? HIGH : LOW);
  } else {
    digitalWrite(GENERATOR_PIN, LOW);
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

bool decodeAndValidateGeneratorConfig(const uint8_t *payload, uint16_t length,
                                      GeneratorConfig &candidate) {
  if (length != GENERATOR_CONFIG_SIZE) {
    return false;
  }
  candidate.outputPin = payload[0];
  candidate.levels = payload[1];
  candidate.prescaler = readU16(payload + 2);
  candidate.halfPeriodTicks = readU32(payload + 4);
  return candidate.outputPin == GENERATOR_PIN &&
         candidate.levels == GENERATOR_LEVELS &&
         candidate.prescaler == GENERATOR_PRESCALER &&
         candidate.halfPeriodTicks >= GENERATOR_MIN_HALF_PERIOD_TICKS &&
         candidate.halfPeriodTicks <= GENERATOR_MAX_HALF_PERIOD_TICKS;
}

void encodeGeneratorConfig(const GeneratorConfig &config, uint8_t *payload) {
  payload[0] = config.outputPin;
  payload[1] = config.levels;
  writeU16(payload + 2, config.prescaler);
  writeU32(payload + 4, config.halfPeriodTicks);
}

void sendGeneratorState(uint8_t messageType) {
  const uint8_t payload[1] = {static_cast<uint8_t>(generatorState)};
  sendFrame(messageType, payload, sizeof(payload));
}

bool decodeAndValidateConfig(const uint8_t *payload, uint16_t length,
                             AcquisitionConfig &candidate,
                             uint16_t &compare, uint8_t &clockBits,
                             bool &extended) {
  if (length != LEGACY_CONFIG_SIZE && length != EXTENDED_CONFIG_SIZE) {
    return false;
  }
  extended = length == EXTENDED_CONFIG_SIZE;
  candidate.periodUs = readU32(payload);
  candidate.sampleCount = readU32(payload + 4);
  candidate.analogChannel = payload[8];
  if (extended) {
    candidate.generationType = payload[9];
    candidate.outputPin = payload[10];
    candidate.levels = payload[11];
    candidate.parameter1 = readU32(payload + 12);
    candidate.parameter2 = readU32(payload + 16);
  } else {
    candidate.generationType = GENERATION_STEP;
    candidate.outputPin = payload[9];
    candidate.levels = payload[10];
    candidate.parameter1 = readU32(payload + 11);
    candidate.parameter2 = 0;
  }

  if (candidate.sampleCount == 0 || candidate.sampleCount > 1000000UL ||
      candidate.analogChannel != 0 || candidate.outputPin < 2 ||
      candidate.outputPin > 13 || (candidate.levels & 0xFC) != 0) {
    return false;
  }
  if (candidate.generationType == GENERATION_STEP) {
    if ((candidate.levels & 0x01) == ((candidate.levels >> 1) & 0x01) ||
        candidate.parameter1 >= candidate.sampleCount || candidate.parameter2 != 0) {
      return false;
    }
  } else if (candidate.generationType == GENERATION_SQUARE_BURST) {
    if (candidate.levels != 0x02 || candidate.parameter1 == 0 || candidate.parameter2 == 0) {
      return false;
    }
    const uint64_t expectedCount =
        2ULL * candidate.parameter1 * candidate.parameter2 + 1ULL;
    if (expectedCount != candidate.sampleCount) {
      return false;
    }
  } else {
    return false;
  }
  uint32_t actualUs = 0;
  if (!chooseTimer(candidate.periodUs, actualUs, compare, clockBits)) {
    return false;
  }
  candidate.periodUs = actualUs;
  return true;
}

uint8_t encodeConfig(const AcquisitionConfig &config, bool extended, uint8_t *payload) {
  writeU32(payload, config.periodUs);
  writeU32(payload + 4, config.sampleCount);
  payload[8] = config.analogChannel;
  if (extended) {
    payload[9] = config.generationType;
    payload[10] = config.outputPin;
    payload[11] = config.levels;
    writeU32(payload + 12, config.parameter1);
    writeU32(payload + 16, config.parameter2);
    return EXTENDED_CONFIG_SIZE;
  }
  payload[9] = config.outputPin;
  payload[10] = config.levels;
  writeU32(payload + 11, config.parameter1);
  return LEGACY_CONFIG_SIZE;
}

void configureAdcRegisters() {
  ADMUX = _BV(REFS0);  // AVcc reference, ADC0 input, right adjusted.
  DIDR0 |= _BV(ADC0D);
  ADCSRB = 0;
  ADCSRA = _BV(ADEN) | _BV(ADPS2) | _BV(ADPS1) | _BV(ADPS0);
}

void configureAdcAndPrime() {
  configureAdcRegisters();
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

uint8_t copyDataFromRing(uint16_t *values, uint8_t *levels) {
  uint8_t savedSreg = SREG;
  cli();
  uint8_t count = ringCount;
  if (count > DATA_VALUES_PER_FRAME) {
    count = DATA_VALUES_PER_FRAME;
  }
  if (count != 0) {
    values[0] = adcRing[ringTail];
    levels[0] = generatorLevelRing[ringTail];
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
    levels[i] = generatorLevelRing[ringTail];
    ringTail = static_cast<uint8_t>((ringTail + 1) & (ADC_RING_SIZE - 1));
    --ringCount;
    SREG = savedSreg;
  }
  return count;
}

void sendOneDataFrame() {
  uint16_t values[DATA_VALUES_PER_FRAME];
  uint8_t levels[DATA_VALUES_PER_FRAME];
  const uint8_t count = copyDataFromRing(values, levels);
  if (count == 0) {
    return;
  }
  constexpr uint8_t MAX_BITMAP_SIZE = (DATA_VALUES_PER_FRAME + 7) / 8;
  uint8_t payload[14 + DATA_VALUES_PER_FRAME * 2 + MAX_BITMAP_SIZE];
  writeU32(payload, sessionId);
  writeU32(payload + 4, sequenceNumber);
  writeU32(payload + 8, sentSampleCount);
  writeU16(payload + 12, count);
  for (uint8_t i = 0; i < count; ++i) {
    writeU16(payload + 14 + 2 * i, values[i]);
  }
  uint16_t payloadLength = static_cast<uint16_t>(14 + 2 * count);
  uint8_t messageType = DATA;
  if (acquisitionUsesContinuousGenerator) {
    const uint8_t bitmapSize = static_cast<uint8_t>((count + 7) / 8);
    for (uint8_t i = 0; i < bitmapSize; ++i) {
      payload[payloadLength + i] = 0;
    }
    for (uint8_t i = 0; i < count; ++i) {
      if (levels[i] != 0) {
        payload[payloadLength + i / 8] |= _BV(i & 7);
      }
    }
    payloadLength += bitmapSize;
    messageType = DATA_GBF;
  }
  sendFrame(messageType, payload, payloadLength);
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
  pendingSampleLevelHigh = false;
  acquisitionStartedPending = false;
  SREG = savedSreg;
  sequenceNumber = 0;
  sentSampleCount = 0;
}

void prepareAcquisition(uint32_t newSessionId, bool continuousGenerator) {
  resetAcquisitionCounters();
  sessionId = newSessionId;
  acquisitionUsesContinuousGenerator = continuousGenerator;
  if (!acquisitionUsesContinuousGenerator) {
    pinMode(activeConfig.outputPin, OUTPUT);
    digitalWrite(activeConfig.outputPin, lowLevelHigh() ? HIGH : LOW);
    stepOutputRegister = portOutputRegister(digitalPinToPort(activeConfig.outputPin));
    stepBitMask = digitalPinToBitMask(activeConfig.outputPin);
  }
  safeLevelApplied = false;

  if (continuousGenerator) {
    // Arm the ADC without any conversion. The physical rising edge starts k=0.
    configureAdcRegisters();
  } else {
    configureAdcAndPrime();
  }
  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1 = 0;
  OCR1A = timerCompare;
  TIFR1 = _BV(OCF1A);
  TIMSK1 = 0;

  ADCSRA = _BV(ADEN) | _BV(ADIE) | _BV(ADIF) |
            _BV(ADPS2) | _BV(ADPS1) | _BV(ADPS0);
}

void startAcquisition(uint32_t newSessionId) {
  prepareAcquisition(newSessionId, false);

  const uint8_t savedSreg = SREG;
  cli();
  samplingActive = true;
  state = ACQUIRING;
  TIMSK1 = _BV(OCIE1A);
  if (activeConfig.generationType == GENERATION_STEP) {
    if (activeConfig.parameter1 == 0) {
      setStepLevelDirect(highLevelHigh());
    }
  } else {
    // SQUARE_BURST sample 0: the rising edge defines t=0 and precedes ADC start.
    setStepLevelDirect(highLevelHigh());
    nextSquareTransitionIndex = activeConfig.parameter1;
  }
  ADCSRA |= _BV(ADSC);  // Start sample 0 before the timer epoch.
  // Starting Timer1 last guarantees that sample 1 cannot begin less than Te
  // after sample 0; later samples are exactly one CTC period apart.
  TCCR1B = static_cast<uint8_t>(_BV(WGM12) | timerClockBits);
  SREG = savedSreg;
}

void armAcquisition(uint32_t newSessionId) {
  prepareAcquisition(newSessionId, true);
  const uint8_t savedSreg = SREG;
  cli();
  samplingActive = false;
  state = ARMED;
  SREG = savedSreg;
}

bool cancelArmedAcquisition() {
  const uint8_t savedSreg = SREG;
  cli();
  if (state != ARMED) {
    SREG = savedSreg;
    return false;
  }
  TCCR1B = 0;
  TIMSK1 = 0;
  ADCSRA &= static_cast<uint8_t>(~(_BV(ADIE) | _BV(ADEN)));
  samplingActive = false;
  acquisitionStartedPending = false;
  state = CONFIGURED;
  SREG = savedSreg;
  applySafeLevel();
  acquisitionUsesContinuousGenerator = false;
  return true;
}

void sendAcquisitionStarted() {
  uint8_t payload[4];
  writeU32(payload, sessionId);
  sendFrame(ACQ_STARTED, payload, sizeof(payload));
}

bool sendPendingAcquisitionStarted() {
  bool pending = false;
  const uint8_t savedSreg = SREG;
  cli();
  if (acquisitionStartedPending) {
    acquisitionStartedPending = false;
    pending = true;
  }
  SREG = savedSreg;
  if (pending) {
    sendAcquisitionStarted();
  }
  return pending;
}

void sendEnd() {
  uint8_t payload[8];
  writeU32(payload, sessionId);
  writeU32(payload + 4, sentSampleCount);
  sendFrame(END, payload, sizeof(payload));
}

void finishWithEnd() {
  sendEnd();
  state = CONFIGURED;
  acquisitionUsesContinuousGenerator = false;
  endPending = false;
}

void abortActiveWithError(uint16_t code, const char *text) {
  stopSampling();
  applySafeLevel();
  sendPendingAcquisitionStarted();
  while (currentRingCount() != 0) {
    sendOneDataFrame();
  }
  sendError(code, text);
  state = hasConfig ? CONFIGURED : IDLE;
  acquisitionUsesContinuousGenerator = false;
  endPending = false;
  faultPending = 0;
}

void handleFrame(uint8_t version, uint8_t type, const uint8_t *payload, uint16_t length) {
  if (version != PROTOCOL_VERSION) {
    if (acquisitionSessionActive()) {
      abortActiveWithError(ERR_PROTOCOL, "protocol version");
    } else {
      sendError(ERR_PROTOCOL, "protocol version");
    }
    return;
  }

  if (type == HELLO) {
    if (length == 0) {
      sendHelloAck();
    } else if (acquisitionSessionActive()) {
      abortActiveWithError(ERR_PROTOCOL, "HELLO payload");
    } else {
      sendError(ERR_PROTOCOL, "HELLO payload");
    }
    return;
  }

  if (type == GEN_CONFIG) {
    if (acquisitionSessionActive() || generatorState != GENERATOR_STOPPED) {
      sendError(ERR_STATE, "GEN_CONFIG while active");
      return;
    }
    GeneratorConfig candidate{};
    if (!decodeAndValidateGeneratorConfig(payload, length, candidate)) {
      sendError(ERR_CONFIGURATION, "invalid GEN_CONFIG");
      return;
    }
    generatorConfig = candidate;
    hasGeneratorConfig = true;
    pinMode(GENERATOR_PIN, OUTPUT);
    setGeneratorLevelDirect(false);
    uint8_t ack[GENERATOR_CONFIG_SIZE];
    encodeGeneratorConfig(generatorConfig, ack);
    sendFrame(GEN_CONFIG_ACK, ack, sizeof(ack));
    return;
  }

  if (type == GEN_START) {
    if (length != 0) {
      sendError(ERR_PROTOCOL, "GEN_START payload");
      return;
    }
    if (acquisitionSessionActive() || generatorState != GENERATOR_STOPPED ||
        !hasGeneratorConfig) {
      sendError(ERR_STATE, "invalid GEN_START");
      return;
    }
    startGenerator();
    sendGeneratorState(GEN_START_ACK);
    return;
  }

  if (type == GEN_STOP) {
    if (length != 0) {
      sendError(ERR_PROTOCOL, "GEN_STOP payload");
      return;
    }
    if (generatorState == GENERATOR_RUNNING) {
      stopGenerator();
    }
    const bool triggerCancelled = cancelArmedAcquisition();
    sendGeneratorState(GEN_STOP_ACK);
    if (triggerCancelled) {
      sendError(ERR_TRIGGER_CANCELLED, "trigger cancelled");
    }
    return;
  }

  if (type == GEN_STATUS) {
    if (length != 0) {
      sendError(ERR_PROTOCOL, "GEN_STATUS payload");
      return;
    }
    sendGeneratorState(GEN_STATUS_ACK);
    return;
  }

  if (type == GEN_KEEPALIVE) {
    if (length != 0) {
      sendError(ERR_PROTOCOL, "GEN_KEEPALIVE payload");
      return;
    }
    if (generatorState != GENERATOR_RUNNING) {
      sendError(ERR_STATE, "GEN_KEEPALIVE while stopped");
      return;
    }
    generatorLastKeepaliveMs = millis();
    return;
  }

  if (type == CONFIG) {
    if (acquisitionSessionActive()) {
      abortActiveWithError(ERR_STATE, "CONFIG while active");
      return;
    }
    AcquisitionConfig candidate{};
    uint16_t candidateCompare = 0;
    uint8_t candidateClockBits = 0;
    bool candidateExtended = false;
    if (!decodeAndValidateConfig(payload, length, candidate,
                                 candidateCompare, candidateClockBits,
                                 candidateExtended)) {
      sendError(ERR_CONFIGURATION, "invalid CONFIG");
      return;
    }
    if (hasConfig && activeConfig.outputPin != candidate.outputPin) {
      if (!(generatorState == GENERATOR_RUNNING &&
            activeConfig.outputPin == GENERATOR_PIN)) {
        digitalWrite(activeConfig.outputPin, lowLevelHigh() ? HIGH : LOW);
        pinMode(activeConfig.outputPin, INPUT);
      }
    } else if (!hasConfig && candidate.outputPin != GENERATOR_PIN &&
               generatorState != GENERATOR_RUNNING) {
      pinMode(GENERATOR_PIN, INPUT);
    }
    activeConfig = candidate;
    activeConfigExtended = candidateExtended;
    timerCompare = candidateCompare;
    timerClockBits = candidateClockBits;
    hasConfig = true;
    if (!(generatorState == GENERATOR_RUNNING &&
          activeConfig.outputPin == GENERATOR_PIN)) {
      pinMode(activeConfig.outputPin, OUTPUT);
    }
    applySafeLevel();
    configureAdcAndPrime();
    ADCSRA &= static_cast<uint8_t>(~_BV(ADEN));
    uint8_t ack[EXTENDED_CONFIG_SIZE];
    const uint8_t ackLength = encodeConfig(activeConfig, activeConfigExtended, ack);
    sendFrame(CONFIG_ACK, ack, ackLength);
    state = CONFIGURED;
    return;
  }

  if (type == START) {
    if (length != 4 || state != CONFIGURED || !hasConfig) {
      if (acquisitionSessionActive()) {
        abortActiveWithError(ERR_STATE, "invalid START");
      } else {
        sendError(ERR_STATE, "invalid START");
      }
      return;
    }
    const uint32_t newSessionId = readU32(payload);
    if (generatorState == GENERATOR_RUNNING) {
      armAcquisition(newSessionId);
    } else {
      startAcquisition(newSessionId);
    }
    return;
  }

  if (type == STOP) {
    if (length != 4) {
      if (acquisitionSessionActive()) {
        abortActiveWithError(ERR_STATE, "invalid STOP");
      } else {
        sendError(ERR_STATE, "invalid STOP");
      }
      return;
    }
    if (!acquisitionSessionActive()) {
      return;  // STOP is deliberately idempotent at rest.
    }
    if (readU32(payload) != sessionId) {
      abortActiveWithError(ERR_STATE, "STOP session");
      return;
    }
    if (state == ARMED) {
      if (cancelArmedAcquisition()) {
        sendEnd();
        return;
      }
    }
    stopSampling();
    applySafeLevel();
    endPending = true;
    return;
  }

  if (acquisitionSessionActive()) {
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
  if (state == ARMED) {
    return;
  }
  if (state != ACQUIRING) {
    return;
  }
  if (sendPendingAcquisitionStarted()) {
    return;
  }
  if (!safeLevelApplied && (!samplingActive || endPending || faultPending != 0)) {
    stopSampling();
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
    acquisitionUsesContinuousGenerator = false;
  } else if (shouldEnd) {
    finishWithEnd();
  }
}

void serviceGenerator() {
  if (generatorFaultPending) {
    const uint8_t savedSreg = SREG;
    cli();
    generatorFaultPending = false;
    SREG = savedSreg;
    if (cancelArmedAcquisition()) {
      sendError(ERR_TRIGGER_CANCELLED, "trigger cancelled");
    } else {
      sendError(ERR_GENERATOR, "generator scheduler fault");
    }
    return;
  }
  if (generatorState == GENERATOR_RUNNING &&
      static_cast<uint32_t>(millis() - generatorLastKeepaliveMs) >=
          GENERATOR_KEEPALIVE_TIMEOUT_MS) {
    stopGenerator();
    if (cancelArmedAcquisition()) {
      sendError(ERR_TRIGGER_CANCELLED, "trigger cancelled");
    }
  }
}

}  // namespace

ISR(TIMER2_COMPA_vect) {
  if (generatorState != GENERATOR_RUNNING || generatorActiveChunkTicks == 0 ||
      generatorActiveChunkTicks > generatorRemainingTicks) {
    stopGeneratorFromIsr();
    generatorFaultPending = true;
    return;
  }

  generatorRemainingTicks -= generatorActiveChunkTicks;
  if (generatorRemainingTicks == 0) {
    const bool risingEdge = !generatorLevelHigh;
    setGeneratorLevelDirect(risingEdge);
    generatorRemainingTicks = generatorConfig.halfPeriodTicks;
    if (risingEdge && state == ARMED && acquisitionUsesContinuousGenerator) {
      // This physical LOW->HIGH edge is t=0. Timer1 is still stopped here.
      // Clear its counter and any stale compare flag before enabling compare,
      // capture E_0 from D8, then launch ADC k=0. Starting Timer1 last makes
      // its first compare (k=1) occur exactly one complete Te later.
      TCNT1 = 0;
      TIFR1 = _BV(OCF1A);
      TIMSK1 = _BV(OCIE1A);
      pendingSampleLevelHigh = generatorPinIsHigh();
      samplingActive = true;
      state = ACQUIRING;
      acquisitionStartedPending = true;
      ADCSRA |= _BV(ADSC);
      TCCR1B = static_cast<uint8_t>(_BV(WGM12) | timerClockBits);
    }
  }

  const uint16_t nextChunk = generatorChunkTicks(generatorRemainingTicks);
  if (nextChunk != generatorActiveChunkTicks) {
    OCR2A = generatorCompareForChunk(nextChunk);
    // CTC has already cleared the counter. Reset explicitly only when TOP
    // changes, so a short remainder can never be missed after ISR latency.
    TCNT2 = 0;
  }
  generatorActiveChunkTicks = nextChunk;
}

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
  if (acquisitionUsesContinuousGenerator) {
    // Capture the physical D8 level immediately before starting ADC k.
    // If Timer2 and Timer1 were both pending, AVR interrupt priority/order has
    // already determined the level observed here; no theoretical reconstruction
    // is attempted.
    pendingSampleLevelHigh = generatorPinIsHigh();
  } else if (activeConfig.generationType == GENERATION_STEP) {
    if (acquiredCount == activeConfig.parameter1) {
      setStepLevelDirect(highLevelHigh());
    }
  } else if (acquiredCount == nextSquareTransitionIndex) {
    // Equivalent to generated_level(): final index stays LOW; otherwise the
    // integer half-period phase selects HIGH for even phases and LOW for odd.
    if (acquiredCount == activeConfig.sampleCount - 1) {
      setStepLevelDirect(lowLevelHigh());
    } else {
      const uint32_t phase = acquiredCount / activeConfig.parameter1;
      setStepLevelDirect((phase & 1UL) == 0 ? highLevelHigh() : lowLevelHigh());
      nextSquareTransitionIndex += activeConfig.parameter1;
    }
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
  generatorLevelRing[ringHead] = pendingSampleLevelHigh ? 1 : 0;
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
  pinMode(GENERATOR_PIN, OUTPUT);
  digitalWrite(GENERATOR_PIN, LOW);
  generatorOutputRegister = portOutputRegister(digitalPinToPort(GENERATOR_PIN));
  generatorInputRegister = portInputRegister(digitalPinToPort(GENERATOR_PIN));
  generatorBitMask = digitalPinToBitMask(GENERATOR_PIN);
  stopGenerator();
  Serial.begin(BAUD_RATE);
}

void loop() {
  while (Serial.available() > 0) {
    receiver.feed(static_cast<uint8_t>(Serial.read()));
  }
  serviceGenerator();
  serviceAcquisition();
}
