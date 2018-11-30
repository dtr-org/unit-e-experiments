#!/usr/bin/env python3

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

"""
This simulation script has been created to see how some settings/variables could
affect the chain forks distribution. The variables that are being considered
are:
  - Latency
  - Bandwidth
  - Expected time between block creation
  - Number of proposer & relay nodes (not the numbers but their relative
    proportions)
  - Network Topology? (different graph generators, different parameters)

The outcomes that we want to observe are:
  - Number of chain forks' distribution across nodes (and maybe consider their
    depths too)
  - Number of orphan blocks' distribution across nodes
"""


import sys

from asyncio import (
    AbstractEventLoop,
    coroutine,
    sleep as asyncio_sleep,
    get_event_loop,
)
from collections import defaultdict
from io import BytesIO
from logging import (
    INFO,
    basicConfig as logging_config,
    getLogger
)
from os.path import (
    dirname,
    normpath,
    realpath
)
from random import sample
from shutil import rmtree
from tempfile import mkdtemp
from time import time
from typing import (
    List,
    Optional,
    Set,
    Tuple
)

import test_framework.util as tf_util

from experiments.utils.graph import (
    enforce_nodes_reconnections,
    ensure_one_inbound_connection_per_node,
    create_directed_graph,
)
from experiments.utils.nodes_hub import NodesHub
from test_framework.regtest_mnemonics import regtest_mnemonics
from test_framework.test_node import TestNode
from test_framework.util import initialize_datadir


