/*
  Happy Birthday - light show  (Arduino UNO R4 WiFi + 8-channel relay)

  The 7 lights flash with the Happy Birthday melody. Each note of the song
  switches ON one light for as long as the note lasts:

      note  C  D  E  F  G  A  B
      light 1  2  3  4  5  6  7      (same note in any octave = same light)

  The fan relay is NOT used. Relays are active LOW (LOW = light ON).
  Optional: a passive buzzer on pin D10 plays the real tune (see BUZZER_PIN).

  Note: this sketch replaces SmartNest on the board. Upload smartnest_v2 again
  afterwards to get the home control back.
*/

// ---------- Relay pins (same wiring as SmartNest) ----------
// order = notes C D E F G A B  ->  Bulb1, Bulb2, Bulb3, Bulb4, Smoke light, Temp light, Dark light
const uint8_t LIGHT_PIN[7] = {9, 6, 7, 5, 4, 3, 2};
const uint8_t FAN_PIN = 8;               // kept OFF the whole time

// ---------- Optional buzzer ----------
const int BUZZER_PIN = 10;               // passive buzzer: + to D10, - to GND. Set to -1 if you have none.

// ---------- Song settings ----------
const unsigned int UNIT_MS = 125;        // length of one sixteenth note. Bigger = slower song
const unsigned int GAP_MS  = 25;         // short pause between notes so repeated notes are visible
const unsigned long PAUSE_BETWEEN_PLAYS_MS = 5000;

struct Note {
  uint16_t freq;     // Hz
  uint8_t  units;    // length in sixteenths
  int8_t   light;    // 0..6 (C..B)
};

// Notes: C=0 D=1 E=2 F=3 G=4 A=5 B=6
#define C4 262
#define D4 294
#define E4 330
#define F4 349
#define G4 392
#define A4 440
#define B4 494
#define C5 523
#define D5 587
#define E5 659
#define F5 698
#define G5 784

const Note SONG[] = {
  // Happy birthday to you
  {G4, 3, 4}, {G4, 1, 4}, {A4, 4, 5}, {G4, 4, 4}, {C5, 4, 0}, {B4, 8, 6},
  // Happy birthday to you
  {G4, 3, 4}, {G4, 1, 4}, {A4, 4, 5}, {G4, 4, 4}, {D5, 4, 1}, {C5, 8, 0},
  // Happy birthday dear (name)
  {G4, 3, 4}, {G4, 1, 4}, {G5, 4, 4}, {E5, 4, 2}, {C5, 4, 0}, {B4, 4, 6}, {A4, 4, 5},
  // Happy birthday to you
  {F5, 3, 3}, {F5, 1, 3}, {E5, 4, 2}, {C5, 4, 0}, {D5, 4, 1}, {C5, 8, 0},
};
const int SONG_LEN = sizeof(SONG) / sizeof(SONG[0]);

// ---------- Helpers ----------
void lightOn(int i)  { digitalWrite(LIGHT_PIN[i], LOW); }    // active LOW
void lightOff(int i) { digitalWrite(LIGHT_PIN[i], HIGH); }

void allLights(bool on) {
  for (int i = 0; i < 7; i++) digitalWrite(LIGHT_PIN[i], on ? LOW : HIGH);
}

void playNote(const Note &n) {
  digitalWrite(FAN_PIN, HIGH);            // keep the fan OFF
  unsigned long total = (unsigned long)n.units * UNIT_MS;
  unsigned long on = total > GAP_MS ? total - GAP_MS : total;
  lightOn(n.light);
  if (BUZZER_PIN >= 0) tone(BUZZER_PIN, n.freq, on);
  delay(on);
  lightOff(n.light);
  if (BUZZER_PIN >= 0) noTone(BUZZER_PIN);
  delay(total - on);
}

// Finale: lights run left to right and back, then all flash 3 times
void finale() {
  for (int i = 0; i < 7; i++)  { lightOn(i);  delay(90); lightOff(i); }
  for (int i = 6; i >= 0; i--) { lightOn(i);  delay(90); lightOff(i); }
  for (int k = 0; k < 3; k++) {
    allLights(true);
    if (BUZZER_PIN >= 0) tone(BUZZER_PIN, C5, 200);
    delay(220);
    allLights(false);
    delay(220);
  }
}

void setup() {
  // everything OFF first (HIGH) so nothing flickers when the board starts
  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, HIGH);           // fan OFF
  for (int i = 0; i < 7; i++) {
    pinMode(LIGHT_PIN[i], OUTPUT);
    digitalWrite(LIGHT_PIN[i], HIGH);
  }
  if (BUZZER_PIN >= 0) pinMode(BUZZER_PIN, OUTPUT);
  delay(2000);                            // short wait before the first play
}

void loop() {
  digitalWrite(FAN_PIN, HIGH);            // keep the fan OFF
  for (int i = 0; i < SONG_LEN; i++) playNote(SONG[i]);
  finale();
  delay(PAUSE_BETWEEN_PLAYS_MS);          // then it plays again
}
