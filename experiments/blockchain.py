#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from hashlib import sha256
from math import ceil
from statistics import median
from struct import pack
from typing import Optional


max_uint32_val = 2**32 - 1
max_uint256_val = 2**256 - 1


def compact_target_to_uint256(compact_target: bytes) -> bytes:
    """
    Transforms a compact target into an equivalent 256bits hash.
    """
    assert len(compact_target) == 4

    # The bigger is the compact target, the bigger is the target
    num_zero_bits = 255 - compact_target[0]
    bits_shift = num_zero_bits % 8
    neg_bits_shift = 8 - bits_shift

    partial_result = b'\x00' * (num_zero_bits // 8)

    if len(partial_result) < 32:
        next_byte = (128 >> bits_shift)  # Implicit bit
        bits_shift = (bits_shift + 1) % 8
        neg_bits_shift = 8 - bits_shift
        if bits_shift > 0:
            next_byte += (compact_target[1] >> bits_shift)
        partial_result += pack('B', next_byte)

    if bits_shift == 0:
        partial_result += compact_target[1:2]

    if len(partial_result) < 32:
        partial_result += pack('B', (
            ((compact_target[1] << neg_bits_shift) & 0xff) +
            (compact_target[2] >> bits_shift)
        ))
    if len(partial_result) < 32:
        partial_result += pack('B', (
            ((compact_target[2] << neg_bits_shift) & 0xff) +
            (compact_target[3] >> bits_shift)
        ))
    if len(partial_result) < 32:
        partial_result += pack('B', (
            ((compact_target[3] << neg_bits_shift) & 0xff) +
            (0xff >> bits_shift)
        ))

    return partial_result + b'\xff' * (32 - len(partial_result))


def compact_target_to_bigint(compact_target: bytes) -> int:
    return int.from_bytes(compact_target_to_uint256(compact_target), 'big')


def uint256_to_compact_target(hash_target: bytes) -> bytes:
    """
    Transforms a 256bits hash into an equivalent compact target
    """
    assert len(hash_target) == 32

    num_leading_zeros = 0
    for bit_index in range(255):
        byte = hash_target[bit_index // 8]
        bit = bool(byte & (2 ** (7 - bit_index % 8)))
        if bit:
            break
        num_leading_zeros += 1

    bits_shift = (num_leading_zeros + 1) % 8  # We have an implicit 1
    neg_bits_shift = 8 - bits_shift
    byte_index = (num_leading_zeros + 1) // 8

    compact_target = pack('B', 255 - num_leading_zeros)

    if bits_shift == 0:
        compact_target += hash_target[byte_index:byte_index + 3]
        compact_target += b'\xff' * (4 - len(compact_target))
        return compact_target

    for _ in range(3):
        if byte_index <= 31:
            next_byte = (hash_target[byte_index] << bits_shift) & 0xff
            if byte_index + 1 <= 31:
                next_byte += (hash_target[byte_index + 1] >> neg_bits_shift)
            else:
                next_byte += (0xff >> bits_shift)
            compact_target += pack('B', next_byte)
        else:
            compact_target += b'\xff'
        byte_index += 1

    return compact_target


class BlockHeader:
    """
    This class does not pretend to faithfully mimic the real headers' structure,
    but just enough to be able to reproduce the proposal mechanism.

    Our "merkle root" will be just a double hash of the block where the "staked
    coin" was created, we won't have transactions, and all "coins" will have the
    same denomination.

    "Ownership" over coins won't be based on secure cryptographic primitives,
    but just on "good behavior", just because it's simpler.
    """

    def __init__(
            self, *,
            hash_prev_block: bytes,
            stake_hash: bytes,
            timestamp: int,
            compact_target: bytes,
            real_timestamp: Optional[int] = None
    ):
        assert 0 <= timestamp <= max_uint32_val
        assert 4 == len(compact_target)
        assert len(hash_prev_block) == 32
        assert len(stake_hash) == 32

        self.hash_prev_block = hash_prev_block
        self.stake_hash = stake_hash
        self.timestamp = timestamp

        if real_timestamp is None:
            self.real_timestamp = timestamp
        else:
            self.real_timestamp = real_timestamp

        # Compact representation of the target hash.
        # Block's hash has to be lower than it's equivalent hash.
        self.compact_target = compact_target

        self._kernel_hash: Optional[bytes] = None
        self._coin_hash: Optional[bytes] = None

    @staticmethod
    def get_valid_block(
            *,
            min_timestamp: int,
            max_timestamp: int,
            time_step: int,
            hash_prev_block: bytes,
            stake_hash: bytes,
            compact_target: bytes,
            real_timestamp: Optional[int] = None
    ) -> Optional['BlockHeader']:
        """
        It returns a "valid" block, in the sense that its hash meets its target,
        but it does not provide any guarantee on its contextual validity.
        """
        assert min_timestamp < max_timestamp
        assert min_timestamp % time_step == 0
        assert max_timestamp % time_step == 0

        block = BlockHeader(
            hash_prev_block=hash_prev_block,
            stake_hash=stake_hash,
            timestamp=min_timestamp,
            compact_target=compact_target,
            real_timestamp=real_timestamp
        )

        hash_target = compact_target_to_uint256(block.compact_target)

        tries = 0
        while block.kernel_hash() > hash_target and block.timestamp < max_timestamp:
            tries += 1
            block.increase_timestamp(time_step)

        if block.kernel_hash() > hash_target:
            return None  # It was impossible to find a good enough block

        return block

    def kernel_hash(self) -> bytes:
        """
        The kernel hash is used to determine if we can propose or not.
        """
        if self._kernel_hash is None:
            self._kernel_hash = sha256(
                self.hash_prev_block +
                self.stake_hash +
                pack('>I', self.timestamp) +
                self.compact_target
            ).digest()
        return self._kernel_hash

    def coin_hash(self) -> bytes:
        if self._coin_hash is None:
            self._coin_hash = sha256(self.kernel_hash()).digest()
        return self._coin_hash

    def increase_timestamp(self, delta: int):
        assert delta > 0
        self.timestamp += delta
        self._kernel_hash = None  # We invalidate the previous hash
        self._coin_hash = None  # Same for the coin


class Clock:
    def __init__(self, first_time: int):
        assert first_time >= 0
        self.time = first_time

    def advance_time(self, amount: int = 1):
        self.time += amount


class BlockChain:
    """Represents a blockchain"""

    def __init__(
            self, *,

            # Chain state
            genesis: BlockHeader,

            # World state
            clock: Optional[Clock] = None,

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
        assert 1 <= difficulty_adjustment_period <= 256
        assert 6 <= difficulty_adjustment_window <= 256
        assert 4 <= time_between_blocks <= 120
        assert block_time_mask < time_between_blocks
        assert time_between_blocks % block_time_mask == 0

        if clock is None:
            clock = Clock(0)

        # The block comes from the past, not from the future
        assert genesis.timestamp <= clock.time
        # The hash is consistent with the target
        assert genesis.kernel_hash() < compact_target_to_uint256(genesis.compact_target)

        # Consensus Settings
        ########################################################################
        # How old (in blocks) has to be a coin to be staked
        self.stake_maturing_period = stake_maturing_period

        # For how many blocks do we forbid a coin to be used as stake
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
        self.height = 1

        # Caches the next target for height + 1, stored as (height, target)
        self.next_compact_target = (0, b'\xff\xff\xff\xff')

        # Tracks chain work (height, acc_work), used in fork choice rule.
        self.chain_work = (0, 0)

    def add_block(self, block: BlockHeader, check_time_locks: bool = True):
        self.validate_block(block, check_time_locks=check_time_locks)
        self.add_block_fast(block)

    def add_block_fast(self, block: BlockHeader):
        self.blocks.append(block)
        self.height += 1

    def validate_block(self, block: BlockHeader, check_time_locks: bool = True):
        # WARNING: Notice that we don't check that the block hash is properly
        #          computed, this is because we don't have to deal with
        #          malicious nodes in our simulations.

        # The new block depends on last one
        assert block.hash_prev_block == self.blocks[-1].kernel_hash()

        if check_time_locks:
            stake_maturing_period = self.stake_maturing_period
            stake_blocking_period = self.stake_blocking_period
        else:
            stake_maturing_period = 0
            stake_blocking_period = 0

        # An existent (& mature) coin was used as stake
        assert block.stake_hash in (
            b.coin_hash() for b in self.blocks[:len(self.blocks) - stake_maturing_period]
        )
        # The stake is not blocked for being used recently
        if self.stake_blocking_period > 0:
            assert block.stake_hash not in (
                b.stake_hash for b in self.blocks[-stake_blocking_period:]
            )

        # The block times are not "too crazy"
        assert block.timestamp > self.median_past_timestamp()
        assert block.timestamp <= self.clock.time + self.max_future_block_time_seconds

        # The "difficulty" is properly computed
        assert block.compact_target == self.get_next_compact_target()
        assert block.kernel_hash() < compact_target_to_uint256(block.compact_target)

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

        if ratio[0] <= 0:  # The noisy don't allow us to adjust the difficulty
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
        for h in range(self.chain_work[0], self.height):  # h = block_height - 1
            self.chain_work = (
                h + 1,
                self.chain_work[1] + self.get_block_work(h)
            )
        return self.chain_work[1]

    def get_block_work(self, block_index: int) -> int:
        return 2**256 // (compact_target_to_bigint(
            self.blocks[block_index].compact_target
        ) + 1)

    def get_valid_block(
            self,
            hash_merkle_root: bytes,
            min_timestamp: Optional[int] = None
    ) -> Optional['BlockHeader']:
        """
        Given a staked "coin", it tries to create a new contextually valid block.
        """

        if min_timestamp is None:
            min_timestamp = self.block_time_mask * int(ceil(
                (self.median_past_timestamp() + 1) / self.block_time_mask
            ))
        else:
            min_timestamp = self.block_time_mask * int(ceil(
                min_timestamp / self.block_time_mask
            ))

        return BlockHeader.get_valid_block(
            min_timestamp=min_timestamp,
            max_timestamp=self.clock.time + self.max_future_block_time_seconds,
            time_step=self.block_time_mask,
            hash_prev_block=self.blocks[-1].kernel_hash(),
            stake_hash=hash_merkle_root,
            compact_target=self.get_next_compact_target(),
            real_timestamp=self.clock.time
        )
