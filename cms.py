#!/usr/bin/env python3

import sys
import socket
import pickle
import argparse
from threading import Thread, Lock, Condition
from time import time, sleep
from serial import Serial
from random import randint

VOLTAGE = 220
DEBUG = True

# TODO: CONTROL_DELAY = 900
CONTROL_DELAY = 6 # 15 minutes
READ_DELAY = 2 # 2 seconds

# TODO: FAST_CONTROL_DELAY = 0.9
FAST_CONTROL_DELAY =  0.006
FAST_READ_DELAY = 0.002

MAKE_MODEL = {"nissan leaf": 40}

openevse = None
i = 0
start_time = time()

building_dataset = []
car_dataset = []

cars = []
cars_mutex = Lock()

wait = Condition()

class Car:
    name = ""
    simulation = True
    sleep_mode = False
    priority = 0
    delta_kWh = 0 # desired delta SoC * total capacity
    departure_time = 0
    min_current = 6
    max_current = 24 # 24A for L1 
    charging_current = 0
    battery = False
    make_model = ""
    capacity = 0

def read(delay, fast_sim):
    # delay in seconds
    global i
    while i < len(building_dataset):
        if i % CONTROL_DELAY // READ_DELAY == 0:
            wait.acquire()
            wait.notify()
            wait.release()

        cars_mutex.acquire()

        # read available building power
        # building dataset in kW
        available_current = building_dataset[i] * 1000 / VOLTAGE 

        # read current (read from openevse or dataset for simulation)
        # TODO: ask Shash to make datasets for measured current that accounts for current saturation
        # TODO: use dataset currents for measured_current
        for car in cars:
            if car.simulation:
                measured_current = car.charging_current
            else:
                openevse.write("$GG")
                measured_current = openevse.readline()
            car.delta_kWh -= measured_current * VOLTAGE * (delay / 3600) * 0.001
            if car.delta_kWh < 0:
                car.delta_kWh = 0
            # check saturation
            if measured_current <= car.charging_current - 2: # this value may need to be tuned
                car.max_current = measured_current

        # assign current (cars are already sorted from highest priority to lowest priority)
        remove_cars = 0
        used_current = 0
        for car in cars:
            car.charging_current = int(available_current * car.priority)

            if available_current - used_current < car.min_current:
                if car.sleep_mode:
                    car.battery = True
                    print("Log: Turning on battery for " + car.name)
                else:
                    break
            elif car.charging_current > car.max_current:
                car.charging_current = car.max_current
            elif car.charging_current < car.min_current:
                car.charging_current = car.min_current

            if car.name == "openevse":
                openevse.write("$SC " + car.charging_current)

            used_current += car.charging_current

        # TODO: if available_current > 0 charge batteries

        cars_mutex.release()
        if fast_sim:
            sleep(FAST_READ_DELAY)
        else:
            sleep(delay)
        i += 1

def state_control(state_control_delay, read_delay, fast_sim):
    global car_dataset
    while i < len(building_dataset):
        #if fast_sim:
        #    current_time = i * read_delay
        #else:
        #    current_time = time() - start_time

        wait.acquire()
        wait.wait()
        wait.release()

        current_time = i * read_delay

        # check for new simulated cars that have arrived
        for car in car_dataset:
            arrival, model, desired_soc = car
            if int(arrival) <= current_time:
                if DEBUG:
                    print("Log: Simulated car arrived")
                car = Car()
                car.name = "sim" + str(randint(1,99))
                car.make_model = model.strip().lower()
                car.capacity = MAKE_MODEL[car.make_model]
                car.delta_kWh = int(desired_soc) * car.capacity
                car.departure_time = 50000
                cars_mutex.acquire()
                cars.append(car)
                cars_mutex.release()
        car_dataset = [x for x in car_dataset if int(x[0]) > current_time]

        cars_mutex.acquire()
        # check if battery needs to be turned on
        for car in cars:
            if car.delta_kWh >= car.max_current * VOLTAGE * (car.departure_time - current_time):
                print("Log: Turning on battery for " + car.name)
                car.battery = True

        # assign priorities
        normalize = 0
        for car in cars:
            car.priority = car.delta_kWh / (car.departure_time - current_time)
            normalize += car.priority
        for car in cars:
            car.priority = car.priority / normalize
        cars.sort(key=lambda x: (x.sleep_mode, x.priority), reverse=True)

        cars_mutex.release()
        #if fast_sim:
        #    sleep(FAST_CONTROL_DELAY)
        #else:
        #    sleep(state_control_delay)

