from pytest import approx
from pyomo.opt import SolverFactory
from pyomo.common.errors import ApplicationError

# Imported function from Egret tests
def find_solver(requested_solver=None, return_mip_avail=False):
    if requested_solver is None:
        solver_list = ['xpress_persistent', 'gurobi_persistent', 'cplex_persistent', 'gurobi', 'cplex']
    else:
        solver_list = [requested_solver]
    test_solver = None
    comm_mip_avail = False
    for solver in solver_list:
        try:
            if SolverFactory(solver).available():
                test_solver = solver
                comm_mip_avail = True
                break
        except ApplicationError:
            continue
    if test_solver is None:
        for solver in ['cbc', 'glpk']:
            try:
                if SolverFactory(solver).available():
                    test_solver = solver
                    break
            except ApplicationError:
                continue
    if test_solver is None:
        raise RuntimeError("No MIP/LP solver found for unit commitment tests")
    if return_mip_avail:
        return test_solver, comm_mip_avail
    else:
        return test_solver

def dictionary_testing(d1:dict, d2:dict):
    """Test all elements of a dictionary using default
    precision.
    
    NOTE:
        It is assumed that the dictionaries share the same
        keys

    Args:
        d1 (dict): dictionary one
        d2 (dict): dictionary two
    """
    for k,v in d1.items():
        if isinstance(v, dict):
            dictionary_testing(v, d2[k])
        elif isinstance(v, list):
            list_testing(v, d2[k])
        else:
            assert v == approx(d2[k])  
            
def list_testing(l1, l2):
    for i, j in zip(l1, l2):
        if isinstance(i, dict):
            dictionary_testing(i,j)
        elif isinstance(i, list):
            list_testing(i,j)
        else:
            assert i == approx(j)