#!/usr/bin/env python3

# Copyright (c) 2018 The unit-e core developers
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


from asyncio import (
    AbstractEventLoop,
    coroutine,
    sleep as asyncio_sleep
)
from os import (
    getenv,
    listdir,
    remove as remove_file
)
from os.path import (
    dirname,
    isdir,
    join as join_path,
    normpath,
    realpath
)
from shutil import (
    copytree,
    rmtree
)
from tempfile import mkdtemp

import test_framework.util as tf_util

from graph import (
    ensure_one_inbound_connection_per_node,
    create_directed_graph,
)
from test_framework.nodes_hub import NodesHub
from test_framework.test_node import TestNode
from test_framework.util import (
    get_datadir_path,
    initialize_datadir,
    p2p_port,
    set_node_times,
    sync_blocks
)


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
        create_cache = False

        for i in range(self.num_nodes):
            if not isdir(get_datadir_path(self.cache_dir, i)):
                create_cache = True
                break

        if create_cache:
            self.create_chain_cache()

        for i in range(self.num_nodes):
            from_dir = get_datadir_path(self.cache_dir, i)
            to_dir = get_datadir_path(self.tmp_dir, i)
            copytree(from_dir, to_dir)
            initialize_datadir(self.tmp_dir, i)

    def create_chain_cache(self):
        for i in range(self.num_nodes):
            if isdir(get_datadir_path(self.cache_dir, i)):
                rmtree(get_datadir_path(self.cache_dir, i))

        for i in range(self.num_nodes):
            datadir = initialize_datadir(self.cache_dir, i)
            args = [getenv('UNITED', 'united'), '-server', '-keypool=1', '-datadir=' + datadir, '-discover=0']
            if i > 0:
                args.append('-connect=127.0.0.1:%s' % p2p_port(0))
            self.nodes.append(TestNode(
                i, self.cache_dir, extra_args=[], rpchost=None, timewait=None, binary=None, stderr=None,
                mocktime=self.mocktime, coverage_dir=None
            ))
            self.nodes[i].args = args
            self.start_node(i)

        for node in self.nodes:
            node.wait_for_rpc_connection()

        # Create a 200-block-long chain; each of the 4 first nodes gets 25 mature blocks and 25 immature.
        # Note: To preserve compatibility with older versions of initialize_chain, only 4 nodes will generate coins.
        # Blocks are created with timestamps 10 minutes apart starting from 2010 minutes in the past
        self.enable_mocktime()
        block_time = self.mocktime - (201 * 10 * 60)
        for i in range(2):
            for peer in range(4):
                for j in range(25):
                    set_node_times(self.nodes, block_time)
                    self.nodes[peer].generate(1)
                    block_time += 10 * 60
                # Must sync before next peer starts generating blocks
                sync_blocks(self.nodes)

        # Shut them down, and clean up cache directories:
        self.stop_nodes()
        self.nodes = []
        self.disable_mocktime()

        def cache_path(n, *paths):
            return join_path(get_datadir_path(self.cache_dir, n), 'regtest', *paths)

        for i in range(self.num_nodes):
            for entry in listdir(cache_path(i)):
                if entry not in ['wallets', 'chainstate', 'blocks']:
                    remove_file(cache_path(i, entry))

    def enable_mocktime(self):
        self.mocktime = 1388534400 + (201 * 10 * 60)  # 2014/01/01 + (201 * 10 * 60) seconds

    def disable_mocktime(self):
        self.mocktime = 0

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
