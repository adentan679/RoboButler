#pragma once
class Servo {
  bool attached_ = false;
public:
  int lastPulse = 0;
  bool attached() { return attached_; }
  void attach(int, int=544, int=2400) { attached_ = true; }
  void writeMicroseconds(int us) { lastPulse=us; }
};
