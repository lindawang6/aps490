#!/usr/bin/env python3

import sys
import socket
import pickle
import argparse
from threading import Thread, Lock, Condition
from time import time, sleep
from serial import Serial
from random import randint

VOLTAGE = 240
DEBUG = True

CONTROL_DELAY = 6 # 6 seconds
READ_DELAY = 2 # 2 seconds

FAST_CONTROL_DELAY =  0.006
FAST_READ_DELAY = 0.002

MAKE_MODEL = {"nissan leaf": 40,
              "tesla model y": 75,
              "chevrolet bolt": 65}

openevse = None
i = 0

building_dataset = []
car_dataset = []

max_building = 0

cars = []
cars_mutex = Lock()

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
    battery_capacity = 20

def read(fast_sim, log):
    # delay in seconds
    global i
    while i < len(building_dataset):
        if i % CONTROL_DELAY // READ_DELAY == 0:
            wait.acquire()
            wait.notify()
            wait.release()

        cars_mutex.acquire()

        # read building power
        # building dataset in kW
        available_current = (max_building - building_dataset[i]) * 1000 / VOLTAGE 

        # read current (read from openevse or dataset for simulation)
        # TODO: make datasets for measured current that accounts for current saturation
        # TODO: use dataset currents for measured_current
        for car in cars:
            if car.simulation:
                measured_current = car.charging_current * 0.8
            else:
                openevse.write("$GG")
                measured_current = int(openevse.readline())
            car.delta_kWh -= measured_current * VOLTAGE * (READ_DELAY / 3600) * 0.001
            if car.delta_kWh < 0:
                car.delta_kWh = 0
            # check saturation
            if measured_current > 0 and measured_current <= car.charging_current * 0.75: # this value may need to be tuned
                car.max_current = measured_current

            car.battery_capacity -= car.battery_current * VOLTAGE * (READ_DELAY / 3600) * 0.001

        # assign current (cars are already sorted from highest priority to lowest priority)
        remove_cars = 0
        used_current = 0
        for car in cars:
            car.charging_current = int(available_current * car.priority)

            if car.priority == 0:
                pass
            elif car.battery_on and car.battery_capacity > car.max_current * VOLTAGE * (READ_DELAY / 3600) * 0.001:
                if car.charging_current < car.max_current:
                    car.battery_current = car.max_current - car.charging_current
                car.charging_current = car.max_current

            else:
                if available_current - used_current < car.min_current:
                    if car.sleep_mode:
                        car.charging_current = car.min_current
                        car.battery_current = car.min_current - (available_current - used_current)
                    else:
                        car.charging_current = 0
                elif car.charging_current > car.max_current:
                    car.charging_current = car.max_current
                elif car.charging_current < car.min_current:
                    car.charging_current = car.min_current

            used_current += (car.charging_current - car.battery_current)

            if car.name == "openevse":
                openevse.write("$SC " + car.charging_current)

        # Log building current, battery current, remaining SoC
        if log:
            for car in cars:
                file = open(car.name + ".txt", "a")
                file.write(str(car.charging_current) + ", " + str(car.battery_current) + ", " + str(100 * car.delta_kWh/car.capacity) + "\n")
            for car in car_dataset:
                file = open(car[0] + ".txt", "a")
                file.write("0, 0, 0\n")

        # TODO: if available_current > 0 charge batteries

        cars_mutex.release()
        if fast_sim:
            sleep(FAST_READ_DELAY)
        else:
            sleep(READ_DELAY)
        i += 1

def state_control(fast_sim):
    global car_dataset
    while i < len(building_dataset):
        wait.acquire()
        wait.wait()
        wait.release()

        current_time = i * READ_DELAY

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
                car.departure = int(departure)
                car.sleep_mode = sleep_mode.strip() == 'True'
                cars_mutex.acquire()
                cars.append(car)
                cars_mutex.release()
        car_dataset = [x for x in car_dataset if int(x[1]) > current_time]

        cars_mutex.acquire()

        # check for cars that have left
        for car in cars[:]:
            if car.departure < current_time:
                print("Car: " + str(car.name) + " left at " + str(car.departure) + " with SoC remaining(%): " + str(100 * car.delta_kWh/car.capacity))
                cars.remove(car)

        # check if battery needs to be turned on
        for car in cars:
            if not car.battery_on and car.delta_kWh >= 0.8 * car.max_current * VOLTAGE * 0.001 * (car.departure - current_time) / 3600:
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
                    if DEBUG:
                        print("Log: Car plugged in")
                    car = Car()
                    car.name = "openevse"
                    car.simulation = False
                    car.make_model = car_info["make_model"].strip('\n').lower()
                    car.capacity = MAKE_MODEL[car.make_model]
                    car.delta_kWh = car_info["delta_soc"] * car.capacity
                    car.departure = i * READ_DELAY
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
                    visualization_info["cars"].append({"name": car.name, "delta_soc": 100 * car.delta_kWh/car.capacity, "current": car.charging_current, "battery": car.battery_current})
                data = pickle.dumps(visualization_info)
                conn.send(data)
                sleep(delay)

if __name__ == "__main__":
    # TODO: how to simulate charging station batteries (sharing/charging/assigning batteries)
    # TODO: how to turn on/off physical battery
    # TODO: determine expected departure time (right now all cars leave around 14 hours after time 0)

    parser = argparse.ArgumentParser(description='Charging Management System')
    parser.add_argument("--building-dataset", "--bd", dest="building_file", required=True, help="Building dataset file")
    parser.add_argument("--car-dataset", "--cd", dest="car_file", required=True, help="Car dataset file")
    parser.add_argument("--user-input-port", "--up", dest="user_port", type=int, default=8000, help="Port to listen for user input (default: %(default)s)")
    parser.add_argument("--visualization-port", "--vp", dest="visualization_port", type=int, default=9000, help="Port to send visualization output (default: %(default)s)")
    parser.add_argument("--openevse-port", "--op", dest="openevse_port", default="", help="OpenEVSE serial port")
    parser.add_argument("--fast-sim", "--fs", dest="fast_sim", action="store_true", help="Run dataset without delay")
    parser.add_argument("--log", dest="log", action="store_true", help="Log building current, battery current and remaining SoC of each car")
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

    try:
         openevse = Serial(args.openevse_port)
    except Exception as ex:
         openevse = None

    read_thread = Thread(target=read, args=(args.fast_sim, args.log)) # every two seconds
    state_control_thread = Thread(target=state_control, args=(args.fast_sim,))
    if not args.fast_sim:
        wait_for_car_thread = Thread(target=wait_for_car, args=(args.user_port,))
        publish_status_thread = Thread(target=publish_status, args=(2, args.visualization_port))

    read_thread.start()
    state_control_thread.start()

    if not args.fast_sim:
        wait_for_car_thread.start()
        publish_status_thread.start()

    read_thread.join()

    print("Log: Building dataset complete")
