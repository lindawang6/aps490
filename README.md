# CMS
## Run CMS:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt```

### Building dataset format

Available building power readings (kW) separated by new lines.

First reading is reading at 6pm. Each reading is two seconds apart. 

### Car dataset format

List of cars separated by new lines.

Format of each line: name, arrival time (seconds), departure time (seconds), model, desired change in SoC (%), sleep mode (True/False).

Arrival time of 0 means the car arrives at 6pm.

### Examples

See building_datasets and car_datasets for correct dataset format.

## Run visualization interface:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt --visualization-port 9000```

```./visualization.py 9000```

## Connect to OpenEVSE:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt --user-input-port 8000 --openevse-port /dev/ttyUSB0```

```./user_input.py 8000```

## Run fast sim:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt --fast-sim```

## Log each car's building current, battery current and remaining SoC:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt --log```

## Help:

```./cms.py --help```
