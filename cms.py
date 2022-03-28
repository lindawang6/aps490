#!/usr/bin/env python3

import sys
import socket
import pickle
import argparse
import can
import os
import subprocess
from threading import Thread, Lock, Condition
from time import time, sleep
from serial import Serial
from random import randint

import zeka

# ip_address = "169.254.36.234"
ip_address = "127.0.0.1"

DEBUG = True

VOLTAGE = 208
ZEKA_VOLTAGE = 500
EFFICIENCY = 0.9

BATTERY_CAPACITY = 10
# Lithium ion batteries should charge at 0.8C
BATTERY_CHARGING_CURRENT = (BATTERY_CAPACITY * 1000 / VOLTAGE) * 0.8

CONTROL_DELAY = 6 # 6 seconds
READ_DELAY = 2 # 2 seconds

FAST_CONTROL_DELAY =  0.006
FAST_READ_DELAY = 0.002

MAKE_MODEL = {"nissan leaf": 24,
              "tesla model y": 75,
              "chevrolet bolt": 65,
              "renault zoe": 52,
              "tesla model 3": 54,
              "tesla model s": 90,
              "tesla model x": 100}

openevse = None
zeka_bus = None
i = 0
num_stations = 0
station_number = 1
start = ""
low_current_num = 0

building_dataset = []
car_dataset = []

max_building = 0

cars = []
cars_mutex = Lock()
stations = []

wait = Condition()

class Car:
    name = ""
    simulation = True
    sleep_mode = False
    priority = 0
    delta_kWh = 0 # desired delta SoC * total capacity
    departure = 0
    min_current = 6
    max_current = 24 # 24A for L1 
    charging_current = 0
    battery_current = 0
    battery_on = False
    make_model = ""
    capacity = 0
    station_no = -1
    battery_no = -1
    prev_current = 0
    measured_current = 0

class Station:
    station_no = -1
    battery_capacity = BATTERY_CAPACITY
    battery_current = 0
    charging_current = 0

    def __init__ (self, station_no, battery_capacity=BATTERY_CAPACITY, battery_current=0, charging_current=0):
        self.station_no = station_no
        self.battery_capacity = battery_capacity
        self.battery_current = battery_current
        self.charging_current = charging_current

def str_to_int(string):
    start_time = start.split(":")
    current_time = string.split(":")
    start_time = int(start_time[0]) * 3600 + int(start_time[1]) * 60 + int(start_time[2])
    current_time = int(current_time[0]) * 3600 + int(current_time[1]) * 60 + int(current_time[2])
    return (current_time - start_time) % 86400

def int_to_str(integer):
    start_time = start.split(":")
    start_time = int(start_time[0]) * 3600 + int(start_time[1]) * 60 + int(start_time[2])
    current_time = (integer + start_time) % 86400
    hours = current_time // 3600
    minutes = (current_time - (hours * 3600)) // 60
    seconds = current_time - hours * 3600 - minutes * 60
    return str(hours).zfill(2) + ":" + str(minutes).zfill(2) + ":" + str(seconds).zfill(2) 

