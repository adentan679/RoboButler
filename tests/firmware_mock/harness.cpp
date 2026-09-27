// Executes the actual .ino with a simulated Arduino clock, pins, Serial and Servo.
#include <iostream>
#include <sstream>
#include <string>
#include <deque>
#include <cassert>
#define HIGH 1
#define LOW 0
#define OUTPUT 1
unsigned long clockUs=0;
int stepRises=0, stepPin=0;
unsigned long millis() { return clockUs/1000; }
unsigned long micros() { return clockUs; }
void pinMode(int,int) {}
void digitalWrite(int pin,int level) {
  if(pin==3) { if(level && !stepPin) stepRises++; stepPin=level; }
}
long map(long x,long a,long b,long c,long d) { return (x-a)*(d-c)/(b-a)+c; }
class MockSerial {
public:
  std::deque<char> input;
  std::ostringstream output;
  void begin(int) {}
  int available() { return input.size(); }
  int read() { char c=input.front(); input.pop_front(); return c; }
  template<class T> void print(T value) { output<<value; }
  template<class T> void println(T value) { output<<value<<"\n"; }
} Serial;
#include "../../software/arduino/project_servo_stepper/project_servo_stepper.ino"
void send(std::string s) {
  for(char c:s+"\n") Serial.input.push_back(c);
  while(Serial.available()) loop();
}
void tick(unsigned long ms) {
  for(unsigned long n=0;n<ms*10;n++) { clockUs+=100; loop(); }
}
void contains(std::string s) { assert(Serial.output.str().find(s)!=std::string::npos); }
int main() {
  setup(); assert(position==UNKNOWN); assert(!myServo.attached());
  send("HELLO"); contains("READY ROBOBUTLER1");
  send("1 STOW"); contains("DONE 1 STOWED");
  send("2 Command_2"); contains("ACK 2");
  assert(motion==SERVO_WAIT); assert(myServo.lastPulse==1166);
  tick(1500); contains("DONE 2 EXTENDED"); assert(position==EXTENDED);
  assert(stepRises==300);
  send("PING"); send("3 RETURN"); tick(700);
  contains("DONE 3 RETRACTED_UNVERIFIED"); assert(position==RETRACTED_UNVERIFIED);
  assert(stepRises==600);
  send("4 STOW"); assert(position==STOWED);
  send("5 Command_4"); tick(850); assert(motion==STEPPING);
  send("STOP"); int before=stepRises; tick(100);
  assert(motion==IDLE && position==UNKNOWN && stepPin==LOW && stepRises==before);
  send("6 STOW"); send("7 Command_1"); send("8 Command_2");
  contains("FAULT BUSY"); assert(motion==IDLE);
  send("9 STOW"); send("9 STOW"); contains("FAULT BAD_ID");
  send("10 STOW"); send("PING"); tick(2100);
  contains("FAULT LINK_TIMEOUT"); assert(position==UNKNOWN);
  send("HELLO"); send(std::string(80,'x')); contains("FAULT LINE_TOO_LONG");
  std::cout<<"PASS native firmware: handshake, no boot motion, selection, 300 pulses each way,\n"
           <<"unverified retraction, STOP, busy rejection, IDs, timeout, bounded parser.\n";
}
