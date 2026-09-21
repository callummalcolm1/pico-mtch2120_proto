"""
RP2040 + MTCH2120 (12-channel capacitive touch) -> USB MIDI
CircuitPython firmware

Wiring (as specified):
  GPIO20 (pin 31) -> MTCH2120 SDA
  GPIO21 (pin 32) -> MTCH2120 SCL
  GPIO22 (pin 34) -> MTCH2120 INT
  GPIO23 (pin 35) -> MTCH2120 RESET (active-low)

Requires this library in your CIRCUITPY/lib folder (from the Adafruit
CircuitPython Bundle matching your CircuitPython version):
    adafruit_midi

Install it either by:
  - copying lib/adafruit_midi/ from the bundle onto CIRCUITPY/lib/, or
  - `circup install adafruit_midi` if you use circup.

Save this file as CIRCUITPY/code.py. As soon as it's saved, the board
will reboot and enumerate as a USB MIDI device.

ASSUMPTIONS / THINGS TO VERIFY ON FIRST RUN
---------------------------------------------------------------------
1. I2C address: the MTCH2120's ADD_SEL pin selects 0x20 (tied low) or
   0x21 (tied high). This defaults to 0x20 -- change MTCH_ADDR below if
   your board ties ADD_SEL high.
2. Register-ADDRESS byte order: the datasheet (DS40002613B) confirms
   register *data* is little-endian (low byte at the lower memory
   address), but its text doesn't show an example bus trace for how the
   16-bit *register address* itself is clocked out. This script sends
   it MSB-first, which is the common convention for Microchip/most I2C
   devices using 16-bit addressing. The DEVID check at startup will
   immediately tell you if this assumption is wrong -- if you see the
   warning below, try swapping the byte order in _reg_addr_bytes().
3. Assumes no external pull-up resistor is on INT; an internal pull-up
   is enabled in software. If your PCB already has one, that's fine too
   (harmless redundancy). SDA/SCL need pull-ups (external, or your
   board's I2C bus may already provide them).
---------------------------------------------------------------------
"""

import time
import board
import digitalio
import busio
import usb_midi
import adafruit_midi
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

MTCH_ADDR = 0x20          # 0x20 if ADD_SEL tied low, 0x21 if tied high

MIDI_CHANNEL = 0          # zero-indexed -> MIDI channel 1
FIXED_VELOCITY = 100

# Pads 0-11 mapped like one octave of a piano keyboard starting at C4
# (MIDI note 60). Edit this list to change the layout, octave, or to use
# a non-consecutive note set.
PAD_TO_NOTE = [60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71]
#              C4  C#4 D4  D#4 E4  F4  F#4 G4  G#4 A4  A#4 B4

# MTCH2120 register offsets (from datasheet DS40002613B, section 4.2)
REG_DEVID = 0x0000   # 1 byte,  expected reset value 0x0B
REG_BTNSTA = 0x0102   # 2 bytes, bit n = 1 -> button n touched (n = 0..11)

# ---------------------------------------------------------------------
# Hardware setup
# ---------------------------------------------------------------------

i2c = busio.I2C(board.GP21, board.GP20)            # SCL, SDA

reset_pin = digitalio.DigitalInOut(board.GP23)
reset_pin.direction = digitalio.Direction.OUTPUT
reset_pin.value = True                              # idle high (not in reset)

int_pin = digitalio.DigitalInOut(board.GP22)
int_pin.direction = digitalio.Direction.INPUT
int_pin.pull = digitalio.Pull.UP                     # INT is active-low, open-drain

midi = adafruit_midi.MIDI(midi_out=usb_midi.ports[1], out_channel=MIDI_CHANNEL)


def hardware_reset():
    reset_pin.value = False
    time.sleep(0.01)          # 10 ms low pulse
    reset_pin.value = True
    time.sleep(0.30)          # datasheet: init takes ~250 ms typical


def _reg_addr_bytes(reg):
    # MSB-first 16-bit register address -- see assumption #2 above.
    return bytes([(reg >> 8) & 0xFF, reg & 0xFF])


def i2c_read(reg, nbytes):
    buf = bytearray(nbytes)
    while not i2c.try_lock():
        pass
    try:
        i2c.writeto(MTCH_ADDR, _reg_addr_bytes(reg), stop=False)
        i2c.readfrom_into(MTCH_ADDR, buf)
    finally:
        i2c.unlock()
    return buf


def read_button_status():
    """Returns a 12-bit mask; bit n = 1 if pad n is currently touched."""
    data = i2c_read(REG_BTNSTA, 2)
    raw = data[0] | (data[1] << 8)    # register data is little-endian
    return raw & 0x0FFF               # bits 0-11 = the 12 physical buttons


def check_device_id():
    devid = i2c_read(REG_DEVID, 1)[0]
    if devid != 0x0B:
        print("WARNING: DEVID read 0x%02X, expected 0x0B." % devid)
        print("Check wiring, MTCH_ADDR, and the register-address byte")
        print("order noted in the comments at the top of this file.")
    else:
        print("MTCH2120 detected OK (DEVID=0x0B).")


# ---------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------

hardware_reset()
check_device_id()

prev_mask = 0

while True:
    # INT is pulled low by the MTCH2120 whenever any button's touch
    # state changes, and stays low until the host reads BTNSTA (or
    # SENSTATE). Only touch the I2C bus when INT is asserted, so the
    # bus is otherwise idle.
    if not int_pin.value:
        mask = read_button_status()
        changed = mask ^ prev_mask

        for pad in range(12):
            bit = 1 << pad
            if changed & bit:
                note = PAD_TO_NOTE[pad]
                if mask & bit:
                    midi.send(NoteOn(note, FIXED_VELOCITY))
                else:
                    midi.send(NoteOff(note, 0))

        prev_mask = mask

    time.sleep(0.001)
