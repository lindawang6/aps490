#!/usr/bin/env python3

import sys
import socket
import pickle

if __name__ == "__main__":
    car_info = {}
    print("Enter the charging station number: ")
    car_info["station_no"] = int(sys.stdin.readline())
    print("Enter car make/model: ")
    car_info["make_model"] = sys.stdin.readline()
    print("Enter desired change in SoC(%): ")
    car_info["delta_soc"] = int(sys.stdin.readline())
    print("Enter departure time (hh:mm:ss): ")
    car_info["departure"] = sys.stdin.readline()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("127.0.0.1", int(sys.argv[1])))
        data = pickle.dumps(car_info)
        s.send(data)
        s.close()
