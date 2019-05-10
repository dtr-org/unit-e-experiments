#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from abc import ABC, abstractmethod
from copy import copy as shallow_copy
from math import ceil
from numpy.random import binomial  # type: ignore
from statistics import median
from typing import Optional

from blockchain import max_uint256_val
from blockchain.block import Block
from blockchain.transaction import Coin, CoinStakeTransaction
from blockchain.utils import (
    compact_target_to_bigint,
    compact_target_to_uint256,
    uint256_to_compact_target
)


class Clock(ABC):
    @abstractmethod
    def get_time(self) -> int:
        raise NotImplementedError


class CheatedClock(Clock):
    def __init__(self, time: int):
        assert time >= 0
        self.__time = time

    def advance_time(self, amount: int = 1):
        self.__time += amount

    def get_time(self) -> int:
        return self.__time


class BiasedClock(Clock):
    """
    Like Clock, but with a random (although fixed) bias drawn from a shifted
    binomial distribution. Useful to simulate lack of synchronicity.
    """
    def __init__(self, base_clock: Clock, max_bias=5, p=0.1):
        self.base_clock = base_clock
        self.bias = binomial(n=int(max_bias / p), p=p) - max_bias

    def get_time(self) -> int:
        return self.base_clock.get_time() + self.bias


class BlockChain:
    """Represents a blockchain"""

    def __init__(
            self, *,

            # Chain state
            genesis: Block,

            # World state
            clock: Clock,

            # Chain custom params
            stake_maturing_period: int = 0,
            stake_blocking_period: int = 0,
            num_blocks_for_median_timestamp: int = 11,
            max_future_block_time_seconds: int = 120,
            difficulty_adjustment_period: int = 1,
            difficulty_adjustment_window: int = 40,
            time_between_blocks: int = 16,
            block_time_mask: int = 4
    ):
        # Checking pre-conditions
        assert 0 <= stake_maturing_period <= 150
        assert 0 <= stake_blocking_period <= 150
        assert 1 <= num_blocks_for_median_timestamp <= 20
        assert 16 <= max_future_block_time_seconds <= 3600
        assert 1 <= difficulty_adjustment_period <= 8192
        assert 6 <= difficulty_adjustment_window <= 8192
        assert 4 <= time_between_blocks <= 120
        assert block_time_mask < time_between_blocks
        assert time_between_blocks % block_time_mask == 0

        # The block comes from the past, not from the future
        assert genesis.timestamp <= clock.get_time()
        # The hash is consistent with the target
        assert genesis.kernel_hash() < compact_target_to_uint256(genesis.compact_target)

        # Consensus Settings
        ########################################################################
        # How old (in blocks) a reward has to be to be staked
        self.stake_maturing_period = stake_maturing_period

        # For how long do we forbid a coin to be staked again after proposing
        # It seems that the most reasonable value is 0
        self.stake_blocking_period = stake_blocking_period

        # How many blocks are used to compute the past median timestamp
        self.num_blocks_for_median_timestamp = num_blocks_for_median_timestamp

        # How much in the future can be the new block timestamps
        self.max_future_block_time_seconds = max_future_block_time_seconds

        # Number of blocks between difficulty adjustments
        self.difficulty_adjustment_period = difficulty_adjustment_period

        # How many blocks we'll use to compute the next difficulty
        self.difficulty_adjustment_window = difficulty_adjustment_window

        # Expected average time between blocks
        self.time_between_blocks = time_between_blocks

        # Determines the allowed timestamp granularity
        self.block_time_mask = block_time_mask

        # World State
        ########################################################################
        self.clock = clock

        # Chain State
        ########################################################################
        self.blocks = [genesis]
        self.height = 0

        # Caches the target for height, stored as (height, target)
        # We init height at -1 to invalidate this first cached value.
        self.next_compact_target = (-1, b'\xff\xff\xff\xff')

        # Tracks chain work (height, acc_work), used in fork choice rule.
        self.chain_work = (0, 0)  # We consider the genesis adds no work

    def add_block(self, block: Block):
        # We don't try to validate anything, just to save time
        self.blocks.append(block)
        self.height += 1

    def median_past_timestamp(self) -> int:
        return int(round(median([
            b.timestamp for b in self.blocks[-self.num_blocks_for_median_timestamp:]
        ])))

    def get_next_compact_target(self) -> bytes:
        """
        Returns a new compact target based on how fast were generated the
        previous blocks, trying to ensure that new blocks will be generated at
        the correct pace.
        """
        if self.next_compact_target[0] == self.height:
            return self.next_compact_target[1]

        if len(self.blocks) < 2:
            return self.blocks[-1].compact_target  # We don't have enough data
        if self.height % self.difficulty_adjustment_period != 0:
            return self.blocks[-1].compact_target  # We just reuse the last one

        blocks_window = self.blocks[-self.difficulty_adjustment_window:]

        # Greater than 1: too slow; Lower than 1: too fast
        ratio = (
            blocks_window[-1].timestamp - blocks_window[0].timestamp,
            self.time_between_blocks * (len(blocks_window) - 1)
        )

        if ratio[0] <= 0:  # The noise does not allow us to adjust the difficulty
            ratio = (1, 4)

        # This is needed because we are able to update the target every time we
        # add a new block, which is a different from what's in Bitcoin.
        avg_compact_target = sum(
            compact_target_to_bigint(b.compact_target) for b in blocks_window
        ) // len(blocks_window)

        self.next_compact_target = (
            self.height,
            uint256_to_compact_target(min(
                max_uint256_val,
                (ratio[0] * avg_compact_target) // ratio[1]
            ).to_bytes(32, 'big'))
        )
        return self.next_compact_target[1]

    def get_chain_work(self) -> int:
        if self.chain_work[0] < self.height:
            self.chain_work = (
                self.height,
                self.chain_work[1] + sum(
                    self.get_block_work(h)
                    for h in range(self.chain_work[0] + 1, self.height + 1)
                )
            )
        return self.chain_work[1]

    def get_block_work(self, height: int) -> int:
        return 2**256 // (compact_target_to_bigint(
            self.blocks[height].compact_target
        ) + 1)

    def get_valid_block(
        self, *,
        coinstake_tx: CoinStakeTransaction,
        min_timestamp: Optional[int] = None,
        greedy_proposal: bool = True
    ) -> Optional['Block']:
        """
        Given a staked "coin", it tries to create a new contextually valid block.
        """

        if greedy_proposal:
            if min_timestamp is None:
                min_timestamp = self.block_time_mask * int(ceil(
                    (self.median_past_timestamp() + 1) / self.block_time_mask
                ))
            else:
                # We pass through here when we're greedily exploring timestamps,
                # and we already explored a subset of them before.
                min_timestamp = self.block_time_mask * int(ceil(
                    min_timestamp / self.block_time_mask
                ))
        else:
            # If we are not greedy, we just pass the current masked time
            min_timestamp = self.block_time_mask * (
                self.clock.get_time() // self.block_time_mask
            )
            if min_timestamp <= self.median_past_timestamp():
                return None  # This shouldn't happen, but who knows.

        # This relies on the fact that once we create a coinstake transaction,
        # we only put it into one block, so we do not have weird side effects.
        coinstake_tx.height = self.height + 1
        last_block = self.blocks[-1]

        return Block(
            prev_block_hash=last_block.block_hash(),
            prev_block_stake_modifier=last_block.stake_modifier(),
            compact_target=self.get_next_compact_target(),
            coinstake_tx=coinstake_tx,
            timestamp=min_timestamp,
            real_timestamp=self.clock.get_time()
        ).try_to_be_valid(
            max_timestamp=self.clock.get_time() + self.max_future_block_time_seconds,
            time_mask=self.block_time_mask,
            greedy_proposal=greedy_proposal
        )

    def get_truncated_copy(self, height: int) -> 'BlockChain':
        new_chain = shallow_copy(self)

        new_chain.blocks = new_chain.blocks[:height + 1]
        new_chain.height = height
        new_chain.chain_work = (0, 0)
        new_chain.next_compact_target = (-1, b'\xff\xff\xff\xff')

        return new_chain

    def is_stakeable(self, coin: Coin) -> bool:
        if coin.height == 0:
            return True  # The coins from genesis have no restrictions

        # We don't check if the coin comes from a coinbase transaction because
        # that's always the case in our simulations.
        if 0 == coin.txo.out_idx:
            # The coin is a reward
            return coin.height <= self.height - self.stake_maturing_period
        else:
            # The coin is a combination of older stakes
            return coin.height <= self.height - self.stake_blocking_period
