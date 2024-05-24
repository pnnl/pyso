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