def read(fast_sim, log):
    # delay in seconds
    global i
    global stations
    global low_current_num

    while i < len(building_dataset):
        start_loop = time()
        if i % CONTROL_DELAY // READ_DELAY == 0:
            wait.acquire()
            wait.notify()
            wait.release()

        cars_mutex.acquire()

        # read building power
        # building dataset in kW
        available_current = (max_building - building_dataset[i]) * 1000 / VOLTAGE 

        # read current (read from openevse or dataset for simulation)
        for car in cars:
            if car.simulation:
                measured_current = car.charging_current * EFFICIENCY
            else:
                cmd = b"$GG\r"
                if openevse.is_open:
                    openevse.write(cmd)
                while openevse.in_waiting == 0:
                    pass
                if openevse.in_waiting > 0:
                    msg = openevse.read(openevse.in_waiting)
                try:
                    measured_current = float(msg.decode().split(" ")[1]) / 1000
                except Exception as e:
                    measured_current = car.charging_current * EFFICIENCY
            car.measured_current = measured_current
            car.delta_kWh -= measured_current * VOLTAGE * (READ_DELAY / 3600) * 0.001
            if car.delta_kWh < 0:
                car.delta_kWh = 0

            # check saturation
            if not car.simulation:
                if measured_current > 0 and measured_current <= car.charging_current * (EFFICIENCY - 0.1):
                    low_current_num = low_current_num + 1
                else:
                    low_current_num = 0

                if low_current_num >= 10:
                    car.max_current = measured_current
                    low_current_num = 0

        for station in stations:
            station.battery_capacity -= station.battery_current * VOLTAGE * (READ_DELAY / 3600) * 0.001 * (1.0/EFFICIENCY)
            station.battery_capacity += station.charging_current * VOLTAGE * (READ_DELAY / 3600) * 0.001 * EFFICIENCY
            station.battery_current = 0

        # assign current (cars are already sorted from highest priority to lowest priority)
        remove_cars = 0
        used_current = 0
        for car in cars:
            car.prev_current = car.charging_current
            car.charging_current = int(available_current * car.priority)

            car.battery_no = -1
            car.battery_current = 0

            if car.priority == 0:
                pass
            elif car.battery_on:
                not_max = False
                if car.charging_current < car.max_current:
                    if not car.simulation:
                        if stations[0].battery_capacity > car.max_current * VOLTAGE * (READ_DELAY / 3600) * 0.001:
                            car.battery_no = 0
                            stations[0].battery_current = car.max_current - car.charging_current
                            car.battery_current = car.max_current - car.charging_current
                        else:
                            not_max = True
                    elif stations[car.station_no].battery_current == 0 and stations[car.station_no].battery_capacity > car.max_current * VOLTAGE * (READ_DELAY / 3600) * 0.001:
                        stations[car.station_no].battery_current = car.max_current - car.charging_current
                        car.battery_current = car.max_current - car.charging_current
                        car.battery_no = car.station_no
                    else:
                        stations_tmp = [station for station in stations if (station.battery_current == 0 and station.battery_capacity > car.max_current * VOLTAGE * (READ_DELAY / 3600) * 0.001 and station.station_no != 0)]
                        stations_tmp.sort(key=lambda x: x.battery_capacity, reverse=True)

                        if len(stations_tmp) > 0:
                            stations[stations_tmp[0].station_no].battery_current = car.max_current - car.charging_current
                            car.battery_current = car.max_current - car.charging_current
                            car.battery_no = stations_tmp[0].station_no
                        else:
                            print("Warn: no batteries available")
                            not_max = True
                if not not_max:
                    car.charging_current = car.max_current

            else:
                if available_current - used_current < car.min_current:
                    if car.sleep_mode:
                        car.charging_current = car.min_current

                        if not car.simulation:
                            if stations[0].battery_capacity > car.min_current * VOLTAGE * (READ_DELAY / 3600) * 0.001:
                                car.battery_no = 0
                                stations[0].battery_current = car.min_current - (available_current - used_current)
                                car.battery_current = car.min_current - (available_current - used_current)
                            else:
                                car.charging_current = 0
                        elif stations[car.station_no].battery_current == 0 and stations[car.station_no].battery_capacity > car.min_current * VOLTAGE * (READ_DELAY / 3600) * 0.001:
                            stations[car.station_no].battery_current = car.min_current - (available_current - used_current)
                            car.battery_current = car.min_current - (available_current - used_current)
                            car.battery_no = car.station_no
                        else:
                            stations_tmp = [station for station in stations if (station.battery_current == 0 and station.station_no != 0)]
                            stations_tmp.sort(key=lambda x: x.battery_capacity, reverse=True)
                            if len(stations_tmp) > 0 and stations_tmp[0].battery_capacity > car.min_current * VOLTAGE * (READ_DELAY / 3600) * 0.001:
                                stations[stations_tmp[0].station_no].battery_current = car.min_current - (available_current - used_current)
                                car.battery_current = car.min_current - (available_current - used_current)
                                car.battery_no = stations_tmp[0].station_no
                            else:
                                print("Warn: no batteries available")
                                car.charging_current = 0
                    else:
                        car.charging_current = 0
                elif car.charging_current > car.max_current:
                    car.charging_current = car.max_current
                elif car.charging_current < car.min_current:
                    car.charging_current = car.min_current

            used_current += (car.charging_current - car.battery_current)

            if car.name == "openevse" and car.charging_current != car.prev_current:
                cmd = "$SC " + str(int(car.charging_current)) + " V\r"
                if openevse.is_open:
                    openevse.write(cmd.encode())
                while openevse.in_waiting == 0:
                    pass
                if openevse.in_waiting > 0:
                    msg = openevse.read(openevse.in_waiting)

        stations_tmp = [station for station in stations if (station.battery_current == 0 and station.battery_capacity < (BATTERY_CAPACITY * 0.9))]
        stations_tmp.sort(key=lambda x: x.battery_capacity)

        for station in stations:
            station.charging_current = 0

        while available_current - used_current >= BATTERY_CHARGING_CURRENT and len(stations_tmp) > 0:
            stations[stations_tmp[0].station_no].charging_current = BATTERY_CHARGING_CURRENT
            available_current -= BATTERY_CHARGING_CURRENT
            stations_tmp.pop(0)

        # Log building current, battery current, remaining SoC
        if log:
            write_openevse = False
            current_time = int_to_str(i * READ_DELAY)
            total_power_used = 0.0
            total_building_power_used = 0.0

            for car in cars:
                file = open("logs/" + car.name + ".txt", "a")
                file.write(current_time + ", " + str(car.measured_current) + ", " + str(car.charging_current) + ", " + str(car.battery_current) + ", " + str(100 * car.delta_kWh/car.capacity) + ", " + str(car.battery_no) + ", " + str(car.priority) + "\n")
                if car.name == "openevse":
                    write_openevse = True
                total_power_used += car.charging_current * VOLTAGE
                total_building_power_used += (car.charging_current - car.battery_current) * VOLTAGE

            if not write_openevse:
                file = open("logs/openevse.txt", "a")
                file.write(current_time + ", 0, 0, 0, 0, 0, 0\n")

            for station in stations:
                if station.station_no < 10:
                    file = open("logs/" + "station0" + str(station.station_no) + ".txt", "a")
                else:
                    file = open("logs/" + "station" + str(station.station_no) + ".txt", "a")
                file.write(current_time + ", " + str(station.battery_current) + ", " + str(station.charging_current) + ", " + str(station.battery_capacity) + "\n")

            for car in car_dataset:
                file = open("logs/" + car[0] + ".txt", "a")
                file.write(current_time + ", 0, 0, 0, 0, 0, 0\n")

            file = open("logs/sim_power_use" + ".txt", "a")
            file.write(current_time + ", " + str(total_building_power_used) + ", " + str((max_building - building_dataset[i]) * 1000) + ", " + str(total_power_used) + "\n")

        cars_mutex.release()

        end_loop = time()
        offset = end_loop - start_loop

        if (offset) > READ_DELAY:
            pass
        elif fast_sim:
            sleep(FAST_READ_DELAY)
        else:
            sleep(READ_DELAY - (offset))

        i += 1

