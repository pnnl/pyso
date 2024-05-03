PyEnergyMarket is a EGRET-based energy market modeling tool developed by PNNL in the E-COMP LDRD initiative.

## Use Case Structure
### Data Set
We'll start with the RTS GMLC system just to have a model that runs.
Will shift to Mini WECC once it is available
### Day Ahead Market
* Model as  unit commitment followed by energy dispatch
* Add a capacity reserve (either via available constraint or bumping load in commitment)

### Reserve Market
* 24 hour hourly capacity reserve
* Only generation that has been committed can participate
* Generators do not _have to_ have their capacity add to 100%, that is if unit commitment for hour t is 100% can still offer reserves, difference must be reconciled in real time

### Real Time Market
* Energy Dispatch
* 15 minute resolution
