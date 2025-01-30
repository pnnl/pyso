from pytest import approx
import platform, os

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
    print(f"d1: {d1}\nd2: {d2}")
    for k,v in d1.items():
        if isinstance(v, dict):
            dictionary_testing(v, d2[k])
        elif isinstance(v, list):
            list_testing(v, d2[k])
        else:
            assert v == approx(d2[k])  
            
def list_testing(l1, l2):
    print(f"l1: {l1}\nl2: {l2}")
    for i, j in zip(l1, l2):
        if isinstance(i, dict):
            dictionary_testing(i,j)
        elif isinstance(i, list):
            list_testing(i,j)
        else:
            assert i == approx(j)

def os_safe_networkpath(path:str) -> str:
    """Return a platform specific path onto the E-COMP network drive

    Args:
        path (str): path in windows format (\\PNNL\Projects\ECOMP\...)

    Raises:
        FileNotFoundError: If path not mounted on unix machines

    Returns:
        str: platform appropriate path
    """

    if platform.system() == 'Windows':
        return path
    else:
        unixbase = '/Volumes/Shared Data'
        p = path.split(r"\\PNL\Projects\ECOMP\Shared Data")[1]
        h5path = os.path.join(unixbase, *p.replace("\\","/").split("/"))
        if not os.path.exists(h5path):
            raise FileNotFoundError(f'{h5path} not found. Please mount smb://pnl/Projects/ECOMP/Shared Data')
        return h5path