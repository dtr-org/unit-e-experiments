#!/usr/bin/env python3

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

"""
This simulation script has been created to see how some settings/variables could affect the chain forks distribution.
The variables that are being considered are:
  - Latency
  - Bandwidth
  - Expected time between block creation
  - Number of proposer & relay nodes (not the numbers but their relative proportions)
  - Network Topology? (different graph generators, different parameters)

The outcomes that we want to observe are:
  - Number of chain forks' distribution across nodes (and maybe consider their depths too)
  - Number of orphan blocks' distribution across nodes

TODO: Add proper logging

TODO: Should we consider node centrality measures and see how they affect the outcomes?
TODO: Should we consider latencies (& bandwidths) distribution instead of one shared latency & bandwidth?
TODO: Should we relate latencies with nodes centrality?
"""


import sys

try:
    from settings import extra_import_paths
    for extra_path in extra_import_paths:
        sys.path.append(extra_path)
except ModuleNotFoundError:
    print('Missing import paths for Unit-E functional test packages')
    print('Copy "settings.py.example" to "settings.py" and adapt the paths')


from asyncio import (
    AbstractEventLoop,
    coroutine,
    sleep as asyncio_sleep
)
from os.path import (
    dirname,
    normpath,
    realpath
)
from shutil import rmtree
from tempfile import mkdtemp

import test_framework.util as tf_util

from graph import (
    ensure_one_inbound_connection_per_node,
    create_directed_graph,
)
from test_framework.nodes_hub import NodesHub
from test_framework.test_node import TestNode
from test_framework.util import initialize_datadir


class ForkingSimulation:
    def __init__(
            self, *,
            loop: AbstractEventLoop, latency: float, bandwidth: float, num_proposer_nodes: int, num_relay_nodes: int,
            simulation_time: float = 600, sample_time: float = 1, graph_model: str = 'preferential_attachment'
    ):
        if num_proposer_nodes < 0 or num_relay_nodes < 0:
            raise RuntimeError('Number of nodes must be positive')
        elif num_relay_nodes + num_proposer_nodes == 0:
            raise RuntimeError('Total number of nodes must be greater than 0')
        elif num_proposer_nodes > 4:
            raise RuntimeError('For now we only have 4 wallets with funds')

        self.loop = loop

        self.latency = latency  # For now just a shared latency parameter
        self.bandwidth = bandwidth  # Not used yet, here to outline the fact that we have to consider its effects

        self.num_proposer_nodes = num_proposer_nodes
        self.num_relay_nodes = num_relay_nodes
        self.num_nodes = num_proposer_nodes + num_relay_nodes

        self.graph_model = graph_model

        self.nodes = []
        self.graph_edges = set()
        self.nodes_hub = None

        self.simulation_time = simulation_time  # For how long the simulation will run
        self.sample_time = sample_time  # Time that passes between each sample

        self.mocktime = 0
        self.cache_dir = normpath(dirname(realpath(__file__)) + '/cache')
        self.tmp_dir = ''

        self.define_network_topology()

    def run(self):
        self.setup_directories()

        self.setup_chain()
        self.setup_nodes()
        self.start_nodes()

        self.nodes_hub = NodesHub(loop=self.loop, nodes=self.nodes, sync_setup=True)
        self.nodes_hub.sync_start_proxies()
        self.nodes_hub.sync_connect_nodes(self.graph_edges)
        # self.loop.run_until_complete(coroutine(self.sync_all)())  # TODO: Something like this

        # TODO: Configure wallets

        self.loop.create_task(self.sample_forever())  # TODO: This task should be cancelled when the simulation ends
        self.loop.run_until_complete(asyncio_sleep(self.simulation_time))

    @coroutine
    def sample_forever(self):
        while True:
            yield from asyncio_sleep(self.sample_time)
            yield from self.sample()

    @coroutine
    def sample(self):
        pass  # TODO: Register information and dump it to a CSV file

    def safe_run(self):
        try:
            self.run()
        finally:
            self.stop_nodes()
            self.cleanup_directories()
            self.loop.close()

    def setup_directories(self):
        self.tmp_dir = mkdtemp(prefix='simulation')

    def cleanup_directories(self):
        if self.tmp_dir != '':
            rmtree(self.tmp_dir)

    def setup_chain(self):
        for i in range(self.num_nodes):
            initialize_datadir(self.tmp_dir, i)

    def setup_nodes(self):
        self.nodes = [
            TestNode(
                i=i, dirname=self.tmp_dir, extra_args=[], rpchost=None, timewait=None, binary=None, stderr=None,
                mocktime=self.mocktime, coverage_dir=None, use_cli=False
            )
            for i in range(self.num_nodes)
        ]

    def start_node(self, i):
        node = self.nodes[i]
        try:
            node.start()
            node.wait_for_rpc_connection()
        except:
            self.stop_nodes()
            raise

    def start_nodes(self):
        try:
            for node in self.nodes:
                node.start()
            for node in self.nodes:
                node.wait_for_rpc_connection()
        except:
            self.stop_nodes()
            raise

    def stop_nodes(self):
        for node in self.nodes:
            node.stop_node()
        for node in self.nodes:
            node.wait_until_stopped()

    def define_network_topology(self):
        """This function just defines the network's topology"""

        graph_edges, inbound_degrees = create_directed_graph(
            num_nodes=self.num_nodes,
            num_outbound_connections=8,
            max_inbound_connections=125,
            model=self.graph_model
        )
        self.graph_edges, _ = ensure_one_inbound_connection_per_node(
            num_nodes=self.num_nodes,
            graph_edges=graph_edges,
            inbound_degrees=inbound_degrees
        )


def main():
    tf_util.MAX_NODES = 200  # We need more flexibility for our simulations
    # TODO: Load settings from cmd options and/or settings file and pass them to run_experiment
    pass


if __name__ == '__main__':
    main()
