// Smart AAC Board - production switch sketch (Elegoo UNO R3 / Arduino Uno)
// Prints one protocol token per line at 9600 baud for hardware/bridge.py:
//   D2 PREV -> PREV, D3 NEXT -> NEXT, D4 WORD -> SELECT, D5 DEL -> DELETE, D6 SAY -> SPEAK
//   A0 sound sensor (optional vocal switch) -> VOICE
// Buttons use INPUT_PULLUP: wire each between its pin and GND (pressed = LOW).
// Wiring check lives in hardware/test/test.ino.

// Set to true to also print sound levels once a second (the bridge ignores these lines).
const bool DEBUG = false;

// Vocal switch calibration: VOICE fires once when the A0 level stays above
// SOUND_THRESHOLD for SOUND_HOLD_MS. Dips shorter than SOUND_GAP_MS do not reset the
// timer (the sensor output wobbles even during a steady sound). After firing, the level
// must stay below the threshold for SOUND_GAP_MS before it can fire again.
const int SOUND_THRESHOLD = 400;
const unsigned long SOUND_HOLD_MS = 500;
const unsigned long SOUND_GAP_MS = 100;

const int soundPin = A0;
const unsigned long debounceDelay = 50; // 50ms debounce window

// Debounced active-LOW button (same approach as hardware/test/test.ino)
struct DebouncedButton {
  int pin;
  const char* token;
  int stableState;
  int lastReading;
  unsigned long lastDebounceTime;

  DebouncedButton(int p, const char* t)
    : pin(p), token(t), stableState(HIGH), lastReading(HIGH), lastDebounceTime(0) {}

  void begin() {
    pinMode(pin, INPUT_PULLUP);
  }

  // Returns true ONLY on the press edge
  bool wasPressed() {
    bool triggered = false;
    int reading = digitalRead(pin);

    if (reading != lastReading) {
      lastDebounceTime = millis();
    }

    if ((millis() - lastDebounceTime) > debounceDelay) {
      if (reading != stableState) {
        stableState = reading;
        if (stableState == LOW) {
          triggered = true;
        }
      }
    }

    lastReading = reading;
    return triggered;
  }
};

DebouncedButton buttons[] = {
  DebouncedButton(2, "PREV"),
  DebouncedButton(3, "NEXT"),
  DebouncedButton(4, "SELECT"),
  DebouncedButton(5, "DELETE"),
  DebouncedButton(6, "SPEAK"),
};
const int buttonCount = sizeof(buttons) / sizeof(buttons[0]);

bool soundActive = false;       // inside a loud stretch
bool soundFired = false;        // VOICE already sent for this stretch
unsigned long soundStart = 0;   // when the loud stretch began
unsigned long lastLoudTime = 0; // last sample above the threshold
unsigned long lastDebugTime = 0;

void checkSound() {
  unsigned long now = millis();
  int level = analogRead(soundPin);

  if (level > SOUND_THRESHOLD) {
    if (!soundActive) {
      soundActive = true;
      soundStart = now;
    }
    lastLoudTime = now;
    if (!soundFired && now - soundStart >= SOUND_HOLD_MS) {
      Serial.println("VOICE");
      soundFired = true;
    }
  } else if (soundActive && now - lastLoudTime > SOUND_GAP_MS) {
    // Quiet long enough: the stretch is over and the switch re-arms
    soundActive = false;
    soundFired = false;
  }

  if (DEBUG && now - lastDebugTime >= 1000) {
    lastDebugTime = now;
    Serial.print("# sound ");
    Serial.println(level);
  }
}

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < buttonCount; i++) {
    buttons[i].begin();
  }
}

void loop() {
  for (int i = 0; i < buttonCount; i++) {
    if (buttons[i].wasPressed()) {
      Serial.println(buttons[i].token);
    }
  }
  checkSound();
}
