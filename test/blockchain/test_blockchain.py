#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


import pytest

from blockchain.block import Block
from blockchain.blockchain import BlockChain, Clock
from blockchain.transaction import CoinStakeTransaction


def test_clock():
    with pytest.raises(expected_exception=AssertionError):
        Clock(-1)
    clock = Clock(16)
    assert clock.time == 16

    clock.advance_time()
    assert clock.time == 17


def test_blockchain_get_chain_work():
    # When we have more proposers staking, the difficulty increases.
    # Notice that in this test, the proposers are "greedy", they try to propose
    # exploring the whole set of valid timestamps.

    genesis_block = Block.genesis(
        timestamp=256,
        compact_target=b'\xff\xff\xff\xff'
    )

    # Creating a "strong" chain (all coins are staked)
    blockchain_a = BlockChain(
        genesis=genesis_block,
        clock=Clock(257),
        max_future_block_time_seconds=176,
        time_between_blocks=16,
        block_time_mask=1,
        difficulty_adjustment_period=4,
        difficulty_adjustment_window=40
    )

    coins = set(genesis_block.coinstake_tx.get_all_coins())
    for _ in range(128):
        min_timestamp = None  # We pass this to avoid repeating work
        candidates = []
        while 0 == len(candidates):
            candidates = sorted(
                [
                    b for b in (
                        blockchain_a.get_valid_block(
                            coinstake_tx=CoinStakeTransaction(vin=[coin]),
                            min_timestamp=min_timestamp,
                            greedy_proposal=True
                        ) for coin in coins
                    )
                    if b is not None
                ],
                key=lambda bb: bb.coinstake_tx.vin[0]
            )

            blockchain_a.clock.advance_time(1)
            min_timestamp = blockchain_a.clock.time + blockchain_a.max_future_block_time_seconds - 1

        # Local variables for convenience
        block = candidates[0]
        tx = block.coinstake_tx

        blockchain_a.add_block(block)  # Extending the blockchain
        coins.difference_update(tx.vin)  # Discarding used coins
        coins.update(tx.get_all_coins())  # Adding new coins

    # Creating a "weak" chain (just staking half of the coins)
    blockchain_b = BlockChain(
        genesis=genesis_block,
        clock=Clock(257),
        max_future_block_time_seconds=176,
        time_between_blocks=16,
        block_time_mask=1,
        difficulty_adjustment_period=1,
        difficulty_adjustment_window=40
    )
    coins = set(genesis_block.coinstake_tx.get_all_coins())
    for _ in range(128):
        stakeable_coins = sorted(
            list(coins),
            key=lambda c: c.height  # Older coins first
        )[:max(1, len(coins) // 16)]

        min_timestamp = None  # We pass this to avoid repeating work
        candidates = []
        while 0 == len(candidates):
            candidates = sorted(
                [
                    b for b in (
                        blockchain_b.get_valid_block(
                            coinstake_tx=CoinStakeTransaction(vin=[coin]),
                            min_timestamp=min_timestamp,
                            greedy_proposal=True
                        ) for coin in stakeable_coins
                    )
                    if b is not None
                ],
                key=lambda bb: bb.coinstake_tx.vin[0]
            )

            blockchain_b.clock.advance_time(1)
            min_timestamp = blockchain_b.clock.time + blockchain_b.max_future_block_time_seconds - 1

        # Local variables for convenience
        block = candidates[0]
        tx = block.coinstake_tx

        blockchain_b.add_block(block)  # Extending the blockchain
        coins.difference_update(tx.vin)  # Discarding used coins
        coins.update(tx.get_all_coins())  # Adding new coins

    # Given the low amount of blocks, we had to use a substantially lower amount
    # of coins (16 times less coins) to ensure that this assertions pass always.
    assert blockchain_a.get_next_compact_target() < blockchain_b.get_next_compact_target()
    assert blockchain_a.get_chain_work() > blockchain_b.get_chain_work()
