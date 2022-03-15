#!/usr/bin/env python3

import sys
import socket
import pickle
import curses
import signal

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

def signal_handler(sig, frame):
    curses.endwin()
    s.close()
    sys.exit(0)

if __name__ == "__main__":
    s.connect(("127.0.0.1", int(sys.argv[1])))
    signal.signal(signal.SIGINT, signal_handler)
    stdscr = curses.initscr()

    while True:
        data = s.recv(4096)
        if len(data) == 0:
            continue
        visualization_info = pickle.loads(data)

        stdscr.clear()
        stdscr.addstr(0, 0, "Current time: " + visualization_info["current_time"])
        stdscr.addstr(1, 0, "Building consumption: " + str(visualization_info["building_power"]))
        i = 2
        for station_num, car in visualization_info["cars"].items():
            if car == "empty":
                stdscr.addstr(i, 0, "Station: " + str(station_num) + " Status: empty")
            else:
                stdscr.addstr(i, 0, "Station: " + str(station_num) + " Name: " + str(car["name"]) + " SoC remaining(%): " + str(car["delta_soc"]) + " Current(A): " + str(car["current"]) + " Battery: " + str(car["battery"]) + " Remaining time: " + str(car["remaining_time"]))
            i += 1
        stdscr.refresh()
