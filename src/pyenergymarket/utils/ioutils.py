"""Utilities relating to handling of data input and output should be
place here.
"""
def merge_configs(defaults:dict, user:dict, level=0):
    """update the default options with user inputs"""
    for k, v in user.items():
        if k not in defaults:
            if level == 0:
                # if this is a top level configuration key, raise warning
                print(f"WARNING: configuration parameter {k} is unknown. Check spelling and capitalization perhaps?")
            defaults[k] = v
        else:
            if isinstance(v, dict):
                merge_configs(defaults[k], v, level=level+1)
            else:
                defaults[k] = v