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

A project share drive is available at \\\PNL\Projects\ECOMP where data can be stored.
The tests can then refer to this folder and data therein.

For example the [`test_energymarket.py`](./test_energymarket.py) references the following two files:
| filepath | description|
|:-------- |:-----------|
|`h5path = r"\\PNL\Projects\ECOMP\Shared Data\H5Files\WECC240_20240807.h5"` | path where the h5 file to run an market instance is located |
|`solpath = r"\\PNL\Projects\ECOMP\Shared Data\PyEnergyMarketTestData\test_energymarket_solution.json"` | location of solution used to compare result after solving|