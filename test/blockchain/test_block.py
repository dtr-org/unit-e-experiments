#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from itertools import product as cartesian_product

from blockchain import zeroes_uint256
from blockchain.block import Block
from blockchain.transaction import CoinStakeTransaction
from blockchain.utils import (
    compact_target_to_bigint,
    compact_target_to_uint256
)


def test_block_block_hash():
    uncombined_params = [
        [b'123456789012345678901234567890ab', b'ab123456789012345678901234567890'],
        [b'123456789012345678901234567890cd', b'cd123456789012345678901234567890'],
        [b'\xff\xff\xff\xff', b'\x07\xff\xff\xff'],
        [CoinStakeTransaction.genesis()],
        [16, 32, 48, 64, 80, 96, 112, 128],
    ]
    block_params = list(cartesian_product(*uncombined_params))

    hashes = set()
    for params in block_params:
        block = Block(
            prev_block_hash=params[0],
            prev_block_stake_modifier=params[1],
            compact_target=params[2],
            coinstake_tx=params[3],
            timestamp=params[4]
        )

        test_hash = block.block_hash()  # SUT
        assert len(test_hash) == 32
        hashes.add(test_hash)

    # All hashes are different (& prev stake modifier is not in the header)
    assert len(hashes) == len(block_params) / len(uncombined_params[1])


def test_block_try_to_be_valid():
    # The difficulty is so low that they must be equal
    genesis = Block.genesis()

    assert genesis.kernel_hash() < compact_target_to_uint256(genesis.compact_target)
    assert int.from_bytes(genesis.kernel_hash(), 'big') < compact_target_to_bigint(genesis.compact_target)

    valid_block_01 = Block.genesis().try_to_be_valid(
        max_timestamp=16384,
        time_mask=1
    )
    assert valid_block_01.block_hash() == genesis.block_hash()
    assert valid_block_01.kernel_hash() == genesis.kernel_hash()

    # The difficulty is so high that it's not possible to find a block
    none_block = Block(
        prev_block_hash=zeroes_uint256,
        prev_block_stake_modifier=zeroes_uint256,
        compact_target=b'\x04\xff\xff\xff',
        coinstake_tx=CoinStakeTransaction.genesis(),
        timestamp=0
    ).try_to_be_valid(max_timestamp=256, time_mask=16)
    assert none_block is None

    # Is it possible to find valid blocks under reasonable constrains
    valid_block_02 = Block(
        prev_block_hash=zeroes_uint256,
        prev_block_stake_modifier=zeroes_uint256,
        compact_target=b'\xf0\xff\xff\xff',
        coinstake_tx=CoinStakeTransaction.genesis(),
        timestamp=0
    ).try_to_be_valid(max_timestamp=2**16, time_mask=1)

    assert valid_block_02 is not None
    assert valid_block_02.kernel_hash() < compact_target_to_uint256(valid_block_02.compact_target)
