from setuptools import setup
from setuptools.command.develop import develop
from setuptools.command.install import install
from setuptools.command.egg_info import egg_info

#### Dependency checking
import importlib.util

def check_dependencies():
    with open("dependencies.log", "w") as f:
        dependencies = {"required": ["egret"],
                        "optional": ["pnnlpcm"]
        }
        sources = {"egret": "https://github.com/pnnl-private/egret",
                "pnnlpcm": "https://devops.pnnl.gov/ntp/ntp_PCM"}
        missing_dependencies = {"required": [], "optional": []}

        for typ, dlist in dependencies.items():
            for dependency in dlist:
                if importlib.util.find_spec(dependency) is None:
                    missing_dependencies[typ].append(dependency)

        for typ, dlist in missing_dependencies.items():
            if dlist:
                print(f"\nThe following {typ.upper()} dependencies are missing:", file=f)
                for dep in dlist:
                    print(f" - {dep} (source: {sources[dep]})", file=f)
                print("\nThey should be installed as editable packages using pip:", file=f)
                # for dep in dlist:
                print(f"Clone repository from source", file=f)
                print("cd into repository folder", file=f)
                print(f"pip install -e .", file=f)


#see: https://stackoverflow.com/questions/20288711/post-install-script-with-python-setuptools

class PostDevelopCommand(develop):
    """Post installation in develop mode"""
    def run(self):
        print("IN POST DEVELOP COMMAND")
        post_install()
        # install.run(self)
        super().run()

class PostEggCommand(egg_info):
    """Post installation in egg info mode"""
    def run(self):
        print("IN EGG INFO COMMAND")
        post_install()
        # install.run(self)
        super().run()
        

class PostInstallCommand(install):
    """Post installation in installation mode"""
    def run(self):
        print("IN POST INSTALL COMMAND", flush=True)
        post_install()
        # install.run(self)
        super().run()
        

def post_install():
    check_dependencies()
    
setup(
    name="pyenergymarket",
    cmdclass={
        "install": PostInstallCommand,
        "develop": PostDevelopCommand,
        "egg_info": PostEggCommand # https://stackoverflow.com/questions/19569557/pip-not-picking-up-a-custom-install-cmdclass
    },
)