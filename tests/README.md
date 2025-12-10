# PyEnergyMarket Tests
This folder contains tests for the `pyenergymarket` module.
Tests are written with [`pytest`](https://docs.pytest.org/en/stable/).
See the [Getting Started](https://docs.pytest.org/en/stable/getting-started.html) for additional help.

## Run tests

- run all tests using the command (from the root pyenergymarket folder should be):
```
>pytest tests
```
- run specific folder or file tests using the command (from the root pyenergymarket folder should be):
```
>pytest tests/test_energymarket.py
```

see [how to invoke pytest](https://docs.pytest.org/en/stable/how-to/usage.html) for more information.

>**NOTE**<br>
>`pytest` is an optional dependency that is installed if the `test` option is given.

## Location of data

>Please don't put large data files in the repository as this becomes really messy with git.
> Test data may be safely placed in `tests/localdata` which is included in `.gitignore`

The tests [`test_energymarket.py`](./test_energymarket.py), [`test_fuelcurve.py`](./test_fuelcurve.py),
and [`test_acpfmodel.py`](./test_acpfmodel.py) reference the following files. For access contact
Molly Rose Kelly-Gorham ( <mollyrose.kelly-gorham@pnnl.gov> ) or Eran Schweitzer ( <eran.schweitzer@pnnl.gov> ):

| filepath | description|
|:-------- |:-----------|
|`h5path = "tests/localdata/WECC240_20240807.h5"` | path where the h5 file to run a market instance is located |
|`pwdpath = "tests/localdata/240busWECC_2018_PSS.pwb"` | path where the h5 file to run a market instance is located |
|`solpath = "tests/localdata/test_[test_name]_solution.json"` | location of solution used to compare result after solving|
