import time
import board
import digitalio
import busio
import usb_midi
import adafruit_midi
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff

# Configuration

MTCH_ADDR = 0x20          # 0x20 if ADD_SEL tied low, 0x21 if tied high

MIDI_CHANNEL = 0       
FIXED_VELOCITY = 100

PAD_TO_NOTE = [60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71]

REG_DEVID = 0x0000  
REG_BTNSTA = 0x0102   

# Hardware setup

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
    time.sleep(0.30)         

def _reg_addr_bytes(reg):
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
    raw = data[0] | (data[1] << 8)    
    return raw & 0x0FFF             


def check_device_id():
    devid = i2c_read(REG_DEVID, 1)[0]
    if devid != 0x0B:
        print("WARNING: DEVID read 0x%02X, expected 0x0B." % devid)
        print("Check wiring, MTCH_ADDR, and the register-address byte")
        print("order noted in the comments at the top of this file.")
    else:
        print("MTCH2120 detected OK (DEVID=0x0B).")

# Main loop

hardware_reset()
check_device_id()

prev_mask = 0

while True:
  
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
