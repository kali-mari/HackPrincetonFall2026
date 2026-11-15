// Smart AAC Board - everything on the Arduino UNO Q's microcontroller.
//
// Buttons (INPUT_PULLUP, each wired between its pin and GND, pressed = LOW):
//   D2 PREV, D3 NEXT, D4 WORD -> SELECT, D5 DEL -> DELETE, D6 SAY -> SPEAK
//   PREV + NEXT held together -> LISTEN (caregiver toggles listen mode)
// Each press is sent to the Linux side as aac_token("<TOKEN>") through the Bridge.
//
// 16x2 LCD (LCD1602, parallel, 4-bit mode):
//   RS->D7, E->D8, D4->D9, D5->D10, D6->D11, D7->D12, RW->GND.
// The Linux side calls lcd_line(row, text) through the Bridge.
//
// The Linux side is hardware/unoq_bridge.py.
//
// The HD44780 driver is written out here instead of using the LiquidCrystal library,
// so the board does not have to download a library to build the sketch.

#include <Arduino_RouterBridge.h>

const uint8_t PIN_RS = 7;
const uint8_t PIN_E = 8;
const uint8_t PIN_DATA[4] = {9, 10, 11, 12}; // LCD D4..D7

void lcdNibble(uint8_t nibble) {
  for (uint8_t i = 0; i < 4; i++) {
    digitalWrite(PIN_DATA[i], (nibble >> i) & 1);
  }
  delayMicroseconds(50);  // data settles before the clock pulse
  digitalWrite(PIN_E, HIGH);
  delayMicroseconds(50);  // long pulse: the board drives 3.3V into a 5V display
  digitalWrite(PIN_E, LOW);
  delayMicroseconds(200); // let the controller finish the command
}

void lcdSend(uint8_t value, bool isData) {
  digitalWrite(PIN_RS, isData ? HIGH : LOW);
  lcdNibble(value >> 4);
  lcdNibble(value & 0x0F);
}

void lcdCommand(uint8_t value) {
  lcdSend(value, false);
}

// Puts the controller back into a known 4-bit state without clearing the text.
// Run before every update so one missed pulse cannot leave the display scrambled.
void lcdResync() {
  digitalWrite(PIN_RS, LOW);
  lcdNibble(0x03);
  delay(5);
  lcdNibble(0x03);
  delay(5);
  lcdNibble(0x03);
  delay(1);
  lcdNibble(0x02);
  lcdCommand(0x28); // 4-bit, 2 lines, 5x8 font
  lcdCommand(0x0C); // display on, cursor off
  lcdCommand(0x06); // write left to right
}

void lcdPrintRow(uint8_t row, const char* text) {
  lcdResync();
  lcdCommand(row == 0 ? 0x80 : 0xC0); // start of line 1 or line 2
  bool ended = false;
  for (uint8_t i = 0; i < 16; i++) {
    if (!ended && text[i] == '\0') ended = true;
    lcdSend(ended ? ' ' : text[i], true); // pad to 16 so old text is erased
  }
}

void lcdBegin() {
  pinMode(PIN_RS, OUTPUT);
  pinMode(PIN_E, OUTPUT);
  for (uint8_t i = 0; i < 4; i++) pinMode(PIN_DATA[i], OUTPUT);
  digitalWrite(PIN_RS, LOW);
  digitalWrite(PIN_E, LOW);

  delay(50); // display power-up time
  lcdResync();
  lcdCommand(0x01); // clear
  delay(2);
}

// Called from Python: row 0 or 1, up to 16 characters.
void lcd_line(int row, String text) {
  lcdPrintRow(row == 0 ? 0 : 1, text.c_str());
}

// ---- Buttons (same debounce and chord logic as hardware/aac_switch) ----

const unsigned long debounceDelay = 50; // 50ms debounce window

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

  bool isDown() {
    return stableState == LOW;
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

// Listen chord: PREV and NEXT held together. Their own PREV and NEXT tokens still go
// out first and cancel each other on the scan. LISTEN fires once per chord and re-arms
// only after both buttons are released.
bool chordFired = false;

void checkChord() {
  bool prevDown = buttons[0].isDown();
  bool nextDown = buttons[1].isDown();

  if (prevDown && nextDown && !chordFired) {
    Bridge.notify("aac_token", "LISTEN");
    chordFired = true;
  } else if (!prevDown && !nextDown) {
    chordFired = false;
  }
}

void setup() {
  for (int i = 0; i < buttonCount; i++) {
    buttons[i].begin();
  }

  lcdBegin();
  lcdPrintRow(0, "AAC BOARD");
  lcdPrintRow(1, "Waiting...");

  Bridge.begin();
  Bridge.provide("lcd_line", lcd_line);
}

void loop() {
  for (int i = 0; i < buttonCount; i++) {
    if (buttons[i].wasPressed()) {
      Bridge.notify("aac_token", buttons[i].token);
    }
  }
  checkChord();
  delay(1); // let the Bridge thread run
}