def state_control(fast_sim):
    global car_dataset
    global station_number
    while i < len(building_dataset):
        wait.acquire()
        wait.wait()
        wait.release()

        current_time = i * READ_DELAY
        time_readable = int_to_str(current_time)

        # check for new simulated cars that have arrived
        for car_data in car_dataset:
            name, arrival, departure, model, desired_soc, sleep_mode = car_data
            if int(arrival) <= current_time:
                if DEBUG:
                    print("Log: Simulated car " + name + " arrived")
                car = Car()
                car.name = name
                car.make_model = model.strip().lower()
                car.capacity = MAKE_MODEL[car.make_model]
                car.delta_kWh = int(desired_soc) * car.capacity * 0.01
                car.departure = str_to_int(departure)
                car.sleep_mode = sleep_mode.strip() == 'True'
                car.station_no = station_number
                station_number += 1
                cars_mutex.acquire()
                cars.append(car)
                cars_mutex.release()
        car_dataset = [x for x in car_dataset if int(x[1]) > current_time]

        cars_mutex.acquire()

        # check for cars that have left
        for car in cars[:]:
            if car.departure <= current_time:
                print("Car: " + str(car.name) + " left at " + str(time_readable) + " with SoC remaining(%): " + str(100 * car.delta_kWh/car.capacity))
                stations[car.battery_no].battery_current = 0
                cars.remove(car)

        # check if battery needs to be turned on
        for car in cars:
            if not car.battery_on and car.delta_kWh >= EFFICIENCY * car.max_current * VOLTAGE * 0.001 * (car.departure - current_time) / 3600:
                print("Log: Turning on battery for " + car.name)
                car.battery_on = True 

        # assign priorities
        normalize = 0
        for car in cars:
            car.priority = car.delta_kWh / (car.departure - current_time)
            normalize += car.priority
        if normalize > 0:
            for car in cars:
                car.priority = car.priority / normalize
        cars.sort(key=lambda x: (x.sleep_mode, x.priority), reverse=True)

        cars_mutex.release()

