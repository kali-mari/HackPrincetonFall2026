// Smart AAC Board - 5-Button & Sound Sensor Hardware Test (Elegoo / Arduino Uno R3)
// Pinout:
//   D2 - PREV (Navigate backward / up)
//   D3 - NEXT (Navigate forward / down)
//   D4 - WORD (Select / Enter word)
//   D5 - DEL  (Delete / Backspace)
//   D6 - SAY  (Speak full sentence)
//   A0 - Sound Sensor (Voice switch)

const int pinPrev  = 2;
const int pinNext  = 3;
const int pinWord  = 4;
const int pinDel   = 5;
const int pinSay   = 6;
const int soundPin = A0; // Set to A0 (or change to A1 if using A1)

const unsigned long debounceDelay = 50; // 50ms debounce window

// Reusable structure for debounced active-LOW buttons (INPUT_PULLUP)
struct DebouncedButton {
  int pin;
  const char* label;
  int stableState;
  int lastReading;
  unsigned long lastDebounceTime;

  DebouncedButton(int p, const char* lbl)
    : pin(p), label(lbl), stableState(HIGH), lastReading(HIGH), lastDebounceTime(0) {}

  void begin() {
    pinMode(pin, INPUT_PULLUP); // Internal pull-up: HIGH = unpressed, LOW = pressed
  }

  // Returns true ONLY on the falling edge (the moment button is pressed down)
  bool wasPressed() {
    bool triggered = false;
    int reading = digitalRead(pin);

    if (reading != lastReading) {
      lastDebounceTime = millis();
    }

    if ((millis() - lastDebounceTime) > debounceDelay) {
      if (reading != stableState) {
        stableState = reading;
        // With INPUT_PULLUP, LOW means the button is pressed (connected to GND)
        if (stableState == LOW) {
          triggered = true;
        }
      }
    }

    lastReading = reading;
    return triggered;
  }
};

// Instantiate all 5 buttons
DebouncedButton btnPrev(pinPrev, "PREV (Navigate Backward)");
DebouncedButton btnNext(pinNext, "NEXT (Navigate Forward)");
DebouncedButton btnWord(pinWord, "WORD (Enter / Select Word)");
DebouncedButton btnDel(pinDel,   "DELETE (Backspace)");
DebouncedButton btnSay(pinSay,   "SAY (Speak Sentence)");

unsigned long lastTelemetryTime = 0;

void setup() {
  // 9600 baud matches the project spec and standard Arduino IDE Serial Monitor
  Serial.begin(9600);

  btnPrev.begin();
  btnNext.begin();
  btnWord.begin();
  btnDel.begin();
  btnSay.begin();

  Serial.println("==================================================");
  Serial.println("  Smart AAC Board - 5-Button Hardware Test Ready  ");
  Serial.println("==================================================");
  Serial.println("Wiring Check (INPUT_PULLUP mode):");
  Serial.println("  - D2: PREV        (Col 8)");
  Serial.println("  - D3: NEXT        (Col 20)");
  Serial.println("  - D4: ENTER WORD  (Col 32)");
  Serial.println("  - D5: DELETE      (Col 44)");
  Serial.println("  - D6: SAY ALL     (Col 56)");
  Serial.println("  - A0: Sound Sensor");
  Serial.println("  - GND: Breadboard (-) Blue Rail");
  Serial.println("Press any button to test...");
  Serial.println("--------------------------------------------------");
}

void loop() {
  // 1. Check all 5 buttons (debounced, non-blocking)
  if (btnPrev.wasPressed()) {
    Serial.println(">>> [D2] PREV Button Pressed!");
  }
  if (btnNext.wasPressed()) {
    Serial.println(">>> [D3] NEXT Button Pressed!");
  }
  if (btnWord.wasPressed()) {
    Serial.println(">>> [D4] ENTER WORD Button Pressed!");
  }
  if (btnDel.wasPressed()) {
    Serial.println(">>> [D5] DELETE Button Pressed!");
  }
  if (btnSay.wasPressed()) {
    Serial.println(">>> [D6] SAY SENTENCE Button Pressed!");
  }

  // 2. Periodic status / sound telemetry every 1000ms (avoids flooding serial monitor)
  if (millis() - lastTelemetryTime >= 1000) {
    lastTelemetryTime = millis();
    int soundVal = analogRead(soundPin);
    
    Serial.print("[Live Status] Sound Level: ");
    Serial.print(soundVal);
    Serial.print(" | Buttons (P,N,W,D,S): ");
    Serial.print(btnPrev.stableState == LOW ? "1" : "0");
    Serial.print(",");
    Serial.print(btnNext.stableState == LOW ? "1" : "0");
    Serial.print(",");
    Serial.print(btnWord.stableState == LOW ? "1" : "0");
    Serial.print(",");
    Serial.print(btnDel.stableState == LOW ? "1" : "0");
    Serial.print(",");
    Serial.println(btnSay.stableState == LOW ? "1" : "0");
  }
}
