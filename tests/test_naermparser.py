import gzip
import json
from unittest import mock

import h5py
import numpy as np
import pandas as pd
import pytest

from pyenergymarket.parsers.naermparser import (
    NAERMProvider,
    TimeSeries,
    assign_ts_values,
    clean_egret_time_series,
    create_egret_md,
    create_ts_uid_to_idx_map,
    enforce_p_min_p_max_consistency,
    get_persistent_ts_value,
    is_egret_time_series,
    is_persistent_time_series,
    is_time_series,
    read_json_gzip,
    read_str_array_from_h5,
    remove_non_time_series,
)


# Mock data creation utilities
def create_mock_json_gzip_file(data, tmp_path, filename):
    """Create a mock .json.gz file for testing"""
    filepath = tmp_path / filename
    with gzip.open(filepath, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    return filepath


def create_mock_h5_file(tmp_path, filename):
    """Create a mock HDF5 file for testing"""
    filepath = tmp_path / filename

    with h5py.File(filepath, "w") as f:
        # Create name dataset
        names = np.array(["load1", "load2", "gen1", "gen2"], dtype="S10")
        f.create_dataset("name", data=names)

        # Create uid dataset
        uids = np.array(["L1", "L2", "G1", "G2"], dtype="S10")
        f.create_dataset("uid", data=uids)

        # Create timestamp dataset - 24 hours starting from Jan 1, 2024 00:00 UTC
        # Make sure to use a timezone-aware approach that matches pd.date_range
        start_time = int(pd.Timestamp("2024-01-01 00:00:00").timestamp())
        timestamps = np.array([start_time + i * 3600 for i in range(24)], dtype=np.int64)
        f.create_dataset("timestamp", data=timestamps)

        # Create values dataset - Random values for 4 entities over 24 hours
        values = np.random.rand(24, 4)  # 24 hours, 4 entities
        f.create_dataset("values", data=values)

    return filepath


# Example mock data
mock_static_data = {
    "system": {"name": "test_system", "base_power": 100.0},
    "elements": {
        "bus": {"bus1": {"base_kv": 138.0}, "bus2": {"base_kv": 345.0}},
        "branch": {
            "branch1": {
                "from_bus": "bus1",
                "to_bus": "bus2",
                "branch_type": "line",
                "rating_long_term": {
                    "data_type": "persistent_time_series",
                    "timestamps": [1704067200, 1704153600],  # Jan 1, 2024 and Jan 2, 2024
                    "values": [100.0, 110.0],
                },
            }
        },
        "generator": {
            "gen1": {
                "bus": "bus1",
                "generator_type": "thermal",
                "p_min": 10.0,
                "p_max": {
                    "data_type": "time_series",
                    "time_series_uid": "G1",
                    "scale_factor": 100.0,
                },
            },
            "gen2": {
                "bus": "bus2",
                "generator_type": "renewable",
                "model_type": "PV",
                "p_min": {"data_type": "time_series", "time_series_uid": "G2", "scale_factor": 0.0},
                "p_max": {
                    "data_type": "time_series",
                    "time_series_uid": "G2",
                    "scale_factor": 50.0,
                },
            },
        },
        "load": {
            "load1": {
                "bus": "bus1",
                "p": {"data_type": "time_series", "time_series_uid": "L1", "scale_factor": 80.0},
            }
        },
    },
}


# Tests for helper functions
class TestHelperFunctions:
    @pytest.fixture(scope="function")
    def setup_files(self, tmp_path):
        """Set up test files and clean up after tests"""
        # Create test files
        static_file = create_mock_json_gzip_file(mock_static_data, tmp_path, "test_static.json.gz")
        ts_file = create_mock_h5_file(tmp_path, "test_ts.h5")

        return {"static_file": static_file, "ts_file": ts_file, "tmp_path": tmp_path}

    def test_read_json_gzip(self, setup_files):
        """Test reading a gzipped JSON file"""
        data = read_json_gzip(setup_files["static_file"])
        assert data is not None
        assert data["system"]["name"] == "test_system"
        assert "elements" in data
        assert "bus" in data["elements"]

    def test_read_json_gzip_file_not_found(self, tmp_path):
        """Test reading a non-existent file"""
        non_existent_file = tmp_path / "non_existent_file.json.gz"
        data = read_json_gzip(str(non_existent_file))
        assert data is None

    def test_read_str_array_from_h5(self, setup_files):
        """Test reading string array from H5 file"""
        with h5py.File(setup_files["ts_file"], "r") as h5f:
            names = read_str_array_from_h5(h5f["name"])
            assert isinstance(names, np.ndarray)
            assert np.issubdtype(names.dtype, np.str_)  # Check if it's a string type
            assert list(names) == ["load1", "load2", "gen1", "gen2"]

    def test_is_time_series(self):
        """Test is_time_series function"""
        # Valid time series
        ts = {"data_type": "time_series", "time_series_uid": "G1", "scale_factor": 100.0}
        assert is_time_series(ts)

        # Not a dict
        assert not is_time_series("not a dict")

        # Missing required keys
        assert not is_time_series({"data_type": "time_series"})
        assert not is_time_series({"time_series_uid": "G1"})
        assert not is_time_series({"scale_factor": 100.0})

    def test_is_egret_time_series(self):
        """Test is_egret_time_series function"""
        # Valid Egret time series
        ts = {"data_type": "time_series", "values": [100.0, 110.0, 120.0]}
        assert is_egret_time_series(ts)

        # Not a dict
        assert not is_egret_time_series("not a dict")

        # Missing or wrong data_type
        assert not is_egret_time_series({"values": [100.0]})
        assert not is_egret_time_series({"data_type": "wrong", "values": [100.0]})

    def test_is_persistent_time_series(self):
        """Test is_persistent_time_series function"""
        # Valid persistent time series
        pts = {
            "data_type": "persistent_time_series",
            "timestamps": [1704067200, 1704153600],
            "values": [100.0, 110.0],
        }
        assert is_persistent_time_series(pts)

        # Not a dict
        assert not is_persistent_time_series("not a dict")

        # Missing or wrong data_type
        assert not is_persistent_time_series({"timestamps": [1], "values": [1]})
        assert not is_persistent_time_series({"data_type": "wrong"})

    def test_create_ts_uid_to_idx_map(self):
        """Test create_ts_uid_to_idx_map function"""
        ts_uid = ["L1", "L2", "G1", "G2"]
        ts_map = create_ts_uid_to_idx_map(ts_uid)

        assert ts_map == {"L1": 0, "L2": 1, "G1": 2, "G2": 3}

    def test_get_persistent_ts_value(self):
        """Test get_persistent_ts_value function"""
        pts = {
            "data_type": "persistent_time_series",
            "timestamps": [1704067200, 1704153600, 1704240000],  # Jan 1, 2, 3, 2024
            "values": [100.0, 110.0, 120.0],
        }

        # Get value at exact timestamp
        assert get_persistent_ts_value(pts, 1704067200) == 100.0

        # Get value at timestamp between entries
        assert get_persistent_ts_value(pts, 1704110400) == 100.0  # Jan 1, 12:00

        # Get value after last entry
        assert get_persistent_ts_value(pts, 1704326400) == 120.0  # Jan 4

        # Test error case - timestamp before first entry
        with pytest.raises(Exception, match="persistent time series .* does not contain"):
            get_persistent_ts_value(pts, 1703980800)  # Dec 31, 2023

    def test_clean_egret_time_series(self):
        """Test clean_egret_time_series function"""
        # Test with float scale_factor
        ts = {
            "data_type": "time_series",
            "time_series_uid": "G1",
            "scale_factor": 100.0,
            "values": [90.0, 95.0, 100.0],
        }

        clean_egret_time_series(ts)
        assert "time_series_uid" not in ts
        assert "scale_factor" not in ts
        assert ts["reference_value"] == 100.0

        # Test with list scale_factor
        ts = {
            "data_type": "time_series",
            "time_series_uid": ["G1", "G2"],
            "scale_factor": [50.0, 50.0],
            "scale_factor_idx": [0, 1],
            "values": [90.0, 95.0, 100.0],
        }

        clean_egret_time_series(ts)
        assert "time_series_uid" not in ts
        assert "scale_factor" not in ts
        assert "scale_factor_idx" not in ts
        assert ts["reference_value"] == 100.0

        # Test error case - invalid scale_factor type
        ts = {
            "data_type": "time_series",
            "time_series_uid": "G1",
            "scale_factor": "invalid",
            "values": [90.0, 95.0, 100.0],
        }

        with pytest.raises(Exception, match="scale factor.*neither float or list"):
            clean_egret_time_series(ts)

    def test_assign_ts_values(self):
        """Test assign_ts_values function"""
        ts = {
            "values": np.array(
                [[10.0, 20.0, 30.0, 40.0], [15.0, 25.0, 35.0, 45.0], [20.0, 30.0, 40.0, 50.0]]
            )
        }
        ts_uid_to_idx = {"L1": 0, "L2": 1, "G1": 2, "G2": 3}

        # Test with single uid
        elem_ts = {"data_type": "time_series", "time_series_uid": "G1", "scale_factor": 2.0}

        assign_ts_values(elem_ts, ts, ts_uid_to_idx)
        assert elem_ts["values"] == [60.0, 70.0, 80.0]
        assert "time_series_uid" not in elem_ts
        assert "scale_factor" not in elem_ts

        # Test with multiple uids
        elem_ts = {
            "data_type": "time_series",
            "time_series_uid": ["L1", "L2"],
            "scale_factor": [1.0, 0.5],
        }

        assign_ts_values(elem_ts, ts, ts_uid_to_idx)
        assert elem_ts["values"] == [20.0, 27.5, 35.0]
        assert "time_series_uid" not in elem_ts
        assert "scale_factor" not in elem_ts

    def test_enforce_p_min_p_max_consistency(self):
        """Test enforce_p_min_p_max_consistency function"""
        md_elem_gen = {
            "gen1": {"generator_type": "thermal", "p_min": 10.0, "p_max": 100.0},
            "gen2": {
                "generator_type": "renewable",
                "model_type": "PV",
                "p_min": {"data_type": "time_series", "values": [0.0, 20.0, 10.0]},
                "p_max": {
                    "data_type": "time_series",
                    "values": [50.0, 50.0, 5.0],  # inconsistent at index 2
                },
            },
        }

        # Capture print output for checking warnings
        with mock.patch("builtins.print") as mocked_print:
            enforce_p_min_p_max_consistency(md_elem_gen)

            # Verify warning was printed
            mocked_print.assert_called_once()

            # Check values are corrected
            assert md_elem_gen["gen2"]["p_min"]["values"] == [0.0, 20.0, 0.0]
            assert md_elem_gen["gen2"]["p_max"]["values"] == [50.0, 50.0, 0.0]

    def test_remove_non_time_series(self):
        """Test remove_non_time_series function"""
        md_elem = {
            "generator": {
                "gen1": {
                    "p_min": 10.0,
                    "p_max": {
                        "data_type": "time_series",
                        "values": [100.0],  # Single value time series should be converted
                    },
                }
            },
            "load": {
                "load1": {
                    "p": {
                        "data_type": "time_series",
                        "values": [80.0, 85.0, 90.0],  # Multi-value time series should remain
                    }
                }
            },
        }

        # Capture print output for checking warnings
        with mock.patch("builtins.print") as mocked_print:
            remove_non_time_series(md_elem)

            # Verify warning was printed
            mocked_print.assert_called_once()

            # Check single-value time series was converted to scalar
            assert md_elem["generator"]["gen1"]["p_max"] == 100.0

            # Check multi-value time series was not converted
            assert md_elem["load"]["load1"]["p"]["data_type"] == "time_series"
            assert "values" in md_elem["load"]["load1"]["p"]

    def test_create_egret_md(self):
        """Test create_egret_md function"""
        # Create minimal model data
        md = {
            "system": {},
            "elements": {
                "generator": {
                    "gen1": {
                        "generator_type": "thermal",  # Adding required field
                        "p_min": 10.0,  # Adding p_min
                        "p_max": {
                            "data_type": "time_series",
                            "time_series_uid": "G1",
                            "scale_factor": 100.0,
                        },
                    }
                },
                "load": {
                    "load1": {
                        "p": {
                            "data_type": "time_series",
                            "time_series_uid": "L1",
                            "scale_factor": 80.0,
                        }
                    }
                },
                "branch": {
                    "branch1": {
                        "from_bus": "bus1",  # Adding required fields
                        "to_bus": "bus2",
                        "branch_type": "line",
                        "rating_long_term": {
                            "data_type": "persistent_time_series",
                            "timestamps": [1704067200, 1704153600],  # Jan 1, 2024 and Jan 2, 2024
                            "values": [100.0, 110.0],
                        },
                    }
                },
            },
        }

        # Create time series data
        ts = {
            "name": np.array(["load1", "gen1"]),
            "uid": np.array(["L1", "G1"]),
            "timestamp": np.array([1704067200, 1704153600]),  # Jan 1, 2024 and Jan 2, 2024
            "values": np.array([[0.5, 0.8], [0.6, 0.9]]),  # 2 timestamps, 2 entities (load1, gen1)
        }

        # Capture print output to avoid cluttering test results
        with mock.patch("builtins.print"):
            # Call the function under test
            result = create_egret_md(md, ts)

            # Verify the results
            assert "time_keys" in result["system"]
            assert len(result["system"]["time_keys"]) == 2

            # Check time series were converted to values
            assert "values" in result["elements"]["generator"]["gen1"]["p_max"]
            assert len(result["elements"]["generator"]["gen1"]["p_max"]["values"]) == 2
            assert result["elements"]["generator"]["gen1"]["p_max"]["values"][0] == 0.8 * 100.0

            # Check persistent time series were converted to values
            assert isinstance(result["elements"]["branch"]["branch1"]["rating_long_term"], float)


# Tests for TimeSeries class
class TestTimeSeries:
    @pytest.fixture(scope="function")
    def ts_file(self, tmp_path):
        """Create a test time series file"""
        return create_mock_h5_file(tmp_path, "test_time_series.h5")

    @pytest.fixture
    def time_series(self, ts_file):
        """Create TimeSeries instance for testing"""
        ts = TimeSeries(ts_file)
        yield ts
        # Cleanup happens automatically when fixture goes out of scope

    def test_init(self, time_series):
        """Test TimeSeries initialization"""
        assert isinstance(time_series.name, np.ndarray)
        assert isinstance(time_series.uid, np.ndarray)
        assert list(time_series.name) == ["load1", "load2", "gen1", "gen2"]
        assert list(time_series.uid) == ["L1", "L2", "G1", "G2"]

    def test_unix_tmstamp_to_idx_forw(self, time_series):
        """Test _unix_tmstamp_to_idx_forw method"""
        # Get the first timestamp from the file
        first_ts = time_series._timestamp[0]
        last_ts = time_series._timestamp[-1]

        # Test exact match
        assert time_series._unix_tmstamp_to_idx_forw(first_ts) == 0

        # Test timestamp between entries
        midpoint_ts = first_ts + 1800  # 30 minutes after first entry
        assert time_series._unix_tmstamp_to_idx_forw(midpoint_ts) == 1

        # Test error for timestamp AFTER last entry (which is what the implementation checks)
        # Looking at the code, it raises ValueError if there's no timestamp >= unix_tmstamp
        with pytest.raises(ValueError):
            time_series._unix_tmstamp_to_idx_forw(last_ts + 3600000)  # Timestamp after the last one

    def test_unix_tmstamp_to_idx_back(self, time_series):
        """Test _unix_tmstamp_to_idx_back method"""
        # Get the first and last timestamps from the file
        first_ts = time_series._timestamp[0]
        last_ts = time_series._timestamp[-1]

        # Test exact match
        assert time_series._unix_tmstamp_to_idx_back(last_ts) == len(time_series._timestamp) - 1

        # Test timestamp between entries
        midpoint_ts = last_ts - 1800  # 30 minutes before last entry
        assert time_series._unix_tmstamp_to_idx_back(midpoint_ts) == len(time_series._timestamp) - 2

        # Test error for timestamp BEFORE first entry (which is what the implementation checks)
        # Looking at the code, it raises ValueError if there's no timestamp <= unix_tmstamp
        with pytest.raises(ValueError):
            # Timestamp before the first one
            time_series._unix_tmstamp_to_idx_back(first_ts - 3600000)

    def test_asdict(self, time_series):
        """Test asdict method"""
        # Get full time series
        ts_dict = time_series.asdict()
        assert "name" in ts_dict
        assert "uid" in ts_dict
        assert "timestamp" in ts_dict
        assert "values" in ts_dict
        assert len(ts_dict["timestamp"]) == 24  # 24 hours

        # Get time series with specified start/end
        first_ts = time_series._timestamp[0]
        middle_ts = time_series._timestamp[12]

        ts_dict = time_series.asdict(first_ts, middle_ts)
        assert len(ts_dict["timestamp"]) == 13  # First 13 hours
        assert ts_dict["timestamp"][0] == first_ts
        assert ts_dict["timestamp"][-1] == middle_ts
        assert ts_dict["values"].shape == (13, 4)  # 13 hours, 4 entities


# Tests for NAERMProvider class
class TestNAERMProvider:
    @pytest.fixture(scope="function")
    def setup_files(self, tmp_path):
        """Set up test files for NAERMProvider"""
        file_name = "test_naerm_static.json.gz"
        static_file = create_mock_json_gzip_file(mock_static_data, tmp_path, file_name)
        ts_file = create_mock_h5_file(tmp_path, "test_naerm_ts.h5")

        return {"static_file": static_file, "ts_file": ts_file}

    @pytest.fixture
    def provider(self, setup_files):
        """Create NAERMProvider instance for testing"""
        provider = NAERMProvider(setup_files["static_file"], setup_files["ts_file"])
        return provider

    def test_init(self, provider):
        """Test NAERMProvider initialization"""
        # Since attributes are private, we can't directly test them
        # Instead, verify provider is properly initialized by calling methods
        assert provider is not None

    def test_get_time_series_none(self, provider):
        """Test _get_time_series with None daterange"""
        ts_dict = provider._get_time_series(None)
        assert "name" in ts_dict
        assert "uid" in ts_dict
        assert "timestamp" in ts_dict
        assert "values" in ts_dict

    def test_get_time_series_with_daterange(self, provider):
        """Test _get_time_series with specified daterange"""
        # Create a daterange for the first 6 hours that will match our H5 file timestamps
        daterange = pd.date_range(start="2024-01-01 00:00:00", periods=6, freq="h")

        # Ensure exact timezone matching by explicitly converting to UTC timestamp
        # This makes our daterange match the timestamps in our mock H5 file
        daterange = pd.DatetimeIndex([pd.Timestamp(dt).replace(tzinfo=None) for dt in daterange])

        ts_dict = provider._get_time_series(daterange)
        assert len(ts_dict["timestamp"]) == 6
        assert ts_dict["values"].shape == (6, 4)  # 6 hours, 4 entities

    def test_get_time_series_empty_daterange(self, provider):
        """Test _get_time_series with empty daterange"""
        empty_daterange = pd.DatetimeIndex([])
        with pytest.raises(ValueError):
            provider._get_time_series(empty_daterange)

    def test_get_model(self, provider):
        """Test get_model method"""
        # Create a daterange for 24 hours that will match our H5 file timestamps
        daterange = pd.date_range(start="2024-01-01 00:00:00", periods=24, freq="h")

        # Ensure exact timezone matching by explicitly converting to UTC timestamp
        # This makes our daterange match the timestamps in our mock H5 file
        daterange = pd.DatetimeIndex([pd.Timestamp(dt).replace(tzinfo=None) for dt in daterange])

        # Get model for the daterange
        model = provider.get_model(daterange)

        # Verify model is created correctly
        assert model is not None
        assert isinstance(model.data, dict)
        assert "system" in model.data
        assert "time_keys" in model.data["system"]
        assert len(model.data["system"]["time_keys"]) == 24

        # Verify time series references are replaced with values
        gen1 = model.data["elements"]["generator"]["gen1"]
        assert isinstance(gen1["p_max"], dict)
        assert "values" in gen1["p_max"]
        assert len(gen1["p_max"]["values"]) == 24

        # Verify persistent time series are replaced with values
        branch1 = model.data["elements"]["branch"]["branch1"]
        assert isinstance(branch1["rating_long_term"], float)
