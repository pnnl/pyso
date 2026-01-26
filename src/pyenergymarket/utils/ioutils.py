"""Utilities relating to handling of data input and output should be
place here.
"""

import copy
import gzip
import importlib
import logging
import sys
from collections.abc import Mapping

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING

import tomli
import tomli_w

if TYPE_CHECKING:
    pass


def save_config(filepath: str, data: dict) -> None:
    """
    Saves a dictionary into a TOML configuration file, supporting gzip compression.

    Args:
        filepath (str): The path where the TOML configuration file will be saved. If the
            filepath ends with '.gz', the content is compressed in Gzip format.
        data (dict): A dictionary containing the data to be saved.

    """
    if filepath.endswith(".gz"):
        with gzip.open(filepath, "wb") as outfile:
            tomli_w.dump(data, outfile)
    else:
        with open(filepath, "wb") as outfile:
            tomli_w.dump(data, outfile)


def load_config(filepath: str, default_path: str = None) -> dict:
    """
    Load and merge TOML configuration files, supporting gzip compression.

    This function loads configuration settings from a user-specified TOML file
    and optionally merges them with default settings from another TOML file.
    User settings take precedence over default settings.

    Args:
        filepath (str): The path to the user-specified TOML configuration file.
        default_path (str, optional): The path to the default TOML configuration file.
            If not provided or None, no default settings are used.

    Returns:
        dict: A dictionary containing the combined configuration settings,
        where user settings override default settings.
    """
    inputs = {}
    if default_path is not None:
        if default_path.endswith(".gz"):
            with gzip.open(default_path, mode="rb") as f:
                inputs = tomli.load(f)
        else:
            with open(default_path, mode="rb") as f:
                inputs = tomli.load(f)

    user = {}
    if filepath:
        if filepath.endswith(".gz"):
            with gzip.open(filepath, mode="rb") as f:
                user = tomli.load(f)
        else:
            with open(filepath, mode="rb") as f:
                user = tomli.load(f)

    inputs = merge_dicts(inputs, user)

    return inputs


def merge_dicts(d1: dict, d2: dict) -> dict:
    """Recursively merges two dictionaries.

    Args:
        d1 (dict): The first dictionary to merge. This is typically the base dictionary.
        d2 (dict): The second dictionary to merge. This dictionary's values will overwrite those in d1 where there are conflicts.

    Returns:
        dict: A new dictionary which is the result of merging d2 into d1.
    """
    merged = copy.deepcopy(d1)
    for k, v in d2.items():
        if isinstance(v, Mapping):
            merged[k] = merge_dicts(merged.get(k, {}), v)
        else:
            merged[k] = v
    return merged


def merge_configs(defaults: dict, user: dict, level=0):
    """update the default options with user inputs"""
    for k, v in user.items():
        if k not in defaults:
            if level == 0:
                # if this is a top level configuration key, raise warning
                print(
                    f"WARNING: configuration parameter {k} is unknown. "
                    f"Check spelling and capitalization perhaps?"
                )
            defaults[k] = v
        else:
            if isinstance(v, dict):
                merge_configs(defaults[k], v, level=level + 1)
            else:
                defaults[k] = v


def format_filename(datetime_str):
    """formats a filename for use with the solved market model based on the current market time.
       current_time is the market operation time.
    example: filename = os.path.join(outdir,market+'_'+
                     pyen.utils.ioutils.format_filename(str(current_time))+'.json')
        used for saving solved market models during testing, prior to
        implementation of database.

    Parameters
    ----------
    datetime_str : string
        the datetime-formatted current time, converted to string

    Returns
    -------
    string
        reformatted datetime string
        example:
        from: '2032:01:01 00:00:00'
        to:   '2032-01-01_00-00-00'
    """
    return datetime_str.replace(":", "-").replace(" ", "_")


def print_inputs(d: dict, printf):
    from pprint import pformat

    sinput = pformat(d, sort_dicts=False, compact=True)
    printf(sinput)


def get_provider_by_name(name: str):
    module = importlib.import_module("pyenergymarket")
    try:
        return getattr(module, name)
    except AttributeError as err:
        raise ValueError(f"No DataProvider named {name} available.") from err


class Logger(logging.Logger):
    def __init__(self, name, level=logging.INFO, msg_format="{message}", **kwargs):
        self.name = name
        self.level = level
        self.logger = logging.getLogger(name)
        ## remove any handlers
        if self.logger.hasHandlers():
            while len(self.logger.handlers) > 0:
                h = self.logger.handlers.pop(0)
                self.logger.removeHandler(h)
            self.logger.handlers = []
        if isinstance(level, str):
            self.logger.setLevel(level.upper())
        else:
            self.logger.setLevel(level)

        self.formatter = logging.Formatter(msg_format, style="{")
        self.formatter_plain = logging.Formatter("{message}", style="{")

        ### add stream handler
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(self.formatter)
        self.logger.addHandler(stream_handler)

        self.formattoggle = False
        self.currentformat = "normal"

    def setlevel(self, level):
        """change the logging level"""
        if isinstance(level, str):
            level = level.upper()
        self.logger.setLevel(level)
        self.level = level
        for h in self.logger.handlers:
            h.setLevel(level)

    def getlevel(self):
        """return the logging level as a string"""
        if isinstance(self.level, str):
            return self.level
        if self.level == logging.DEBUG:
            return "DEBUG"
        elif self.level == logging.INFO:
            return "INFO"
        elif self.level == logging.WARNING:
            return "WARNING"
        elif self.level == logging.ERROR:
            return "ERROR"
        elif self.level == logging.CRITICAL:
            return "CRITICAL"

    def set_logfile(self, file=None, mode="w"):
        if file is None:
            file = self.name + ".log"
        file_handler = logging.FileHandler(file, mode=mode)
        file_handler.setFormatter(self.formatter)
        self.logger.addHandler(file_handler)

    def _logprint(self, level, *args, **kwargs):
        if "end" in kwargs:
            if self.currentformat == "normal":
                self.formattoggle = True
            self.set_terminator(char=kwargs["end"])
            kwargs.pop("end")
        elif self.currentformat == "plain":
            self.formattoggle = True

        self.logger.log(level, *args, **kwargs)

        if self.formattoggle:
            self.toggle_formatter()
            self.formattoggle = False
            self.set_terminator()

    def info(self, *args, **kwargs):
        self._logprint(logging.INFO, *args, **kwargs)

    def warning(self, *args, **kwargs):
        self._logprint(logging.WARNING, *args, **kwargs)

    def debug(self, *args, **kwargs):
        self._logprint(logging.DEBUG, *args, **kwargs)

    def error(self, *args, **kwargs):
        self._logprint(logging.ERROR, *args, **kwargs)

    def toggle_formatter(self):
        if self.currentformat == "normal":
            formatter = self.formatter_plain
            self.currentformat = "plain"
        else:
            formatter = self.formatter
            self.currentformat = "normal"
        for h in self.logger.handlers:
            h.setFormatter(formatter)

    def set_terminator(self, char="\n"):
        for h in self.logger.handlers:
            h.terminator = char

    def close(self):
        handlers = self.logger.handlers[:]
        for h in handlers:
            self.logger.removeHandler(h)
            h.close()
