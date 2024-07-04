import pyenergymarket as pyen
import argparse, sys

def print_daterange(gv:pyen.GVParse):
    print(gv.h5("/area/LOAD"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="test gvparser")
    parser.add_argument("h5path", help="path to h5 file to test")
    parser.add_argument("--get-daterange", help="print the daterange in the h5", action="store_true")
    args = parser.parse_args()
    
    default = {
        "time": {
            "datefrom": "2032-01-01"
        },
        "elements": {
            "branch":{
                "rating_long_term": "A",
                "rating_short_term": "A",
                "rating_emergency": "B"
            },
            "generator": {
                "generator_type_map":{
                    "storage": [3, 10]
                }
            }
        }
    }

    gv = pyen.GVParse(args.h5path, default=default, logger_options={"level": "DEBUG"})
    if args.get_daterange:
        print_daterange(gv)
        sys.exit(0)
    gv.logger.info("Adding system info...", end="")
    gv.add_sys_info()
    gv.logger.info("complete")
    gv.logger.info("Adding buses...", end="")
    gv.add_buses()
    gv.logger.info("complete")
    gv.logger.info("Adding branches...", end="")
    gv.add_branches()
    gv.logger.info("complete")
    gv.logger.info("Adding load...", end="")
    gv.add_load()
    gv.logger.info("complete")
    gv.logger.info("Adding generators...", end="")
    gv.add_generators()
    gv.logger.info("complete")
    gv.logger.info("Converting data for saving...", end="")
    gv.data_convert()
    gv.logger.info("complete")
    gv.h5.close()
    gv.mdl.write("gv2egret_test.json")
    