def wait_for_car(port, cont):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        print("Listening on " + str(port))
        s.bind((ip_address, port))
        s.listen()
        while i < len(building_dataset):
            conn, addr = s.accept()
            with conn:
                data = conn.recv(4096)
                if len(data) == 0:
                    continue
                car_info = pickle.loads(data)
                if DEBUG:
                    print("Log: User input received")
                if car_info["station_no"] == 0 and openevse:
                    cmd = b"$GS\r"
                    print("OpenEVSE station")

                    if openevse.is_open:
                        openevse.write(cmd)
                    while openevse.in_waiting <= 5:
                        pass
                    if openevse.in_waiting > 5:
                        msg = openevse.read(openevse.in_waiting)

                    sleep(2)

                    if openevse.is_open:
                        openevse.write(cmd)
                    while openevse.in_waiting <= 5:
                        pass
                    if openevse.in_waiting > 5:
                        msg = openevse.read(openevse.in_waiting)
                    if msg.decode()[:6] == "$OK 02" or msg.decode()[:6] == "$OK 03":
                        print("Log: Car connected")
                    else:
                        print("Warn: Car not connected. OpenEVSE returned: " + msg.decode())
                        continue

                    cmd = "$SV " + str(VOLTAGE * 1000) + "\r"
                    if openevse.is_open:
                        openevse.write(cmd.encode())
                    while openevse.in_waiting == 0:
                        pass
                    if openevse.in_waiting > 0:
                        msg = openevse.read(openevse.in_waiting)

                    if not cont:
                        car = Car()
                        car.name = "openevse"
                        car.simulation = False
                        car.make_model = car_info["make_model"].strip('\n').lower()
                        car.capacity = MAKE_MODEL[car.make_model]
                        car.delta_kWh = car_info["delta_soc"] * car.capacity * 0.01
                        car.departure = str_to_int(car_info["departure"])
                        car.station_no = 0
                        cars_mutex.acquire()
                        cars.append(car)
                        cars_mutex.release()
                    else:
                        for car in cars:
                            if car.name == "openevse":
                                cars_mutex.acquire()
                                car.simulation = False
                                car.departure = str_to_int(car_info["departure"])
                                cars_mutex.release()
                        break

