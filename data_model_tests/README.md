# EGRET Data Model Tests
This folder contains tests to understand the Egret data model.
The idea is to use the RTS-GMLC implementation in Prescient and extract the Egret data models for testing.

The file `sim_rts_gmlc_save_egret_test.py` runs a Prescient simulation and saves the RUC and SCED Egret dictionaries at each solve.
To run this file, Prescient needs to be installed, as well as.
To install Prescient clone [this repository](https://github.com/grid-parity-exchange/Prescient) and follow the instructions [here](https://github.com/grid-parity-exchange/Prescient?tab=readme-ov-file#installing-from-source)

Follow the [RTS-GMLC Example](https://github.com/grid-parity-exchange/Prescient?tab=readme-ov-file#rts-gmlc-example-model) to create the `downloads/rts_gmlc` folder.
The `data_path` argument in `sim_rts_gmlc_save_egret_test.py` needs to point to the `/downloads/rts_gmlc/RTS-GMLC/RTS_Data/SourceData/` folder.