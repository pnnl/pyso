# Power World Parser
The power world parser is intended to load a power world power flow model to add reactive power limits to generators as well as shunt elements to the model.

>**NOTE:** The Power World Parser is **not** designed to be a data provider at the moment. It will **not** expose a `get_model` function that will generate a full Egret model

The design of this object is that it _receives_ an Egret model as input and updates it.