def wait_for_car(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
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
                if car_info["station_no"] == 1 and openevse:
                    # TODO: check that car is connected to openevse
                    # openevse.write()
                    # openevse.readline()
                    if DEBUG:
                        print("Log: Car plugged in")
                    car = Car()
                    car.name = "openevse"
                    car.simulation = False
                    car.make_model = car_info["make_model"].strip('\n').lower()
                    car.capacity = MAKE_MODEL[car.make_model]
                    car.delta_kWh = car_info["delta_soc"] * car.capacity
                    car.departure_time = 50000
                    cars_mutex.acquire()
                    cars.append(car)
                    cars_mutex.release()

def publish_status(delay, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        conn, addr = s.accept()
        with conn:
            while i < len(building_dataset):
                visualization_info = {}
                visualization_info["building_power"] = building_dataset[i]
                visualization_info["cars"] = []
                for car in cars:
                    visualization_info["cars"].append({"name": car.name, "delta_soc": car.delta_kWh/car.capacity, "current": car.charging_current, "battery": car.battery})
                data = pickle.dumps(visualization_info)
                conn.send(data)
                sleep(delay)

if __name__ == "__main__":
    # TODO: how to simulate charging station batteries
    # TODO: how to turn on/off physical battery
    # TODO: determine expected departure time (right now all cars leave around 14 hours after time 0)
    # TODO: add actual departure time to car dataset

    parser = argparse.ArgumentParser(description='Charging Management System')
    parser.add_argument("--building-dataset", "--bd", dest="building_file", required=True, help="Building dataset file")
    parser.add_argument("--car-dataset", "--cd", dest="car_file", required=True, help="Car dataset file")
    parser.add_argument("--user-input-port", "--up", dest="user_port", type=int, default=8000, help="Port to listen for user input")
    parser.add_argument("--visualization-port", "--vp", dest="visualization_port", type=int, default=9000, help="Port to send visualization output")
    parser.add_argument("--openevse-port", "--op", dest="openevse_port", default="", help="OpenEVSE serial port")
    parser.add_argument("--fast-sim", "--fs", dest="fast_sim", action="store_true", help="Run dataset without delay")
    args = parser.parse_args()

    try:
        file = open(args.building_file, "r")
    except Exception as ex:
        print("Cannot open building dataset")
        exit(0)
    for line in file:
        building_dataset.append(int(line))

    try:
        file = open(args.car_file, "r")
    except Exception as ex:
        print("Cannot open car dataset")
        exit(0)
    for line in file:
        car_dataset.append(line.split(","))

    try:
         openevse = Serial(args.openevse_port)
    except Exception as ex:
         openevse = None

    read_thread = Thread(target=read, args=(READ_DELAY, args.fast_sim)) # every two seconds
    state_control_thread = Thread(target=state_control, args=(CONTROL_DELAY, READ_DELAY, args.fast_sim))
    wait_for_car_thread = Thread(target=wait_for_car, args=(args.user_port,))
    publish_status_thread = Thread(target=publish_status, args=(2, args.visualization_port))

    read_thread.start()
    state_control_thread.start()
    wait_for_car_thread.start()
    publish_status_thread.start()

    read_thread.join()

    print("Log: Building dataset complete")
    for car in cars:
        print("Name: " + str(car.name) + " SoC remaining(%): " + str(car.delta_kWh/car.capacity))
