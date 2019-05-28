#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
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

from argparse import ArgumentParser
from asyncio import (
    AbstractEventLoop,
    sleep as asyncio_sleep,
    get_event_loop,
)
from json import dumps as json_dumps
from logging import (
    INFO,
    WARNING,
    basicConfig as loggingBasicConfig,
    getLogger
)
from math import floor
from os import environ
from os.path import (
    dirname,
    exists as path_exists,
    normpath,
    realpath,
)
from pathlib import Path
from random import sample
from shutil import rmtree
from tempfile import mkdtemp
from time import time as _time
from typing import (
    List,
    Optional,
    Set,
    Tuple
)

import test_framework.util as tf_util

from experiments.graph import (
    enforce_nodes_reconnections,
    ensure_one_inbound_connection_per_node,
    create_directed_graph,
    create_simple_dense_graph
)
from network.latencies import StaticLatencyPolicy
from network.stats import (
    CsvNetworkStatsCollector,
    NullNetworkStatsCollector
)
from network.nodes_hub import (
    NodesHub,
    NUM_INBOUND_CONNECTIONS,
    NUM_OUTBOUND_CONNECTIONS
)
from test_framework.messages import UNIT
from test_framework.regtest_mnemonics import regtest_mnemonics
from test_framework.test_node import TestNode
from test_framework.util import initialize_datadir


