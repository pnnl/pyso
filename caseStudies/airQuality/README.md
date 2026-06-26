# Air Quality Equity Metric:

This repo contains the code associated with [insert paper citation here]. 

## Finding the DAC of interest

It is first necessary to determine with disadvantaged community (DAC) you are interested in studying. The CEJST.ipynb walks you through how to select communities with the DAC title in the WECC region based on one or some combination of the following 3 criteria: energy burden, asthma, and PM2.5. 

## Computing the concentration of the pollutant of interest at the DAC

To calculate the concentration of a pollutant of interest in a DAC due to model data from a nearby powerplant, use the GaussianDispersionModeling.ipynb notebook. This notebook walks you through the necessary inputs needed to compute this and if information is not known, current reasonable averages and values are entered for every necessary input with sources.

## Calculating the AQI at the DAC

We then need to calculate the air quality index (AQI). The AQI.ipynb walks you through how to do this. However, to use the AQI notebook, you must know the concentration of your pollutant of interest (see above). This notebook supports AQI calculations for the following pollutants: O$_3$ (ppm) 8-hour, O$_3$ (ppm) 1-hour, PM$_{2.5}$ ($\mu$g/m$^3$) 24-hour, PM$_{10}$ ($\mu$g/m$^3$) 24-hour, CO (ppm) 8-hour, SO$_2$ (ppb) 1-hour, and NO$_2$ (ppb) 1-hour. Note that only the highest concentration among all of the monitors within a given reporting area should be recorded for each pollutant. All data should be input as a dictionary with keys as the pollutant (type string) and the values as the concentration (type float). Note that the only accepted keys are the following (corresponding to the above listed pollutants): 'O3_8hr_ppm', 'O3_1hr_ppm', 'PM2.5_24hr_μg/m^3', 'PM10_24hr_μg/m^3', 'CO_8hr_ppm', 'SO2_1hr_ppb', 'NO2_1hr_ppb'.

## Specific DACs

The other notebooks walk through the full process for each DAC selected and include values used for each community given generator dispatch data. 