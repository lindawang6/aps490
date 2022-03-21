import sys
import socket
import pickle
import curses
import signal
from datetime import datetime	
import requests

from requests.api import post

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)


# REST_API_URL = "https://api.powerbi.com/beta/0304ab7d-ac17-40f5-af5c-79da66b2889c/datasets/ec775be6-ca91-403b-b235-32a1c93980dd/rows?key=75hmJIaaIZ%2B0mhyhsT4iYkg64OUwcwcUFRLSu1RPS0dnBAxi%2FyvhtVCb1r%2FmX2vn4BSEhzr711Ql1nEl97QcEg%3D%3D"
# REST_API_URL = "https://api.powerbi.com/beta/78aac226-2f03-4b4d-9037-b46d56c55210/datasets/977565ce-38b6-40bc-9feb-7572526600bd/rows?key=Rt8HZgzgG7tHG09AZ9OjaPtVyzL5VbSVeqDwPRL4JX5DK19YiyD9dTY1pDxHr5IoB3VuYO2Hw4V6lnHdPb1ccA%3D%3D"
REST_API_URL ="https://api.powerbi.com/beta/0304ab7d-ac17-40f5-af5c-79da66b2889c/datasets/ec775be6-ca91-403b-b235-32a1c93980dd/rows?key=75hmJIaaIZ%2B0mhyhsT4iYkg64OUwcwcUFRLSu1RPS0dnBAxi%2FyvhtVCb1r%2FmX2vn4BSEhzr711Ql1nEl97QcEg%3D%3D"


def signal_handler(sig, frame):
    curses.endwin()
    s.close()
    sys.exit(0)


def convert(seconds):
    seconds = seconds % (24 * 3600)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
      
    return "%dh %02dmin" % (hour, minutes)



if __name__ == "__main__":
    s.connect(("127.0.0.1", int(sys.argv[1])))
    signal.signal(signal.SIGINT, signal_handler)

    count =0
    num = 0

    while True:
        #Retrieve data from socket
        data = s.recv(4096)
        if len(data) == 0:
            continue
        visualization_info = pickle.loads(data)
        print('=============')
        print("visualization: ", visualization_info)

        i = 1

        now = datetime.strftime(datetime.now(), "%Y-%m-%dT%H:%M:%S%Z")
        # now = visualization_info["current_time"]

        #start JSON string (will be used to post data)
        post_data= '[{{"timestamp": "{0}", "building_power": "{1}", "total_power_used":"{2}", "total_buildingpower_used": "{3}"'.format(now, visualization_info["building_power"], visualization_info["total_power_used"], visualization_info["total_buildingpower_used"])

        for car_id, car in visualization_info["cars"].items():
            # car_id=car_id+1
            
            if car_id >4 or car_id==0: #skip station 0
                continue
            print(car)
            print('----------------')

            if car == 'empty':
                car_name = 'Available Station'
                car_delta_soc = "0"
                car_status = "Available for charge"
                car_current = "0"
                car_battery = "0"
                car_rem_time = convert(0)
            else:
                car_name = str(car["name"])
                car_delta_soc = car["delta_soc"]
                if car_delta_soc <= 0.1:
                    car_status = "Charged"
                else:
                    car_status = "Charging..."

                         
                car_current = str(car["current"])
                car_battery = str(car["battery"])
                car_rem_time = convert(car["remaining_time"])
            
            sub_data = ', "car_name{0}": "{1}", "car_delta_soc{0}": "{2}%", "car_current{0}": "{3}", "car_battery{0}": "{4}", "car_rem_time{0}": "{5}", "car_status{0}": "{6}" '.format(car_id, str(car_name), str(car_delta_soc), car_current, str(car_battery), str(car_rem_time), str(car_status) )
            post_data += sub_data
            i += 1
        
        post_data += '}]'

        # make HTTP POST request to Power BI REST API
        req = requests.post(REST_API_URL, post_data)
        
        count +=1
        print("count: ", count)
        print("POST: {0}".format(post_data))
        print("req status ====")
        print(req)
        print('=============')

        