class ForkingSimulation:
    def __init__(
            self, *,
            loop: AbstractEventLoop,
            latency: float,
            num_proposer_nodes: int,
            num_relay_nodes: int,
            simulation_time: float = 600,
            sample_time: float = 1,
            graph_model: str = 'preferential_attachment',
            results_file_name: str = 'fork_simulation_results.csv'
    ):
        if num_proposer_nodes < 0 or num_relay_nodes < 0:
            raise RuntimeError('Number of nodes must be positive')
        elif num_relay_nodes + num_proposer_nodes == 0:
            raise RuntimeError('Total number of nodes must be greater than 0')
        elif num_proposer_nodes > 100:
            raise RuntimeError('For now we only have 100 wallets with funds')

        self.logger = getLogger('ForkingSimulation')
        self.loop = loop

        self.latency = latency  # For now just a shared latency parameter.

        self.num_proposer_nodes = num_proposer_nodes
        self.num_relay_nodes = num_relay_nodes
        self.num_nodes = num_proposer_nodes + num_relay_nodes

        self.graph_model = graph_model

        self.nodes: List[TestNode] = []
        self.graph_edges: Set[Tuple[int, int]] = set()
        self.nodes_hub: Optional[NodesHub] = None
        self.proposer_node_ids: List[int] = []

        self.simulation_time = simulation_time
        self.sample_time = sample_time

        self.start_time = 0

        self.cache_dir = normpath(dirname(realpath(__file__)) + '/cache')
        self.tmp_dir = ''

        self.results_file: Optional[BytesIO] = None
        self.results_file_name = results_file_name

        self.define_network_topology()

    def run(self):
        self.logger.info('Starting simulation')
        self.setup_directories()

        self.setup_chain()
        self.setup_nodes()
        self.start_nodes()

        self.nodes_hub = NodesHub(
            loop=self.loop, nodes=self.nodes, sync_setup=True
        )
        self.nodes_hub.sync_start_proxies()
        self.nodes_hub.sync_connect_nodes(self.graph_edges)

        # Setting deterministic delays (for now), would be better to use random
        # delays following exponential dist.
        for i in range(self.num_nodes):
            for j in range(self.num_nodes):
                self.nodes_hub.set_nodes_delay(i, j, self.latency)

        # Loading wallets... only for proposers (which are picked randomly)
        self.proposer_node_ids = sample(
            range(self.num_nodes), self.num_proposer_nodes
        )
        for idx, proposer_id in enumerate(self.proposer_node_ids):
            self.nodes[proposer_id].importmasterkey(
                regtest_mnemonics[idx]['mnemonics']
            )

        # Opening results file
        self.results_file = open(file=self.results_file_name, mode='wb')

        self.start_time = time()
        self.loop.create_task(self.sample_forever())
        self.loop.run_until_complete(asyncio_sleep(self.simulation_time))

    @coroutine
    def sample_forever(self):
        self.logger.info('Starting sampling process')
        while True:
            yield from asyncio_sleep(self.sample_time)
            yield from self.sample()

    @coroutine
    def sample(self):
        sample_time = time()
        time_delta = sample_time - self.start_time

        for node_id, node in enumerate(self.nodes):
            tip_stats = defaultdict(int)
            for tip in node.getchaintips():
                tip_stats[tip['status']] += 1

            # There's redundant data because it allows us to keep all the data
            # in one single file, without having to perform "join" operations of
            # any type.
            sample_line = map(str, [
                time_delta,
                self.latency,
                node_id,
                tip_stats['active'],
                tip_stats['valid-fork'],
                tip_stats['valid-headers'],
                tip_stats['headers-only'],
                # TODO: Add node centrality measures
            ])
            self.results_file.write((', '.join(sample_line) + '\n').encode())

    def safe_run(self):
        try:
            self.run()
        finally:
            if not self.results_file.closed:
                self.results_file.close()

            self.stop_nodes()
            self.cleanup_directories()
            self.loop.close()

    def setup_directories(self):
        self.logger.info('Preparing temporary directories')
        self.tmp_dir = mkdtemp(prefix='simulation')

    def cleanup_directories(self):
        self.logger.info('Cleaning temporary directories')
        if self.tmp_dir != '':
            rmtree(self.tmp_dir)

    def setup_chain(self):
        self.logger.info('Preparing "empty" chain')
        for i in range(self.num_nodes):
            initialize_datadir(self.tmp_dir, i)

    def setup_nodes(self):
        self.logger.info('Creating node wrappers')
        self.nodes = [
            TestNode(
                i=i, dirname=self.tmp_dir, extra_args=[], rpchost=None,
                timewait=None, binary=None, stderr=None, mocktime=0,
                coverage_dir=None, use_cli=False
            )
            for i in range(self.num_nodes)
        ]

    def start_node(self, i: int):
        node = self.nodes[i]
        try:
            node.start()
            node.wait_for_rpc_connection()
        except Exception:
            self.stop_nodes()
            raise

    def start_nodes(self):
        self.logger.info('Starting nodes')
        try:
            for node in self.nodes:
                node.start()
            for node in self.nodes:
                node.wait_for_rpc_connection()
        except Exception:
            self.stop_nodes()
            raise

    def stop_nodes(self):
        self.logger.info('Stopping nodes')
        for node in self.nodes:
            node.stop_node()
        for node in self.nodes:
            node.wait_until_stopped()

    def define_network_topology(self):
        """This function defines the network's topology"""

        self.logger.info('Defining network graph')

        graph_edges, inbound_degrees = create_directed_graph(
            num_nodes=self.num_nodes,
            num_outbound_connections=8,
            max_inbound_connections=125,
            model=self.graph_model
        )

        # We try to avoid having sink sub-graphs
        graph_edges, inbound_degrees = enforce_nodes_reconnections(
            graph_edges=graph_edges,
            inbound_degrees=inbound_degrees,
            num_reconnection_rounds=1,
            num_outbound_connections=8
        )

        # This fix the rare case where some nodes don't have inbound connections
        self.graph_edges, _ = ensure_one_inbound_connection_per_node(
            num_nodes=self.num_nodes,
            graph_edges=graph_edges,
            inbound_degrees=inbound_degrees
        )


def main():
    logging_config(
        stream=sys.stdout,
        level=INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    tf_util.MAX_NODES = 500  # has to be greater than 2n+2 where n = num_nodes
    tf_util.PortSeed.n = 314159

    # TODO: Load simulation settings from settings.py
    simulation = ForkingSimulation(
        loop=get_event_loop(),
        latency=0,
        num_proposer_nodes=20,
        num_relay_nodes=180,
        simulation_time=120,
        sample_time=1,
        graph_model='preferential_attachment',
        results_file_name='fork_simulation_results.csv'
    )
    simulation.safe_run()


if __name__ == '__main__':
    main()
