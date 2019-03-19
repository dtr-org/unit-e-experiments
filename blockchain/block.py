#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from hashlib import sha256
from struct import pack
from typing import Any, List, Optional

from blockchain import max_uint256_val, zeroes_uint256
from blockchain.transaction import CoinStakeTransaction
from blockchain.utils import (
    compact_target_to_bigint,
    bigint_to_compact_target
)


class Block:
    def __init__(
        self, *,
        prev_block_hash: bytes,
        prev_block_stake_modifier: bytes,
        compact_target: bytes,
        coinstake_tx: CoinStakeTransaction,
        timestamp: int,
        real_timestamp: Optional[int] = None
    ):
        self.prev_block_hash = prev_block_hash
        self.prev_block_stake_modifier = prev_block_stake_modifier
        self.compact_target = compact_target

        self.coinstake_tx = coinstake_tx

        self.timestamp = timestamp
        self.real_timestamp = timestamp if real_timestamp is None else real_timestamp

        self._kernel_hash_base: Optional[Any] = None  # Optional[HASH]
        self._kernel_hash: Optional[bytes] = None

        self._stake_modifier: Optional[bytes] = None

        self._block_hash_base: Optional[Any] = None  # Optional[HASH]
        self._block_hash: Optional[bytes] = None

    @staticmethod
    def genesis(
        *,
        timestamp: int = 0,
        compact_target: bytes = b'\xff\x0f\xff\xff',
        vout: Optional[List[int]] = None
    ) -> 'Block':
        return Block(
            prev_block_hash=zeroes_uint256,
            prev_block_stake_modifier=zeroes_uint256,
            compact_target=compact_target,
            coinstake_tx=CoinStakeTransaction.genesis(vout=vout),
            timestamp=timestamp,
            real_timestamp=timestamp
        )

    def stake_modifier(self) -> bytes:
        if self._stake_modifier is None:
            self._stake_modifier = sha256(
                self.coinstake_tx.vin[0].txo.tx_hash +  # prevout tx hash
                self.prev_block_stake_modifier
            ).digest()
        return self._stake_modifier

    def kernel_hash(self) -> bytes:
        if self._kernel_hash is None:
            if self._kernel_hash_base is None:
                self._kernel_hash_base = sha256(
                    self.prev_block_stake_modifier +
                    self.coinstake_tx.vin[0].txo.tx_hash +
                    pack('>I', self.coinstake_tx.vin[0].txo.out_idx)
                )
            _kernel_hash = self._kernel_hash_base.copy()
            _kernel_hash.update(pack('>I', self.timestamp))
            self._kernel_hash = _kernel_hash.digest()
        return self._kernel_hash

    def block_hash(self) -> bytes:
        if self._block_hash is None:
            if self._block_hash_base is None:
                self._block_hash_base = sha256(
                    self.prev_block_hash +
                    self.compact_target +
                    self.coinstake_tx.tx_hash()
                )
            _block_hash = self._block_hash_base.copy()
            _block_hash.update(pack('>I', self.timestamp))
            self._block_hash: bytes = _block_hash.digest()
        return self._block_hash

    def __hash__(self):
        return self.block_hash().__hash__()

    def __eq__(self, other):
        return (
            isinstance(other, Block) and
            self.block_hash() == other.block_hash()
        )

    def try_to_be_valid(
        self, *,
        max_timestamp: int,
        time_mask: int,
        greedy_proposal: bool = True
    ) -> Optional['Block']:
        """
        Modifies the block's timestamp until it's valid, returns None if it's
        not able to do that, itself otherwise.

        Relies on the assumption that the initial timestamp is compatible with
        the give time_mask value.
        """
        if self.coinstake_tx.height == 0 and self.coinstake_tx.vin[0].amount == 0:
            # To avoid setting custom_target to 0 at genesis
            custom_target = compact_target_to_bigint(self.compact_target)
        else:
            stake = self.coinstake_tx.vin[0].amount
            custom_target = compact_target_to_bigint(self.compact_target) * stake

        if greedy_proposal:
            while (
                int.from_bytes(self.kernel_hash(), 'big') >= custom_target and
                self.timestamp < max_timestamp
            ):
                self.timestamp += time_mask
                self._kernel_hash = None

        if int.from_bytes(self.kernel_hash(), 'big') < custom_target:
            del self._kernel_hash_base  # Feeding the GC
            self._block_hash = None
            self.block_hash()
            del self._block_hash_base  # Feeding the GC

            return self
        else:
            return None

    def fit_target(self) -> 'Block':
        """
        Adjusts the difficulty as much as possible while keeping the kernel
        hash smaller than the target.
        This is a convenience method to tune genesis blocks, although not ideal,
        it's slightly better than starting with target == b'\xff\xff\xff\xff'.
        """
        self.compact_target = bigint_to_compact_target(
            min(
                max_uint256_val,
                (
                    int.from_bytes(self.kernel_hash(), 'big') //
                    max(1, self.coinstake_tx.vin[0].amount)
                ) +
                (2 ** 24)  # From the compact target's "mantissa" size.
            )
        )
        assert self.is_valid()
        return self

    def is_valid(self) -> bool:
        return int.from_bytes(self.kernel_hash(), 'big') < (
            compact_target_to_bigint(self.compact_target) *
            max(1, self.coinstake_tx.vin[0].amount)
        )