class ForkingSimulation:
    def __init__(
            self, *,
            loop: AbstractEventLoop,
            latency: float,
            num_proposer_nodes: int,
            num_validator_nodes: int,
            num_relay_nodes: int,
            simulation_time: float = 600,
            sample_time: float = 1,
            block_time_seconds: int = 16,
            block_stake_timestamp_interval_seconds: int = 1,
            network_stats_file_name: str,
            nodes_stats_directory: str,
            graph_model: str = 'preferential_attachment',
    ):
        if num_proposer_nodes < 0 or num_relay_nodes < 0:
            raise RuntimeError('Number of nodes must be positive')
        elif num_relay_nodes + num_proposer_nodes == 0:
            raise RuntimeError('Total number of nodes must be greater than 0')
        elif num_proposer_nodes > 100:
            raise RuntimeError('For now we only have 100 wallets with funds')

        self.logger = getLogger('ForkingSimulation')

        # Node related settings
        self.block_time_seconds = block_time_seconds
        self.block_stake_timestamp_interval_seconds = block_stake_timestamp_interval_seconds

        # Network related settings
        self.num_proposer_nodes = num_proposer_nodes
        self.num_validator_nodes = num_validator_nodes
        self.num_relay_nodes = num_relay_nodes
        self.num_nodes = num_proposer_nodes + num_validator_nodes + num_relay_nodes
        self.graph_model = graph_model
        self.graph_edges: Set[Tuple[int, int]] = set()
        self.latency = latency  # For now just a shared latency parameter.
        self.define_network_topology()

        # Simulation related settings
        self.simulation_time = simulation_time
        self.sample_time = sample_time

        # Filesystem related settings
        self.cache_dir = normpath(dirname(realpath(__file__)) + '/cache')
        self.tmp_dir = ''
        self.network_stats_file_name = network_stats_file_name
        self.nodes_stats_directory = Path(nodes_stats_directory).resolve()

        # Required to interact with the network & the nodes
        self.loop = loop
        self.nodes: List[TestNode] = []
        self.nodes_hub: Optional[NodesHub] = None
        self.proposer_node_ids: List[int] = []
        self.validator_node_ids: List[int] = []

        self.is_running = False

    def run(self) -> bool:
        self.logger.info('Starting simulation')
        self.setup_directories()
        self.setup_chain()
        self.setup_nodes()

        try:
            if self.num_validator_nodes > 0:
                self.autofinalization_workaround()
            self.start_nodes()
        except (OSError, AssertionError):
            return False  # Early shutdown

        self.nodes_hub = NodesHub(
            loop=self.loop,
            latency_policy=StaticLatencyPolicy(self.latency),
            nodes=self.nodes,
            network_stats_collector=CsvNetworkStatsCollector(
                output_file=open(file=self.network_stats_file_name, mode='wb')
            )
        )
        self.nodes_hub.sync_start_proxies()
        self.nodes_hub.sync_connect_nodes_graph(self.graph_edges)

        # Notice that the validators have already loaded their wallets
        self.logger.info('Importing wallets')
        for idx, proposer_id in enumerate(self.proposer_node_ids):
            if idx > 0:
                self.nodes[proposer_id].createwallet(f'n{proposer_id}')

            tmp_wallet = self.nodes[proposer_id].get_wallet_rpc(f'n{proposer_id}')
            tmp_wallet.importwallet(normpath(self.tmp_dir + f'/n{proposer_id}.wallet'))

        self.loop.run_until_complete(self.trigger_simulation_stop())
        return True

    def autofinalization_workaround(self):
        """
        Because of auto-finalization, we have to start with a single proposer
        and propose some blocks before we can add the rest of the nodes.
        """
        self.logger.info('Running auto-finalization workaround')

        lucky_proposer_id = self.proposer_node_ids[0]
        validators = [self.nodes[i] for i in self.validator_node_ids]

        self.start_node(lucky_proposer_id)
        self.start_nodes(validators)

        # Although we don't need to collect data during this initialization
        # phase, we'll connect the nodes through a NodesHub instance to ensure
        # that they don't discover the real ports of each other and always
        # connect through the proxies during the simulation.
        tmp_hub = NodesHub(
            loop=self.loop,
            latency_policy=StaticLatencyPolicy(0),
            nodes=self.nodes,
            network_stats_collector=NullNetworkStatsCollector()
        )
        lucky_node_ids = [lucky_proposer_id] + self.validator_node_ids
        tmp_hub.sync_start_proxies(lucky_node_ids)
        dense_graph = create_simple_dense_graph(node_ids=lucky_node_ids)
        tmp_hub.sync_connect_nodes_graph(dense_graph)

        # We have to load some money into the nodes
        lucky_proposer = self.nodes[lucky_proposer_id]
        for proposer_id in self.proposer_node_ids:
            lucky_proposer.createwallet(f'n{proposer_id}')
            tmp_wallet = lucky_proposer.get_wallet_rpc(f'n{proposer_id}')
            tmp_wallet.importmasterkey(
                regtest_mnemonics[proposer_id]['mnemonics']
            )
        for validator_id in self.validator_node_ids:
            self.nodes[validator_id].createwallet(f'n{validator_id}')
            tmp_wallet = self.nodes[validator_id].get_wallet_rpc(f'n{validator_id}')
            tmp_wallet.importmasterkey(
                regtest_mnemonics[validator_id]['mnemonics']
            )

        self.loop.run_until_complete(self.ensure_autofinalization_is_off())

        # Unloading the wallets that don't belong to the lucky proposer
        for proposer_id in self.proposer_node_ids:
            # The wallet file is created in the autofinalization_workaround method
            tmp_wallet = lucky_proposer.get_wallet_rpc(f'n{proposer_id}')
            tmp_wallet.dumpwallet(normpath(self.tmp_dir + f'/n{proposer_id}.wallet'))
            if proposer_id != lucky_proposer_id:
                lucky_proposer.unloadwallet(f'n{proposer_id}')

        tmp_hub.close()  # We close all temporary connections

        # We recover the original topology for the full network
        # self.num_nodes, self.graph_edges = tmp_num_nodes, tmp_graph_edges
        self.logger.info('Finished auto-finalization workaround')

    async def ensure_autofinalization_is_off(self):
        for validator_id in self.validator_node_ids:
            validator = self.nodes[validator_id]
            tmp_wallet = validator.get_wallet_rpc(f'n{validator_id}')
            tmp_wallet.deposit(
                tmp_wallet.getnewaddress('', 'legacy'),
                tmp_wallet.getbalance() - 1
            )

            # Because the network is blocking due to NodesHub, we have to yield
            # control here, so the deposit transactions can be properly relayed.
            await asyncio_sleep(0)

        # We have to wait at least for one epoch :( .
        await asyncio_sleep(1 + self.block_time_seconds * 50)

        lucky_proposer = self.nodes[self.proposer_node_ids[0]]
        is_autofinalization_off = False

        while not is_autofinalization_off:
            finalization_state = lucky_proposer.getfinalizationstate()
            is_autofinalization_off = (
                finalization_state is not None and
                'validators' in finalization_state and
                finalization_state['validators'] >= 1
            )
            await asyncio_sleep(1)

    def safe_run(self, close_loop=True) -> bool:
        successful_run = False
        try:
            successful_run = self.run()
        finally:
            self.logger.info('Releasing resources')
            if self.nodes_hub is not None:
                self.nodes_hub.close()
            self.stop_nodes()

            if successful_run:
                self.cleanup_directories()

            if close_loop:
                self.loop.close()
        return successful_run

    async def trigger_simulation_stop(self):
        self.logger.info(
            f'Started simulation count-down: {self.simulation_time}s'
        )
        await asyncio_sleep(self.simulation_time)
        self.is_running = False
        await asyncio_sleep(4 * self.sample_time)
        self.logger.info('Ending simulation')

    def setup_directories(self):
        if self.tmp_dir != '':
            return

        self.logger.info('Preparing temporary directories')
        self.tmp_dir = mkdtemp(prefix='simulation')
        self.logger.info(f'Nodes logs are in {self.tmp_dir}')

    def cleanup_directories(self):
        if self.tmp_dir != '' and path_exists(self.tmp_dir):
            self.logger.info('Cleaning temporary directories')
            rmtree(self.tmp_dir)
        # TODO: Remove wallet.* files too

    def setup_chain(self):
        self.logger.info('Preparing "empty" chain')
        for i in range(self.num_nodes):
            initialize_datadir(self.tmp_dir, i)

    def setup_nodes(self):
        if len(self.nodes) > 0:
            self.logger.info('Skipping nodes setup')
            return

        self.logger.info('Creating node wrappers')

        all_node_ids = set(range(self.num_nodes))
        self.proposer_node_ids = sample(
            all_node_ids, self.num_proposer_nodes
        )
        self.validator_node_ids = sample(
            all_node_ids.difference(self.proposer_node_ids),
            self.num_validator_nodes
        )

        # Some values are copied from test_framework.util.initialize_datadir, so
        # they are redundant, but it's easier to see what's going on by having
        # all of them together.
        node_args = [
            '-regtest=1',

            '-connect=0',
            '-listen=1',
            '-listenonion=0',
            '-server',

            '-whitelist=127.0.0.1',

            '-debug',
            '-logtimemicros',
            '-debugexclude=libevent',
            '-debugexclude=leveldb',
            '-mocktime=0',

            f'-stakesplitthreshold={50 * UNIT}',
            f'-stakecombinemaximum={50 * UNIT}',
            f'''-customchainparams={json_dumps({
                "block_time_seconds": self.block_time_seconds,
                "block_stake_timestamp_interval_seconds": self.block_stake_timestamp_interval_seconds,
                "genesis_block": {
                    "time": floor(_time()) - 1,
                    "p2wpkh_funds": [
                        {"amount": 10000 * UNIT, "pub_key_hash": mnemonic["address"]}
                        for mnemonic in regtest_mnemonics
                    ]
                }
            }, separators=(",",":"))}'''
        ]
        relay_args = ['-proposing=0'] + node_args
        proposer_args = ['-proposing=1'] + node_args
        validator_args = ['-proposing=0', '-validating=1'] + node_args

        if not self.nodes_stats_directory.exists():
            self.nodes_stats_directory.mkdir()

        def get_node_args(node_id: int) -> List[str]:
            if node_id in self.proposer_node_ids:
                _node_args = proposer_args
            elif node_id in self.validator_node_ids:
                _node_args = validator_args
            else:
                _node_args = relay_args
            return [
                f'-bind=127.0.0.1:{NodesHub.get_p2p_node_port(node_id)}',
                f'-rpcbind=127.0.0.1:{NodesHub.get_rpc_node_port(node_id)}',
                f'''-stats-log-output-file={
                    self.nodes_stats_directory.joinpath(f"stats_{node_id}.csv")
                }''',
                f'-uacomment=simpatch{node_id}'
            ] + _node_args

        self.nodes = [
            TestNode(
                i=i,
                datadir=f'{self.tmp_dir}/node{i}',
                extra_args=get_node_args(i),
                rpchost=None,
                timewait=60,
                unit_e=environ['UNIT_E'],
                unit_e_cli=environ['UNIT_E_CLI'],
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

    def start_nodes(self, nodes: Optional[List[TestNode]] = None):
        self.logger.info('Starting nodes')

        if nodes is None:
            nodes = self.nodes

        for node_id, node in enumerate(nodes):
            try:
                if not node.running:
                    node.start()
            except OSError as e:
                self.logger.critical(f'Node {node_id} failed to start', e)
                raise
        for node_id, node in enumerate(nodes):
            try:
                node.wait_for_rpc_connection()
            except AssertionError as e:
                self.logger.critical(
                    f'Impossible to establish RPC connection to node {node_id}',
                    e
                )
                raise

        self.logger.info('Started nodes')

    def stop_nodes(self):
        self.logger.info('Stopping nodes')
        for node in self.nodes:
            try:
                node.stop_node()
            except AssertionError:
                continue
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

    parser = ArgumentParser(description='Forking simulation')
    parser.add_argument(
        '-n', '--network-stats-file',
        help='Where to output network stats',
        default='network_stats.csv'
    )
    parser.add_argument(
        '-d', '--node-stats-directory',
        help='Where to output the nodes\' stats',
        default='./nodes_stats/'
    )
    cmd_args = vars(parser.parse_args())

    simulation = ForkingSimulation(
        loop=get_event_loop(),
        latency=0,
        num_proposer_nodes=45,
        num_validator_nodes=5,
        num_relay_nodes=0,
        simulation_time=120,
        sample_time=1,
        graph_model='preferential_attachment',
        block_time_seconds=16,
        block_stake_timestamp_interval_seconds=1,
        network_stats_file_name=cmd_args['network_stats_file'],
        nodes_stats_directory=cmd_args['node_stats_directory']
    )

    if not simulation.safe_run():
        exit(1)


if __name__ == '__main__':
    main()
