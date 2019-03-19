#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from collections import defaultdict
from logging import getLogger
from random import sample
from typing import List, Set, Tuple

from blockchain.block import Block
from blockchain.blockchain import BlockChain, CheatedClock
from blockchain.simple_node import SimpleNode
from experiments.graph import (
    create_directed_graph,
    enforce_nodes_reconnections,
    ensure_one_inbound_connection_per_node
)
from network.latencies import ExponentiallyDistributedLatencyPolicy


class SimNet:
    def __init__(
        self, *,
        simulation_time: int,
        num_proposer_nodes: int,
        num_relay_nodes: int,
        num_inbound_connections: int = 125,
        num_outbound_connections: int = 8,
        graph_model: str = 'preferential_attachment',
        num_coins_per_proposer: int = 3,
        coins_amount: int = 1000,
        num_greedy_proposers: int = 0,
        time_between_blocks: int = 16,
        block_time_mask: int = 4,
        difficulty_adjustment_window: int = 2048,
        difficulty_adjustment_period: int = 1,
        num_blocks_for_median_timestamp: int = 13,
        max_future_block_time_seconds: int = 600,
        latency: float = 0.1,
        processing_time: float = 0.001,
    ):
        self.logger = getLogger('SimNet')

        # Simulation settings
        self.proposer_node_ids: List[int] = []
        self.simulation_time = simulation_time

        # Network topology parameters
        self.num_proposer_nodes = num_proposer_nodes
        self.num_relay_nodes = num_relay_nodes
        self.num_nodes = num_proposer_nodes + num_relay_nodes
        self.num_inbound_connections = num_inbound_connections
        self.num_outbound_connections = num_outbound_connections
        self.graph_model = graph_model

        # Network topology construction
        self.graph_edges: Set[Tuple[int, int]] = set()
        self.define_network_topology()

        # (Initial) Economical parameters
        assert 0 <= num_greedy_proposers <= num_proposer_nodes
        self.num_coins_per_proposer = num_coins_per_proposer
        self.coins_amount = coins_amount
        self.num_greedy_proposers = num_greedy_proposers

        # Consensus parameters
        self.time_between_blocks = time_between_blocks
        self.block_time_mask = block_time_mask
        self.difficulty_adjustment_window = difficulty_adjustment_window
        self.difficulty_adjustment_period = difficulty_adjustment_period
        self.num_blocks_for_median_timestamp = num_blocks_for_median_timestamp
        self.max_future_block_time_seconds = max_future_block_time_seconds

        # "Hardware" parameters
        self.latency_policy = ExponentiallyDistributedLatencyPolicy(
            avg_delay=latency
        )
        self.processing_time = processing_time  # Blocks processing time

        # Create node instances
        self.clock = CheatedClock(time=60)
        self.nodes: List[SimpleNode] = []
        self.setup_nodes()
        self.setup_network()

    def define_network_topology(self):
        """This function defines the network's topology"""

        self.logger.info('Defining network graph')

        graph_edges, inbound_degrees = create_directed_graph(
            num_nodes=self.num_nodes,
            max_inbound_connections=self.num_inbound_connections,
            num_outbound_connections=self.num_outbound_connections,
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

    def setup_nodes(self):
        """Creates node instances using the previously specified settings."""

        self.logger.info('Creating node instances')

        genesis_block = Block.genesis(
            timestamp=60,
            compact_target=b'\xff\xff\xff\xff',
            vout=[self.coins_amount] * (
                self.num_coins_per_proposer * self.num_proposer_nodes
            )
        ).fit_target()

        self.proposer_node_ids = sample(
            range(self.num_nodes), self.num_proposer_nodes
        )

        # Assigning coins to proposers
        all_coins = genesis_block.coinstake_tx.get_all_coins()
        coins_per_proposer = defaultdict(set)
        coins_per_proposer.update({
            node_id: set(all_coins[
                self.num_coins_per_proposer * i:
                self.num_coins_per_proposer * (i + 1)
            ])
            for i, node_id in enumerate(self.proposer_node_ids)
        })
        # TODO: Allow arbitrary coins distributions

        # Assigning greed to some proposers
        greedy_node_ids = sample(
            self.proposer_node_ids, self.num_greedy_proposers
        )

        self.nodes = [
            SimpleNode(
                node_id=node_id,
                latency_policy=self.latency_policy,
                chain=BlockChain(
                    genesis=genesis_block,
                    clock=self.clock,
                    time_between_blocks=self.time_between_blocks,
                    block_time_mask=self.block_time_mask,
                    difficulty_adjustment_window=self.difficulty_adjustment_window,
                    difficulty_adjustment_period=self.difficulty_adjustment_period,
                    num_blocks_for_median_timestamp=self.num_blocks_for_median_timestamp,
                    max_future_block_time_seconds=self.max_future_block_time_seconds
                ),
                initial_coins=coins_per_proposer[node_id],
                is_proposer=node_id in self.proposer_node_ids,
                greedy_proposal=node_id in greedy_node_ids,
                max_num_tips=self.num_proposer_nodes + 1,
                max_outbound_peers=self.num_outbound_connections,
                processing_time=self.processing_time
            )
            for node_id in range(self.num_nodes)
        ]

    def setup_network(self):
        """Connects nodes using the previously defined network topology."""

        for src_id, dst_id in self.graph_edges:
            self.nodes[src_id].add_outbound_peer(self.nodes[dst_id])

    def run(self):
        for _ in range(60, 60 + self.simulation_time):
            self.clock.advance_time(1)

            # First we process all what we have "flying" around
            processed_messages = 1
            while processed_messages > 0:
                processed_messages = 0
                for node in self.nodes:
                    processed_messages += node.process_messages()

            # Then all the nodes try to propose
            for node in self.nodes:
                node.try_to_propose()
