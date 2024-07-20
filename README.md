PyEnergyMarket is a EGRET-based energy market modeling tool developed by PNNL in the E-COMP LDRD initiative.

## Package Structure
## EnergyMarket
The `EnergyMarket` class is defined in `engine.py` and houses the core functionalities for running energy market models

## GVParse
The `GVParse` class is the GridView parse used to convert GridView models (currently _solved_) exported to an `h5` file to the EGRET data model

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
* We can model the needed reserves as load and the generators bid in just their reserve as "generation"

### Real Time Market
* Energy Dispatch
* 15 minute resolution

# Setup
## Intalling Egret
To install Egret the repository needs to be cloned and then installed via pip in edit mode.
See the instructions [here](https://github.com/breldridge/Egret?tab=readme-ov-file#installation)

Make sure to [install a solver](#solvers)

Then proceed to verify the installation, see [these instructions](https://github.com/breldridge/Egret?tab=readme-ov-file#testing-the-installation)

## Installing `pnnlpcm` package for GridView h5 handling
Egret models based on GridView models are created by parsing the `h5` file created by GridView.
To work with this file, the `pnnlpcm` package is required, which is hosted privately [here](https://devops.pnnl.gov/ntp/ntp_PCM).
To get access reach out to Eran: <eran.schweitzer@pnnl.gov>.

Once the repository is cloned it can be installed using the editable mode:
```
pip install -e <path-to-ntp-pcm>
```

## installing `pyenergymarket`
Install pyenergy market as an editable package via:
```
pip install -e <path-to-pyenergymarket>
```

## Solvers
### Installing CBC on Windows
Cbc installation appears to be not very supported on windows.
The following appears to work for getting the installation working.

#### Python environment
For this example a `conda` environment is assumed (something like `conda create --name scuc-der`).
There are other ways to work with python environments, with some modification potentially necessary.

#### Get the Binaries
The CBC binaries can be downloaded from [here](https://www.coin-or.org/download/binary/Cbc/?C=M;O=D).
Download one for win64.

This will download a zip file to your computer. For example:
```
Cbc-master-win64-msvc15-mtd.zip
```

Extract the zip files.

Under the created folder structure navigate to `bin`

There should be three `.exe` files located there:
* `cbc.exe`
* `clp.exe`
* `glpsol.exe`

#### Copy to Python Environment

The three `.exe` binaries need to now be copied to the `bin` folder of your Python environment.
This should be located at:
```
<Your-Anacond/Minicond-Installation-Folder>/envs/<environment-name>/Library/bin
```
### Installing SCIP
[SCIP](https://www.scipopt.org/index.php#download) is a high-performance open source MIP solver.
To install it simply run:
```
conda install scip -c conda-forge
```
The repository is [here](https://github.com/conda-forge/scipoptsuite-feedstock)

### IPOPT
There appears to be an issue with ipopt versions `>3.11` that the `ipopt.exe` is no longer included when installing (at least via conda).
See [this issue](https://github.com/conda-forge/ipopt-feedstock/issues/55).
As a result, if ipopt, say version 3.14 (latest at the time of writing) is used, then pyomo (which requires the `ipopt.exe` binary apparently) errors, stating that the application could not be found.

A solution to this is to install version 3.11:
```
conda install ipopt=3.11 -c conda-forge
```

>*Note*:<br>
>Ipopt is installed along with scip, so if you are installing scip it may be better to install this first, otherwise there appear to be dependency issues. 

### Verify Installation
In the command line run:
```
(scuc-der)> pyomo help --solvers

Pyomo Solvers and Solver Managers
---------------------------------
Pyomo uses 'solver managers' to execute 'solvers' that perform
[...]

Serial Solver Interfaces
------------------------
The serial manager supports the following solver interfaces:
[...]
    +cbc                 0.0       The CBC LP/MIP solver
[...]
```
The `(+)` sign next to `cbc` (or any other solver) indicates that the solver was found.
If there is no sign, it means that something didn't work.
