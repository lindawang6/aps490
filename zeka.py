import can
import time
import select
import sys

CONTROL_SEND = 0x159
STATUS_SEND = 0X15C
ACK_ID = 0x459
STATUS_ID = 0x45C

class Zeka:
    zeka_precharge_done = False
    zeka_fullstop_and_device_not_running = True
    zeka_read_voltage = 0
    zeka_read_current = 0
    old_current_set = 0

    def zeka_init(self, bus):
        print("Init")
        msg = can.Message(arbitration_id=CONTROL_SEND, data=[0x80, 0x00, 0x04, 0x00, 0x03, 0xFF, 0xFF, 0xFF], is_extended_id=False)

        try:
            bus.send(msg)
        except can.CanError:
            print("Message not sent")

    def zeka_start(self, bus):
        print("Start")
        msg = can.Message(arbitration_id=CONTROL_SEND, data=[0x80, 0x01, 0x01, 0x00, 0x03, 0xFF, 0xFF, 0xFF], is_extended_id=False)

        try: 
            bus.send(msg)
        except can.CanError:
            print("Message not sent")

    def zeka_stop(self, bus):
        print("Stop")
        msg = can.Message(arbitration_id=CONTROL_SEND, data=[0x80, 0x01, 0x04, 0x00, 0x03, 0xFF, 0xFF, 0xFF], is_extended_id=False)

        try:
            bus.send(msg)
        except can.CanError:
            print("Message not sent")

    def zeka_set_voltage_current(self, bus, voltage, current):
        print("Set voltage and current")
        voltage = int(voltage * 10)
        current = int(current * 10)
        a_to_b_ctrl = [0x83, voltage>>8, voltage & 0x00FF, current>>8, current & 0x00FF, 0xFF, 0xFF, 0xFF]
        msg = can.Message(arbitration_id=CONTROL_SEND, data=a_to_b_ctrl, is_extended_id=False)

        try:
            bus.send(msg)
        except can.CanError:
            print("Message not sent")

    def zeka_main_status(self, bus):
        print("Main status")
        msg = can.Message(arbitration_id=STATUS_SEND, data=[0xA0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], is_extended_id=False)

        try:
            bus.send(msg)
            print(f"Message sent on {bus.channel_info}")
        except can.CanError:
            print("Message not sent")

    def zeka_feedback_status(self, bus):
#        print("Feedback status for side B")
        msg = can.Message(arbitration_id=STATUS_SEND, data=[0xA2, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], is_extended_id=False)

        try:
            bus.send(msg)
        except can.CanError:
            print("Message not sent")

    def zeka_receive(self, bus):
        msg = bus.recv()

        if msg.arbitration_id == ACK_ID:
            if msg.data[0] == 0x80:
                zeka_prev_msg = 0x80
            elif msg.data[0] == 0x83:
                zeka_prev_msg = 0x83

        elif msg.arbitration_id == STATUS_ID:
            if msg.data[0] == 0xA0:
                if (msg.data[2] & 0b00000011) == 0b000:
                    self.zeka_precharge_done = True
                else:
                    self.zeka_precharge_done = False

                if (msg.data[2] & 0b01000100) == 0b01000000:
                    self.zeka_fullstop_and_device_not_running = True
                else:
                    self.zeka_fullstop_and_device_not_running = False

                zeka_prev_msg = 0xA0

            if msg.data[0] == 0xA2:
                self.zeka_read_voltage = ((msg.data[1]<<8) | msg.data[2]) * 0.1 # 0.1V
                self.zeka_read_current = ((msg.data[3]<<8) | msg.data[4]) * 0.1 # 0.1A

                zeka_prev_msg = 0xA2

    def controller(self, bus, v_set, c_set):
       current_set = 0
       if self.zeka_read_voltage > v_set and self.zeka_read_voltage < v_set + 5:
           current_set = c_set
       elif self.zeka_read_voltage > v_set + 5:
           current_set = c_set - 0.1
       elif self.zeka_read_voltage > v_set - 5 and self.zeka_read_voltage < v_set:
           current_set = c_set + 0.1
       elif self.zeka_read_voltage < v_set - 5:
           current_set = c_set + 0.2

       if current_set != self.old_current_set:
           self.zeka_set_voltage_current(bus, v_set + 50, current_set)
           self.zeka_receive(bus)

       self.old_current_set = current_set

if __name__ == "__main__":
    manual = False

    bus = can.interface.Bus(bustype='slcan', channel='/dev/cu.usbmodem14101', bitrate=500000)
    zeka_obj = Zeka()

    zeka_obj.zeka_init(bus)
    zeka_obj.zeka_receive(bus)
    while not zeka_obj.zeka_precharge_done:
        zeka_obj.zeka_main_status(bus)
        zeka_obj.zeka_receive(bus)
        time.sleep(1)
    zeka_obj.zeka_set_voltage_current(bus, 550, 3)
    zeka_obj.zeka_receive(bus)
    zeka_obj.zeka_start(bus)
    zeka_obj.zeka_receive(bus)

    current_set = 3.0
    while True:
        zeka_obj.zeka_feedback_status(bus)
        zeka_obj.zeka_receive(bus)
        time.sleep(0.5)
        if manual and sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            line = sys.stdin.readline()
            if line:
                tmp = line.strip().split(" ")
                current = float(tmp[0])
                voltage = float(tmp[1])
                zeka_obj.zeka_set_voltage_current(bus, voltage, current)
                zeka_obj.zeka_receive(bus)
        else:
            if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                if line:
                    current_set = float(line.strip())
                    zeka_obj.controller(bus, 500, current_set)
            else:
                zeka_obj.controller(bus, 500, current_set)

    zeka_obj.zeka_stop(bus)
