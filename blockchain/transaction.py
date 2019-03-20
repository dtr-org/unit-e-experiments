#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from hashlib import sha256
from struct import pack
from typing import List, NamedTuple, Optional

from blockchain import zeroes_uint256


class TransactionOutput(NamedTuple):
    """Just a "reference" to the point where a coin was created."""
    tx_hash: bytes
    out_idx: int

    @staticmethod
    def genesis() -> 'TransactionOutput':
        return TransactionOutput(
            tx_hash=zeroes_uint256,
            out_idx=0
        )


class Coin(NamedTuple):
    """A 'wrapper' around TransactionOutput, carrying more information."""
    amount: int
    height: int
    txo: TransactionOutput

    @staticmethod
    def genesis() -> 'Coin':
        return Coin(amount=0, height=0, txo=TransactionOutput.genesis())


class CoinStakeTransaction:
    def __init__(
        self, *,
        vin: List[Coin],
        vout: Optional[List[int]] = None,
        height: int = 0
    ):
        """
        Except for genesis, the first output is always the reward, the second is
        always the combination of all the inputs (stake & other coins we want to
        merge)
        """
        self.vin = vin

        if vout is None:
            # We combine stakes by default, if there's something to combine.
            combined_stake = sum(c.amount for c in vin)
            if combined_stake == 0:
                self.vout = [1]
            else:
                self.vout = [1, combined_stake]
        else:
            # We'll use this to create multiple coins at genesis
            self.vout = vout

        self.height = height  # Not really part of tx, just for convenience

        self._tx_hash: Optional[bytes] = None
        self._all_coins: Optional[List[Coin]] = None

    @staticmethod
    def genesis(vout: Optional[List[int]] = None) -> 'CoinStakeTransaction':
        return CoinStakeTransaction(vin=[Coin.genesis()], vout=vout, height=0)

    def tx_hash(self) -> bytes:
        if self._tx_hash is None:
            self._tx_hash = sha256(
                pack('>I', len(self.vin)) +
                b''.join(
                    c.txo.tx_hash +
                    pack('>III', c.txo.out_idx, c.height, c.amount)
                    for c in self.vin
                ) +
                pack('>I', len(self.vout)) +
                b''.join(pack('>I', o) for o in self.vout)
            ).digest()
        return self._tx_hash

    def get_nth_coin(self, out_idx) -> Coin:
        return Coin(
            height=self.height,
            amount=self.vout[out_idx],
            txo=TransactionOutput(
                tx_hash=self.tx_hash(),
                out_idx=out_idx
            )
        )

    def get_all_coins(self) -> List[Coin]:
        """
          - The 0th coin (except in genesis) will be the reward.
          - The 1st coin (except in genesis) will be the stake combination.
          - Whenever we have more coins (just at genesis for this simulations),
            their positions mean nothing.
        """
        if self._all_coins is None:
            self._all_coins = [
                self.get_nth_coin(out_idx)
                for out_idx in range(len(self.vout))
            ]
        return self._all_coins

    def __hash__(self):
        return self.tx_hash().__hash__()

    def __eq__(self, other):
        return (
            isinstance(other, CoinStakeTransaction) and
            self.tx_hash() == other.tx_hash()
        )
