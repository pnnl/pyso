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

def os_safe_h5path(h5path=r"\\PNL\Projects\ECOMP\Shared Data\H5Files\WECC240_20240807.h5"):
    """
    NOTE: this function is currently specific to the PNNL implementation and requires access
    to a PNNL shared drive.
    This is also not well-generalized for different file path inputs.

    This takes an h5path (default is specified for Windows) and
        IF system is Windows: returns h5path unchanged
        ELSE (Mac - may work on a Linux system): directs to a locally mounted drive
            REQUIRES you to mount the drive first. The defaults work if you mount
            'smb://pnl/Projects/ECOMP/Shared Data' in '/Volumes/Shared Data'
            This will be accomplished by connecting to 'smb://pnl/Projects/ECOMP/Shared Data'
            in Finder.
            ALSO NOTE: this mounting will generally need to be re-done every time you connect to the network
    """
    if platform.system() == 'Windows':
        return h5path
    else:
        h5path = '/Volumes/Shared Data/H5Files/WECC240_20240807.h5'
        if not os.path.exists(h5path):
            raise FileNotFoundError(f'{h5path} not found. Please mount smb://pnl/Projects/ECOMP/Shared Data')
        return h5path

def os_safe_solution_json(solution_json):
    """
    NOTE: this function is currently specific to the PNNL implementation and requires access
    to a PNNL shared drive.

    This takes a saved test solutions file (default is specified for Windows) and
        IF system is Windows: returns path to solution_json on the PNNL network drive
        ELSE (Mac - may work on a Linux system): directs to a locally mounted drive
            REQUIRES you to mount the drive first. The defaults work if you mount
            'smb://pnl/Projects/ECOMP/Shared Data' in '/Volumes/Shared Data'
            This will be accomplished by connecting to 'smb://pnl/Projects/ECOMP/Shared Data'
            in Finder.
            ALSO NOTE: this mounting will generally need to be re-done every time you connect to the network
    """
    if platform.system() == 'Windows':
        solution_path = f'r"\\PNL\Projects\ECOMP\Shared Data\PyEnergyMarketTestData\{solution_json}"'
    else:
        solution_path = f'/Volumes/Shared Data/PyEnergyMarketTestData/{solution_json}'
        if not os.path.exists(solution_path):
            raise FileNotFoundError(f'{solution_path} not found. Please mount smb://pnl/Projects/ECOMP/Shared Data')
    return solution_path