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
    sleep as asyncio_sleep,
    get_event_loop,
)
from collections import defaultdict
from io import BytesIO
from logging import (
    INFO,
    WARNING,
    basicConfig as loggingBasicConfig,
    getLogger
)
from os.path import (
    dirname,
    normpath,
    realpath,
    exists as path_exists
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
from experiments.utils.nodes_hub import (
    NodesHub,
    NUM_INBOUND_CONNECTIONS,
    NUM_OUTBOUND_CONNECTIONS
)
from experiments.utils.latencies import StaticLatencyPolicy
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
            sample_size: int = 10,
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
        self.sample_size = sample_size

        self.start_time = 0

        self.cache_dir = normpath(dirname(realpath(__file__)) + '/cache')
        self.tmp_dir = ''

        self.results_file: Optional[BytesIO] = None
        self.results_file_name = results_file_name

        self.define_network_topology()
        self.is_running = False

    def run(self):
        self.logger.info('Starting simulation')
        self.setup_directories()

        self.setup_chain()
        self.setup_nodes()
        self.start_nodes()

        self.nodes_hub = NodesHub(
            loop=self.loop,
            latency_policy=StaticLatencyPolicy(self.latency),
            nodes=self.nodes
        )
        self.nodes_hub.sync_start_proxies()
        self.nodes_hub.sync_connect_nodes_graph(self.graph_edges)

        # Loading wallets... only for proposers (which are picked randomly)
        for idx, proposer_id in enumerate(self.proposer_node_ids):
            self.nodes[proposer_id].importmasterkey(
                regtest_mnemonics[idx]['mnemonics']
            )

        # Opening results file
        self.results_file = open(file=self.results_file_name, mode='wb')

        self.start_time = time()
        self.loop.create_task(self.sample_forever())
        self.loop.run_until_complete(self.trigger_simulation_stop())

    def safe_run(self):
        try:
            self.run()
        finally:
            self.logger.info('Releasing resources')

            if not self.results_file.closed:
                self.results_file.close()
            self.nodes_hub.close()
            self.stop_nodes()
            self.cleanup_directories()
            self.loop.close()

    async def trigger_simulation_stop(self):
        await asyncio_sleep(self.simulation_time)
        self.is_running = False
        await asyncio_sleep(4 * self.sample_time)

    async def sample_forever(self):
        self.logger.info('Starting sampling process')

        self.is_running = True
        while self.is_running:
            await asyncio_sleep(self.sample_time)
            self.sample()

        self.logger.info('Stopping sampling process')

    def sample(self):
        sample_time = time()
        time_delta = sample_time - self.start_time

        for node_id, node in sample(list(enumerate(self.nodes)), self.sample_size):
            tip_stats = defaultdict(int)
            for tip in node.getchaintips():
                tip_stats[tip['status']] += 1

            # There's redundant data because it allows us to keep all the data
            # in one single file, without having to perform "join" operations of
            # any type.
            self.results_file.write((
                f'{time_delta},{node_id},{self.latency},'
                f'{tip_stats["active"]},{tip_stats["valid-fork"]},'
                f'{tip_stats["valid-headers"]},{tip_stats["headers-only"]}\n'
            ).encode())

    def setup_directories(self):
        self.logger.info('Preparing temporary directories')
        self.tmp_dir = mkdtemp(prefix='simulation')
        self.logger.info(f'Nodes logs are in {self.tmp_dir}')

    def cleanup_directories(self):
        if self.tmp_dir != '' and path_exists(self.tmp_dir):
            self.logger.info('Cleaning temporary directories')
            rmtree(self.tmp_dir)

    def setup_chain(self):
        self.logger.info('Preparing "empty" chain')
        for i in range(self.num_nodes):
            initialize_datadir(self.tmp_dir, i)

    def setup_nodes(self):
        self.logger.info('Creating node wrappers')

        self.proposer_node_ids = sample(
            range(self.num_nodes), self.num_proposer_nodes
        )

        relay_args = ['-connect=0', '-listen=1', '-proposing=0']
        proposer_args = ['-connect=0', '-listen=1', '-proposing=1']

        self.nodes = [
            TestNode(
                i=i,
                dirname=self.tmp_dir,
                extra_args=(
                    proposer_args if i in self.proposer_node_ids
                    else relay_args
                ),
                rpchost=None,
                timewait=None,
                binary=None,
                stderr=None,
                mocktime=0,
                coverage_dir=None,
                use_cli=False
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
            num_outbound_connections=NUM_OUTBOUND_CONNECTIONS,
            max_inbound_connections=NUM_INBOUND_CONNECTIONS,
            model=self.graph_model
        )

        # We try to avoid having sink sub-graphs
        graph_edges, inbound_degrees = enforce_nodes_reconnections(
            graph_edges=graph_edges,
            inbound_degrees=inbound_degrees,
            num_reconnection_rounds=1,
        )

        # This fix the rare case where some nodes don't have inbound connections
        self.graph_edges, _ = ensure_one_inbound_connection_per_node(
            num_nodes=self.num_nodes,
            graph_edges=graph_edges,
            inbound_degrees=inbound_degrees,
        )


def main():
    loggingBasicConfig(
        stream=sys.stdout,
        level=INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    getLogger('asyncio').setLevel(WARNING)

    tf_util.MAX_NODES = 500  # has to be greater than 2n+2 where n = num_nodes
    tf_util.PortSeed.n = 314159

    # TODO: Load simulation settings from settings.py
    simulation = ForkingSimulation(
        loop=get_event_loop(),
        latency=0,
        num_proposer_nodes=5,
        num_relay_nodes=45,
        simulation_time=120,
        sample_time=1,
        sample_size=10,
        graph_model='preferential_attachment',
        results_file_name='fork_simulation_results.csv'
    )
    simulation.safe_run()


if __name__ == '__main__':
    main()
