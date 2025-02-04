from __future__ import annotations
import pandas as pd
import numpy as np
import networkx as nx
from typing import Union, Iterable

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .__init__ import GVParse

def get_topology_subgraph(self:GVParse):
    """Create a graph model of the connected component including the 
    reference bus. 
    Only elements within this component will be parsed.
    """

    G = self.h5.create_nx_graph()
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    
    usecomp = [self.refbus in c for c in comps].index(True)

    self.logger.info(f"Using component {usecomp} of {len(comps)} with {len(comps[usecomp])} elements, which contains reference bus {self.refbus}.")
    
    Gsub : nx.Graph = nx.subgraph(G, comps[usecomp])

    self.G = Gsub

def include_bus(self:GVParse, busid:int) -> bool:
    """Returns true if the bus is in the subgraph under consideration.

    Args:
        busid (int): bus number to check

    Returns:
        bool: True=is in subgraph, False=is not in subgraph
    """

    return self.G.has_node(busid)

def include_branch(self:GVParse, from_bus:int, to_bus:int) -> bool:
    """Returns true if both the from and two buses of a branch are in the subgraph.
    IMPORTANT: this does not verify that the edge is actually in the graph.

    Args:
        from_bus (int): from bus number
        to_bus (int): to bus number

    Returns:
        bool: True=include branch, False=exclude branch
    """

    # instead of verifying whether the edge exists, we'll just verify
    # that both ends are nodes in the graph.
    return self.include_bus(from_bus) and self.include_bus(to_bus)