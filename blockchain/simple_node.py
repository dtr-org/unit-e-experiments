#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from bisect import insort_left
from typing import Collection, List, Optional, Set, Tuple

from blockchain.block import Block
from blockchain.blockchain import BlockChain
from blockchain.transaction import Coin, CoinStakeTransaction
from network.latencies import LatencyPolicy


class SimpleNode:
    """
    Represents a node able to relay and propose
    """
    def __init__(
        self,
        node_id: int,
        latency_policy: LatencyPolicy,
        chain: BlockChain,
        initial_coins: Set[Coin],
        is_proposer: bool = False,
        greedy_proposal: bool = True,
        max_num_tips: int = 10,
        max_outbound_peers: int = 8,
        processing_time: float = 0.0
    ):
        assert max_outbound_peers > 0

        # Although in reality nodes do not have a sense of "global identity",
        # this is very convenient to us.
        self.node_id = node_id

        # Global state
        ########################################################################
        self.clock = chain.clock  # Faster to access this reference

        # Global settings
        ########################################################################
        self.latency_policy = latency_policy

        # Node settings
        ########################################################################
        self.is_proposer = is_proposer
        self.processing_time = processing_time
        self.max_outbound_peers = max_outbound_peers
        self.max_num_tips = max_num_tips

        # It greedily explores the timestamps at the time of proposing, or not.
        self.greedy_proposal = greedy_proposal

        # Node state - Network
        ########################################################################

        # It represents messages arriving to the node in the form of a tuples
        # list. The tuples' structure is: (timestamp, block_header, source_id)
        # If their timestamps are bigger than the clock's time,
        # then we consider that they haven't arrived yet, and are just "flying".
        self.incoming_messages: List[Tuple[float, Block, int]] = []

        # We only keep track of outbound peers because they are the only ones to
        # who we'll send messages.
        self.outbound_peers: List[SimpleNode] = []

        # Node state - Blockchain
        ########################################################################
        self.main_chain = chain
        self.alternative_chains: List[BlockChain] = []

        # Coins used by the node when it starts
        self.initial_coins = initial_coins

        # Current set of coins
        self.coins_cache: Set[Coin] = initial_coins.copy()

        self.orphan_blocks: Set[Block] = set()

    def add_outbound_peer(self, peer: 'SimpleNode'):
        assert peer not in self.outbound_peers
        assert len(self.outbound_peers) < self.max_outbound_peers
        self.outbound_peers.append(peer)

    def receive_message(
        self,
        arrival_time: float,
        msg: Block,
        source_id: int
    ):
        # The incoming messages are processed by arrival time (processing time
        # is constant)
        insort_left(
            self.incoming_messages,
            (arrival_time + self.processing_time, msg, source_id)
        )

    def relay_message(
        self,
        msg: Block,
        send_time: Optional[float] = None,
        discard_peers: Collection[int] = ()
    ):
        if send_time is None:
            send_time = self.clock.get_time()

        for peer in self.outbound_peers:
            if peer.node_id in discard_peers:
                continue
            peer.receive_message(
                send_time + self.latency_policy.get_delay(
                    self.node_id, peer.node_id
                ),
                msg,
                self.node_id
            )

    def process_messages(self) -> int:
        """
        It consumes messages from the incoming queue, adding the new blocks to
        the chain when convenient, and also relaying the messages again if they
        provided new information.

        The function returns the number of relayed messages. This is useful to
        know if we should process messages again in other nodes during the same
        'clock tick'.
        """
        num_relayed_messages = 0

        while (
            len(self.incoming_messages) > 0 and
            self.incoming_messages[0][0] <= self.clock.get_time()
        ):
            msg_time, block, source_id = self.incoming_messages.pop(0)

            if not self.process_block(block):
                continue

            # We try to check if we can 'un-orphan' some block...
            self.process_orphans()
            self.find_best_tip()

            self.relay_message(
                msg=block,
                # Notice that msg_time also incorporates the processing time,
                # see `relay_message` & `receive_message` for better insights.
                send_time=msg_time,
                discard_peers=(source_id,)
            )
            num_relayed_messages += 1

        return num_relayed_messages

    def process_orphans(self):
        try_to_save_orphans = True
        while try_to_save_orphans:
            try_to_save_orphans = False
            recovered_orphans = set()
            for orphan in self.orphan_blocks:
                added = self.process_block(orphan)
                if added:
                    recovered_orphans.add(orphan)
                try_to_save_orphans = added or try_to_save_orphans
            self.orphan_blocks.difference_update(recovered_orphans)

    def process_block(self, block: Block) -> bool:
        """
        Tries to add the block to the main blockchain, or at least to one of the
        alternative chains that the node keeps in memory.

        Notice that we don't perform any re-org here because it requires to
        re-compute the coins cache. This is done just at proposing time.

        Returns false when is not possible to save the block.
        """
        # We want to traverse the chains in "importance" order
        self.alternative_chains = sorted(
            self.alternative_chains,
            key=lambda x: x.get_chain_work(),
            reverse=True
        )
        all_chains = [self.main_chain] + self.alternative_chains

        for chain in all_chains:
            c_blocks = chain.blocks
            if block.prev_block_hash == c_blocks[-1].block_hash():
                chain.add_block(block)
                return True
            if block.block_hash() in [b.block_hash() for b in c_blocks]:
                return False  # We already know the block

        # This has to be in a separated loop to ensure that we detect repeated
        # blocks.
        for chain in all_chains:
            c_blocks = chain.blocks
            if (
                len(c_blocks) > block.coinstake_tx.height and
                c_blocks[block.coinstake_tx.height].prev_block_hash == block.prev_block_hash
            ):
                # Our block shares parent with an existent block
                new_chain = chain.get_truncated_copy(block.coinstake_tx.height - 1)
                new_chain.add_block(block)
                self.alternative_chains.append(new_chain)
                return True

        self.orphan_blocks.add(block)
        return False

    def try_to_propose(self) -> bool:
        """
        If the flag `is_proposer` is set, tries to propose a new block on top of
        the tip.
        """
        if not self.is_proposer:
            return False

        coinstake_txns = (
            CoinStakeTransaction(
                # We just put the coin first, the rest doesn't matter,
                # by default we want to combine all of them.
                vin=[coin] + sorted(self.coins_cache.difference([coin]))
            )
            for coin in sorted(self.coins_cache)
            if self.main_chain.is_stakeable(coin)
        )

        proposed = False
        for transaction in coinstake_txns:
            block = self.main_chain.get_valid_block(
                coinstake_tx=transaction,
                greedy_proposal=self.greedy_proposal
            )
            if block is not None:
                self.main_chain.add_block(block)
                self.relay_message(msg=block)

                # We have to update the coins cache
                self.coins_cache.difference_update(transaction.vin)
                self.coins_cache.update(transaction.get_all_coins())

                proposed = True
                break

        return proposed

    def find_best_tip(self):
        all_chains = sorted(
            [self.main_chain] + self.alternative_chains,
            key=lambda x: x.get_chain_work(),
            reverse=True
        )[:self.max_num_tips]
        if self.main_chain is not all_chains[0]:
            self.apply_reorganization(all_chains)

    def apply_reorganization(self, all_chains: List[BlockChain]):
        self.main_chain, self.alternative_chains = all_chains[0], all_chains[1:]
        self.coins_cache = self.initial_coins.copy()

        # Now we'll traverse the whole chain history to reconstruct our cache.
        # TODO: Notice that this could be optimized to avoid performing the full
        #       traversal...
        for block in self.main_chain.blocks:
            if 0 == len(self.coins_cache.intersection(block.coinstake_tx.vin)):
                continue
            self.coins_cache.difference_update(block.coinstake_tx.vin)
            self.coins_cache.update(block.coinstake_tx.get_all_coins())
