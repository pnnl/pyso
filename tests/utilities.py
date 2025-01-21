from pytest import approx
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