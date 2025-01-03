# EGRET Data Model Tests
This folder contains tests to understand the Egret data model.
The idea is to use the RTS-GMLC implementation in Prescient and extract the Egret data models for testing.

The file `sim_rts_gmlc_save_egret_test.py` runs a Prescient simulation and saves the RUC and SCED Egret dictionaries at each solve.
To run this file, Prescient needs to be installed, as well as.
To install Prescient clone [this repository](https://github.com/grid-parity-exchange/Prescient) and follow the instructions [here](https://github.com/grid-parity-exchange/Prescient?tab=readme-ov-file#installing-from-source)

Follow the [RTS-GMLC Example](https://github.com/grid-parity-exchange/Prescient?tab=readme-ov-file#rts-gmlc-example-model) to create the `downloads/rts_gmlc` folder.
Note, the `rts_gmlc.py` script clones a repository, if the path where it plans on cloning has a space in it (e.g. if you're working on the PNNL One-Drive) this will cause an error.
The solution is to modify line 63 of that file to (note that added double quotes around `rtsgmlc_path`):
```python
clone_cmd = 'git clone -n '+url+' '+'"'+rtsgmlc_path+'"'
```
The `data_path` argument in `sim_rts_gmlc_save_egret_test.py` needs to point to the `/downloads/rts_gmlc/RTS-GMLC/RTS_Data/SourceData/` folder.
It can be passed to the script using the optional `--data-path` input.
If you cloned Prescient to the same folder as the pyenergymarket repository, the default should be correct.

The results from the run are commited to the repository for reference in the [`rts_gmlc_output`](./rts_gmlc_output/) folder.
This includes both the prescient results as well as the json outputs of the mode data.
There are outputs both before and after each model run (unit commitment RUC and real time SCED).
The other csvs in the folder are results coming from Prescient.
The idea is to try to set up independent Egret runs and compare them to these results for validation.

>**IMPORTANT**<br>
>It appears that the UC/dispatch problems in Egret don't automatically solve for LMPs, that is, we'll need to tack on a second step for that in all instances.

# GridView Parser
## Testing the model
Generate the Egret `ModelData` json file using `test_gvparser.py`.
This takes as argument a path to an h5 file as well as other optional arguments see:
```
python test_gvparser.py --help
```

Run the Unit Commitment model using the `uc_test_example.py`.
This takes as optional arguments the path to the json model data as well as which solver (gurobi or cbc) to use.
This will save another json file with the solution data in it.

Finally, the results can be investigated using `investigate_solution.py`.
This creates a generation stack figure and also prints some data frames.
More work is necessary on this script.

## Fuel Based or Not
There are two different ways to get costs for thermal generators in the Egret Model.
1. Fuel Base: in this case `fuel_cost`, `p_fuel`, `sartup_fuel`, `non_fuel_startup_cost`
2. Non Fuel Based: in this case things are defined by `p_cost`, `startup_cost`.

Egret defaults to the fuel based values if provided.
See for example:
[startup_cost = thermal_gens[g].get('startup_cost')](https://github.com/breldridge/Egret/blob/03f1f01866c315661ba858e04d330528d200cb32/egret/model_library/unit_commitment/params.py#L855-L859)


The fuel based method is the way the GridView models are generally based, that is the real Production Cost Model.
One issue is that Egret does not seem to support variable O&M which is another $/MWh cost component in the GridView model.

It is probably preferable therefore to convert to (MW,$) curves.

## VOM
There are three locations where VOM is present:
1. ThermalGeneral-> VOMCost
2. ThermalGenericVOMCOst -> VOMCost
3. MonthlyVariableSchedule -> DataTypeID = 1

It is unclear what the precedence is between these, so for now the monthly schedule (point 3) will be ignored and the point 1 taken unless it is negative, in which case the generic value will be used."

## Starting Costs
### IF Generic
Start fuel cost is GenericStartFuel[MMBTU/MW] * Pmax[MW] * Fuel Cost [$/MMBTU]

Non-Fuel Start Cost is GenericStartCost[$/MW] * Pmaxp[MW]

### Non-Generic
Start fuel cost is StartFuel[MMBTU] * Fuel Cost [$/MMBTU]

Non-Fuel Start Cost is StartupCost[$]

###

# GridView Generator Tables (Discussion With Kostas)
## Generator Key based
* `Generator`
* `FuelAssignment`
* `ThermalCurve`
* `ThermalGeneral`
* `ThermalIOCurve`
* `GenMaint`
* `MonthlyVariableSchedule`
* `HourlyResources`

## Generator Table
Column `GeneratorType` links to Monthly Variable Schedule Type.

1. Thermal
2. Hydro
3. Energy Storage including pumped hydro
4. Renewable

## HourlyResources
Table that lists hourly resources keyed by GeneratorKey

The `Type` column maps to the `HourlyResourceType` table.

### ThermalGeneral
* Has a lot of the key constraints for thermal generators (ramp rates, must run).
* Crucially, `FuelID`!!

### ThermalIOCurve
* Points to `ThermalGenericIOCurve` (optional)
* has the heat rate information
* `IOMinCap` and `IncCap<n>` are in MW
* `MinInput` is MMBTU at the minimum
* subsequent HR are MMBTU/MWh

### GenMaint
In the time between `MaintStart` and `MaintEnd` the unit is out of service.

### MonthlyVariableSchdule
Information by Generator Type such as VOM, Fixed costs, etc.

#### MonthlyVariableScheduleType
Look Generator type (i.e. 1 for thermal).
Explains the data types in MonthlyVariableSchedule


## FuelID based
* `Fuel`
* `EmissionFuel`
* `FuelCostSchedule` (FuelID as well as year)

### FuelCostSchedule
* Fuel costs by fuel ID per month $/MMBTU

## Start
if generic
Start fuel cost is StartFuel[MMBTU/MW] * Pmax * Fuel Cost [$/MMBTU]

otherwise: StartFuel[MMBTU] * Fuel Cost [$/MMBTU]

If generic:
StartCost is StartCost[$/MW] * Pmax
Otherwise just StartCost[$]


## Ancilliary Services

>**NOTE:**<br>
>When shapes are provided, they are in `.dat` files that are currently not in the h5.
>Ideally, these would be included/parsed so that just inputs can be used.
>For now, when a shape is pointed to the REQUIREMENT from one of the result keys will be used.

Ancillary service types:
See pg. 326 AncillaryService_Requirement.csv of Hitachi manual
| ASType | Description|
| :----: | :--------  |
| 1 | Regulation Down |
| 2 | Load Following Down |
| 3 | Regulation Up |
| 4 | Spinning Reserve |
| 5 | nonSpinning Reserve |
| 6 | Load Following Up |
| 7 | Frequency Response  |

It looks like EGRET has regulation and flexible ramping which match regulation and load following here.
So the only thing that would be missing is Frequency response.

Looking at the GridView results it appears that 
$$
P_g[t] + RU[t] + LFU[t] \leq P_{\text{max}}
$$

Requirements in mdb/AreaRegionAS
Check if active by column EnforceReserve
Two Options:
1. Based on BaseLoadPercent/GenerationPercent
2. Based on provided shape (if ShapeAdderFlag is True) in that case ShapeAdderID map to /mdb/AreaRegionAS, something like this: 
```python
h5("/mdb/AreaRegionAS").loc[lambda x: x["ShapeAdderFlag"]].merge(h52("/mdb/AreaRegionReserveShape"), how="left", left_on="ShapeAdderID", right_on="ID")
```

ASType (see above)

Type:
1. LoadAreaID
2. Region 
3. Combined

Note: there might be a type 0 which is system wide.

ID:
- If Region (Type=2), applies to all areas in /mdb/LoadArea/ with the same RegionID
- If Combined the use "/mdb/CombinedAreaRegionDefinition" to see maping from ID (CombinedAreaRegionID) to region IDs (ElementID) (if ElementType is 1, or LoadAreaID if ElementType is 2)

mdb/GeneratorAncillaryServiceOption2
GeneratorType (see thermal, hydro, etc.)
Type:
0: Everything
1: Don't Know (almost certainly LoadAreaID)
2: Region 
3: CombinedRegion

>**NOTE**:
> This type mapping should be verified. It appears to be correct for the Mini WECC model.

ID:
The id to look for depending on the Type

SubType:
Type of generation that is configured to provide reserves at various levels.
If there is a row with SubType = Nothing then all resources of this GeneratorType then a True in the other columns takes precedence.

Similarly if Type and ID are 0 this overrides everything.

Other columns:
XX[Option]: Whether this type of unit can supply this kind of reserve
XX[MaxPercentage]: is the maximum percent of capacity that can supply the reserve

# Count On/Off Test
The count on/off test validates the performance of the timeutils.count_onoff function.
This function sets a new initial status based on the commitment history
and previous initial status. For example, at hour 14, a unit committed for
13 hours with an initial status of 3 will get an updated initial status of
16 (meaning 16 hours online).

If a unit changes status, the initial_status keyword won't matter. In instead at hour
14 the unit was committed for the first 8 hours only, it will get a new
initial_status of -6 (14-8 =  6 hours offline).

This test can be run with
```
python test_count_onoff.py
```

This will use solutions from pyenergy_test_solution.json. If this file
doesn't exist, you can specify the h5path the the test will invoke the test_energymarket.py.
Optionally you can also include a verbose flag. This will
print generator results to the terminal. If you would like to only see the generators
that change status, you can also specify the 'different' flag.
```
python test_count_onoff.py --h5path <path-to-h5file.h5> [-v] [-d]
```
The test solution with updated initial status will be saved to count_onoff_test_solution.json.
