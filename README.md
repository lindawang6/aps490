# CMS
## Run CMS:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt```

### Building dataset format

Available building power readings (kW) separated by new lines.

### Car dataset format

List of cars separated by new lines.

Format of each line: arrival time, model, desired change in SoC.

### Examples

See building_dataset_example.txt and car_dataset_example.txt for correct dataset format.

## Run visualization interface:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt --visualization-port 9000```

```./visualization.py 9000```

## Connect to OpenEVSE:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt --user-input-port 8000 --openevse-port /dev/ttyUSB0```

```./user_input.py 8000```

## Run fast sim:

```./cms.py --building-dataset building_dataset_example.txt --car-dataset car_dataset_example.txt --fast-sim```

## Help:

```./cms.py --help```