def publish_status(delay, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((ip_address, port))
        s.listen()
        conn, addr = s.accept()
        with conn:
            while i < len(building_dataset):
                visualization_info = {}
                visualization_info["current_time"] = int_to_str(i * READ_DELAY)
                visualization_info["avail_building_power"] = (max_building - building_dataset[i]) * 1000
                visualization_info["max_power"] = max_building*1000
                visualization_info["cars"] = {}

                total_power_used = 0.0
                total_building_power_used = 0.0
                total_power_to_batteries = 0.0
                total_energy_req = 0.0

                for car in cars:
                    visualization_info["cars"][car.station_no] = {"name": car.name, "delta_soc": 100 * car.delta_kWh/car.capacity, "current": car.charging_current, "battery": car.battery_current, "remaining_time": car.departure - i * READ_DELAY}
                    total_power_used += car.charging_current * VOLTAGE
                    total_building_power_used += (car.charging_current - car.battery_current) * VOLTAGE
                    total_energy_req += car.delta_kWh

                for station in stations:
                    total_power_to_batteries += station.charging_current*VOLTAGE

                visualization_info["total_building_power_used"] = total_building_power_used
                visualization_info["total_power_used"] = total_power_used
                visualization_info["total_power_to_batteries"] = total_power_to_batteries
                visualization_info["total_energy_req"] = total_energy_req

                for num in range(num_stations):
                    if num not in visualization_info["cars"]:
                        visualization_info["cars"][num] = "empty"
                
                data = pickle.dumps(visualization_info)
                try:
                    conn.send(data)
                except:
                    conn, addr = s.accept()
                sleep(delay)

def zeka_control():
    zeka_obj = zeka.Zeka()
    zeka_obj.zeka_init(zeka_bus)
    zeka_obj.zeka_receive(zeka_bus)
    while not zeka_obj.zeka_precharge_done:
        zeka_obj.zeka_main_status(zeka_bus)
        zeka_obj.zeka_receive(zeka_bus)
        sleep(1)
    zeka_obj.zeka_set_voltage_current(zeka_bus, ZEKA_VOLTAGE + 50, 1)
    zeka_obj.zeka_receive(zeka_bus)
    zeka_obj.zeka_start(zeka_bus)
    zeka_obj.zeka_receive(zeka_bus)
    current_set = 1.0

    while i < len(building_dataset):
        zeka_obj.zeka_feedback_status(zeka_bus)
        zeka_obj.zeka_receive(zeka_bus)
        sleep(0.5)
        current_set = (VOLTAGE * float(stations[0].battery_current)) / ZEKA_VOLTAGE
        if current_set < 1.0:
            current_set = 1.0
        zeka_obj.controller(zeka_bus, ZEKA_VOLTAGE, current_set)

        if i % 4 == 0:
            file = open("logs/zeka.txt", "a")
            file.write(int_to_str(i * READ_DELAY) + ", " + str(zeka_obj.zeka_read_current) + ", " + str(zeka_obj.zeka_read_voltage) + "\n")

    zeka_obj.zeka_stop(zeka_bus)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Charging Management System')
    parser.add_argument("--building-dataset", "--bd", dest="building_file", required=True, help="Building dataset file")
    parser.add_argument("--car-dataset", "--cd", dest="car_file", required=True, help="Car dataset file")
    parser.add_argument("--start-time", "--st", dest="start_time", default="18:00:00", help="Start time of building dataset (default: %(default)s)")
    parser.add_argument("--user-input-port", "--up", dest="user_port", type=int, default=8000, help="Port to listen for user input (default: %(default)s)")
    parser.add_argument("--visualization-port", "--vp", dest="visualization_port", type=int, default=9000, help="Port to send visualization output (default: %(default)s)")
    parser.add_argument("--openevse-port", "--op", dest="openevse_port", default="", help="OpenEVSE serial port")
    parser.add_argument("--zeka-port", "--zp", dest="zeka_port", default="", help="Zeka CAN port")
    parser.add_argument("--fast-sim", "--fs", dest="fast_sim", action="store_true", help="Run dataset without delay")
    parser.add_argument("--log", dest="log", action="store_true", help="Log building current, battery current and remaining SoC of each car")
    parser.add_argument("--continue", dest="cont", action="store_true", help="Continue previous simulation using logs")
    args = parser.parse_args()

    try:
        file = open(args.building_file, "r")
    except Exception as ex:
        print("Cannot open building dataset")
        exit(0)
    for line in file:
        building_dataset.append(float(line.strip()))

    max_building = max(building_dataset)
    if DEBUG:
        print("Max building power: " + str(max_building))

    try:
        file = open(args.car_file, "r")
    except Exception as ex:
        print("Cannot open car dataset")
        exit(0)
    for line in file:
        car_dataset.append(line.split(","))

    num_stations = len(car_dataset) + 1
    for num in range(num_stations):
        stations.append(Station(station_no=num))
 
    if not args.cont:
        start = args.start_time
    else:
        start = args.start_time
        line = subprocess.check_output(['tail', '-1', "logs/station00.txt"])
        data = line.decode().split(",")
        i = int(str_to_int(data[0]) / 2) + 1

    if (args.openevse_port != ""):
        try:
            openevse = Serial(args.openevse_port, 115200, xonxoff=True)
        except Exception as ex:
            openevse = None

    if (args.zeka_port != ""):
        try:
            zeka_bus = can.interface.Bus(bustype='slcan', channel=args.zeka_port, bitrate=500000)
        except Exception as ex:
            zeka_bus = None

    if args.log:
        if not os.path.exists("logs"):
            os.makedirs("logs")
        elif not args.cont:
            for f in os.listdir("logs"):
                os.remove(os.path.join("logs",f))

    openevse_arrived = False
    # Load previous logs
    if args.cont:
        for f in os.listdir("logs"):
            if f[0:3] == "sim" or f[0:8] == "openevse":
                line = subprocess.check_output(['tail', '-1', os.path.join("logs",f)])
                timestamp, measured_current, current, battery_current, soc, battery_no, priority = line.decode().split(",")

                if float(soc.strip()) == 0:
                    continue

                if f[0:8] == "openevse":
                    openevse_arrived = True
                    car = Car()
                    car.name = "openevse"
                    car.make_model = "nissan leaf"
                    car.capacity = MAKE_MODEL[car.make_model]
                    car.delta_kWh = float(soc.strip()) * car.capacity * 0.01
                    car.station_no = 0
                    car.charging_current = float(current.strip())
                    car.battery_current = float(battery_current.strip())
                    car.measured_current = float(measured_current.strip())
                    car.battery_no = int(battery_no.strip())
                    car.battery_on = (int(battery_no.strip()) != -1)
                    car.priority = float(priority.strip())
                    cars_mutex.acquire()
                    cars.append(car)
                    cars_mutex.release()
                    continue
                for car_data in car_dataset:
                    name, arrival, departure, model, desired_soc, sleep_mode = car_data
                    if name.strip() == f[0:5]:
                        car = Car()
                        car.name = name
                        car.make_model = model.strip().lower()
                        car.capacity = MAKE_MODEL[car.make_model]
                        car.delta_kWh = float(soc.strip()) * car.capacity * 0.01
                        car.departure = str_to_int(departure)
                        car.sleep_mode = sleep_mode.strip() == 'True'
                        car.station_no = int(f[3:5])
                        car.charging_current = float(current.strip())
                        car.battery_current = float(battery_current.strip())
                        car.measured_current = float(measured_current.strip())
                        car.battery_no = int(battery_no.strip())
                        car.battery_on = (int(battery_no.strip()) != -1)
                        car.priority = float(priority.strip())
                        cars_mutex.acquire()
                        cars.append(car)
                        cars_mutex.release()

            if f[0:7] == "station":
                line = subprocess.check_output(['tail', '-1', os.path.join("logs",f)])
                timestamp, battery_current, charging_current, capacity = line.decode().split(",")
                stations[int(f[7:9])].battery_current = float(battery_current.strip())
                stations[int(f[7:9])].charging_current = float(charging_current.strip())
                stations[int(f[7:9])].battery_capacity = float(capacity.strip())

        car_dataset = [x for x in car_dataset if int(x[1]) > (i * READ_DELAY)]

        if zeka_bus and openevse_arrived:
            zeka_thread = Thread(target=zeka_control)
            zeka_thread.start()
        if openevse and openevse_arrived:
            wait_for_car(args.user_port, True)

    read_thread = Thread(target=read, args=(args.fast_sim, args.log)) # every two seconds
    state_control_thread = Thread(target=state_control, args=(args.fast_sim,))

    read_thread.start()
    state_control_thread.start()

    if not args.fast_sim:
        if openevse and not openevse_arrived:
            wait_for_car_thread = Thread(target=wait_for_car, args=(args.user_port, False))
            wait_for_car_thread.start()
        if zeka_bus and not openevse_arrived:
            zeka_thread = Thread(target=zeka_control)
            zeka_thread.start()

    publish_status_thread = Thread(target=publish_status, args=(2, args.visualization_port))
    publish_status_thread.start()

    read_thread.join()

    print("Log: Building dataset complete")
