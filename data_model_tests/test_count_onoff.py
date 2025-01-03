"""
This code tests the functionality of the pyenergymarket.utils.timeutils function
count_onoff

This is specific to determining the length of time a generator has been on or off
based on its commitment history and its initial status.
"""
import pandas as pd

from pyenergymarket.utils import timeutils
import argparse, os
import subprocess
import json

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="test gvparser")
    parser.add_argument("--h5path", help="path to h5 file to test")
    parser.add_argument("-v", "--verbose", help="If added will print results from each generator",
                        action="store_true")
    parser.add_argument("-d", "--different", help="If using verbose only prints generators which change status",
                        action="store_true")
    args = parser.parse_args()

    # Test is built on the test_energymarket.py solution. If it exists, we use that.
    # If the solution isn't found, we will run test_energymarket.py to create the solution
    if not os.path.isfile("pyenergy_test_solution.json"):
        if args.h5path is None:
            print("No solutions available. Please run test_energymarket.py or rerun with --h5path (path to h5 file)")
        subprocess.run("python", "test_energymarket.py", args.h5path)

    # Load the solution (this is dictionary in Egret ModelData format)
    with open("pyenergy_test_solution.json", "r") as f:
        test_solution = json.load(f)

    # Now pick a time partway through the day
    # At this time, we will set the initial status based on the commitment values
    min_freq = 60  # integer minutes used in RT solution
    system_times = test_solution["system"]["time_keys"]
    if min_freq < 60:
        system_times = pd.to_datetime(pd.date_range(start=system_times[0], end=system_times[-1], freq=min_freq))
    # test_time = test_times[int(len(test_times) / 2) + 1]
    t0idx = int(len(system_times) / 2) + 1
    print(f"selected initial time index {t0idx}: {system_times[t0idx]}")

    solution_out = {"elements": {}, "system": test_solution["system"]}
    # Loop through all elements. If the element is a generator, update the initial status
    for elem, e_dict in test_solution["elements"].items():
        solution_out["elements"][elem] = {}
        if elem == 'generator':
            # Loop through all generators
            for unit, u_dict in e_dict.items():
                # Update the initial statues with the new function
                prev_initial_status = u_dict["initial_status"]
                new_initial_status = timeutils.count_onoff(u_dict, t0idx, min_freq=min_freq)
                u_dict["initial_status"] = new_initial_status
                solution_out["elements"][elem][unit] = u_dict
                # Option to print results for each generator
                if args.verbose:
                    commits_tmp = u_dict["commitment"]
                    if isinstance(commits_tmp, dict):
                        commits = commits_tmp["values"][:t0idx+1]
                        print_commits = commits + ["<-t0idx"] + commits_tmp["values"][t0idx+1:]
                    if args.different:
                        if sum(commits) != 0 and sum(commits) != len(commits):
                            print(f"For generator {unit} setting initial status to {new_initial_status} based on "
                                  f"input initial_status {prev_initial_status} and commitments {print_commits}")
                    else:
                        print(f"For generator {unit} setting initial status to {new_initial_status} based on "
                              f"input initial_status {prev_initial_status} and commitments {print_commits}")

        else:
            # Pass all other values through
            solution_out["elements"][elem] = e_dict

    # Save output to json
    with open("count_onoff_test_solution.json", "w") as f:
        json.dump(solution_out, f, indent=4)