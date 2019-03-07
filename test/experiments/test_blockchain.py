#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


import pytest

from itertools import product as cartesian_product
from struct import pack

from experiments.blockchain import (
    BlockChain,
    BlockHeader,
    Clock,
    compact_target_to_uint256,
    uint256_to_compact_target
)


def test_compact_target_to_hash():
    # 1st case: 255 leading zeroes
    test_hash = compact_target_to_uint256(b'\x00\x00\x00\x00')
    for i in range(31):
        assert 0 == test_hash[i]
    assert 1 == test_hash[31]

    # 2nd case: N leading zeroes
    for num_leading_zeros in range(256):
        compact_target = pack('B', 255 - num_leading_zeros) + b'\xff\xff\xff'
        test_hash = compact_target_to_uint256(compact_target)

        for bit_index in range(num_leading_zeros):
            byte = test_hash[bit_index // 8]
            bit = bool(byte & (2 ** (7 - bit_index % 8)))
            assert not bit

        # Checking that after that we start finding ones
        bit_index = num_leading_zeros
        byte = test_hash[bit_index // 8]
        bit = bool(byte & (2 ** (7 - bit_index % 8)))
        assert bit

    # 3rd case: The last 24 bits of the compact target match the first 24 bits
    #           after the first active bit.
    for num_leading_zeros in range(7, 232, 8):
        compact_target = pack('B', 255 - num_leading_zeros) + b'abc'
        test_hash = compact_target_to_uint256(compact_target)
        byte_index = (num_leading_zeros + 1) // 8

        assert b'abc' == test_hash[byte_index:byte_index + 3]
        assert b'\xff' * (32 - byte_index - 3) == test_hash[byte_index + 3:]


def test_hash_to_compact_target():
    for num_leading_zeros in range(232):
        compact_target = pack('B', 255 - num_leading_zeros) + b'xyz'
        test_hash = compact_target_to_uint256(compact_target)

        assert compact_target == uint256_to_compact_target(test_hash)

    # TODO: Test beyond 232, fix bug


def test_block_header_init():
    with pytest.raises(expected_exception=AssertionError):
        BlockHeader(
            hash_prev_block=b'',  # Invalid hash
            stake_hash=b'123456789012345678901234567890ab',
            timestamp=1,
            compact_target=b'\xff\xff\xff\xff'
        )
    with pytest.raises(expected_exception=AssertionError):
        BlockHeader(
            hash_prev_block=b'123456789012345678901234567890ab',
            stake_hash=b'',  # Invalid hash
            timestamp=1,
            compact_target=b'\xff\xff\xff\xff'
        )
    with pytest.raises(expected_exception=AssertionError):
        BlockHeader(
            hash_prev_block=b'123456789012345678901234567890ab',
            stake_hash=b'123456789012345678901234567890ab',
            timestamp=-1,  # Invalid timestamp
            compact_target=b'\xff\xff\xff\xff'
        )
    with pytest.raises(expected_exception=AssertionError):
        BlockHeader(
            hash_prev_block=b'123456789012345678901234567890ab',
            stake_hash=b'123456789012345678901234567890ab',
            timestamp=2**32,  # Invalid timestamp
            compact_target=b'\xff\xff\xff\xff'
        )
    with pytest.raises(expected_exception=AssertionError):
        BlockHeader(
            hash_prev_block=b'123456789012345678901234567890ab',
            stake_hash=b'123456789012345678901234567890ab',
            timestamp=1,
            compact_target=b'\xff\xff\xff\xff\xff'  # Too long target
        )
    with pytest.raises(expected_exception=AssertionError):
        BlockHeader(
            hash_prev_block=b'123456789012345678901234567890ab',
            stake_hash=b'123456789012345678901234567890ab',
            timestamp=1,
            compact_target=b'\xff\xff\xff'  # Too short target
        )


def test_block_header_hash_and_coin():
    header_params = list(cartesian_product(
        [b'123456789012345678901234567890ab', b'ab123456789012345678901234567890'],
        [b'123456789012345678901234567890cd', b'cd123456789012345678901234567890'],
        [16, 32, 48, 64, 80, 96, 112, 128],
        [b'\xff\xff\xff\xff', b'\x07\xff\xff\xff']
    ))

    hashes = set()
    coins = set()
    for params in header_params:
        block_header = BlockHeader(
            hash_prev_block=params[0],
            stake_hash=params[1],
            timestamp=params[2],
            compact_target=params[3]
        )
        test_hash = block_header.kernel_hash()  # SUT
        test_coin = block_header.coin_hash()  # SUT

        assert len(test_hash) == 32
        assert len(test_coin) == 32

        hashes.add(test_hash)
        coins.add(test_coin)

    # All hashes (& "coins") are different
    assert len(hashes) == len(header_params)
    assert len(coins) == len(header_params)


def test_block_header_increase_timestamp():
    block_header = BlockHeader(
        hash_prev_block=b'123456789012345678901234567890ab',
        stake_hash=b'123456789012345678901234567890cd',
        timestamp=16,
        compact_target=b'\x7f\xff\xff\xff'
    )
    block_header.kernel_hash()

    with pytest.raises(expected_exception=AssertionError):
        block_header.increase_timestamp(-4)  # We don't go back in time

    block_header.increase_timestamp(8)
    assert block_header._kernel_hash is None
    assert block_header._coin_hash is None
    assert block_header.timestamp == 24


def test_block_header_get_valid_block():
    trivial_block = BlockHeader(
        hash_prev_block=b'00000000000000000000000000000000',
        stake_hash=b'00000000000000000000000000000000',
        timestamp=0,
        compact_target=b'\xff\xff\xff\xff'
    )

    valid_block_01 = BlockHeader.get_valid_block(
        min_timestamp=0,
        max_timestamp=16384,
        time_step=1,
        hash_prev_block=b'00000000000000000000000000000000',
        stake_hash=b'00000000000000000000000000000000',
        compact_target=b'\xff\xff\xff\xff'
    )

    # The difficulty is so low that they must be equal
    assert valid_block_01.kernel_hash() == trivial_block.kernel_hash()

    none_block = BlockHeader.get_valid_block(
        min_timestamp=0,
        max_timestamp=256,
        time_step=16,
        hash_prev_block=b'00000000000000000000000000000000',
        stake_hash=b'00000000000000000000000000000000',
        compact_target=b'\x04\xff\xff\xff'
    )

    # The difficulty is so high that it's not possible to find a block
    assert none_block is None

    valid_block_02 = BlockHeader.get_valid_block(
        min_timestamp=0,
        max_timestamp=2**16,
        time_step=1,
        hash_prev_block=b'00000000000000000000000000000000',
        stake_hash=b'00000000000000000000000000000000',
        compact_target=b'\xf0\xff\xff\xff'
    )

    assert valid_block_02 is not None
    assert valid_block_02.kernel_hash() < compact_target_to_uint256(valid_block_02.compact_target)


def test_clock():
    with pytest.raises(expected_exception=AssertionError):
        Clock(-1)
    clock = Clock(16)
    assert clock.time == 16

    clock.advance_time()
    assert clock.time == 17


def test_blockchain_init():
    # This is our genesis block!
    block_ts00 = BlockHeader(
        hash_prev_block=b'00000000000000000000000000000000',
        stake_hash=b'00000000000000000000000000000000',
        timestamp=0,
        compact_target=b'\xff\xff\xff\xff'
    )

    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, stake_maturing_period=-1)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, stake_maturing_period=151)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, stake_blocking_period=-1)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, stake_blocking_period=151)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, num_blocks_for_median_timestamp=0)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, num_blocks_for_median_timestamp=21)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, max_future_block_time_seconds=15)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, max_future_block_time_seconds=3601)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, difficulty_adjustment_period=0)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, difficulty_adjustment_period=257)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, difficulty_adjustment_window=5)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, difficulty_adjustment_window=257)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, time_between_blocks=3)
    with pytest.raises(expected_exception=AssertionError):
        BlockChain(genesis=block_ts00, time_between_blocks=121)

    clock_00 = Clock(0)
    block_ts16 = BlockHeader(
        hash_prev_block=b'00000000000000000000000000000000',
        stake_hash=b'00000000000000000000000000000000',
        timestamp=16,
        compact_target=b'\xff\xff\xff\xff'
    )

    with pytest.raises(expected_exception=AssertionError):
        # It fails because the block is "from the future"
        BlockChain(clock=clock_00, genesis=block_ts16)

    impossible_block = BlockHeader(
        hash_prev_block=b'00000000000000000000000000000000',
        stake_hash=b'00000000000000000000000000000000',
        timestamp=16,
        compact_target=b'\x00\x00\x00\x00'
    )

    with pytest.raises(expected_exception=AssertionError):
        # It fails because the target is to small, or the difficulty too high
        BlockChain(genesis=impossible_block)


def test_blockchain_add_block():
    genesis_block = BlockHeader(
        hash_prev_block=b'00000000000000000000000000000000',
        stake_hash=b'00000000000000000000000000000000',
        timestamp=0,
        compact_target=b'\xfe\xff\xff\xff'
    )

    blockchain = BlockChain(genesis=genesis_block, clock=Clock(256))

    with pytest.raises(expected_exception=AssertionError):
        # hash_prev_block does not match the genesis block's hash
        blockchain.add_block(BlockHeader(
            hash_prev_block=b'00000000000000000000000000000000',
            stake_hash=b'00000000000000000000000000000000',
            timestamp=272,
            compact_target=b'\xfe\xff\xff\xff'
        ))

    with pytest.raises(expected_exception=AssertionError):
        # We're not using a previously created coin to stake
        blockchain.add_block(BlockHeader(
            hash_prev_block=genesis_block.kernel_hash(),
            stake_hash=b'00000000000000000000000000000000',
            timestamp=272,
            compact_target=b'\xfe\xff\xff\xff'
        ))

    with pytest.raises(expected_exception=AssertionError):
        # Too far in the past
        blockchain.add_block(BlockHeader(
            hash_prev_block=genesis_block.kernel_hash(),
            stake_hash=genesis_block.coin_hash(),
            timestamp=16,
            compact_target=b'\xfe\xff\xff\xff'
        ))

    with pytest.raises(expected_exception=AssertionError):
        # Too far in the future
        blockchain.add_block(BlockHeader(
            hash_prev_block=genesis_block.kernel_hash(),
            stake_hash=genesis_block.coin_hash(),
            timestamp=1000272,
            compact_target=b'\xfe\xff\xff\xff'
        ))

    with pytest.raises(expected_exception=AssertionError):
        cmpct_target = bytearray(blockchain.get_next_compact_target())
        cmpct_target[3] = (cmpct_target[3] + 1) % 256  # Arbitrary change
        cmpct_target = bytes(cmpct_target)

        # The target differs from what's expected
        blockchain.add_block(BlockHeader(
            hash_prev_block=genesis_block.kernel_hash(),
            stake_hash=genesis_block.coin_hash(),
            timestamp=272,
            compact_target=cmpct_target
        ))

    with pytest.raises(expected_exception=AssertionError):
        block_02 = BlockHeader(
            hash_prev_block=genesis_block.kernel_hash(),
            stake_hash=genesis_block.coin_hash(),
            timestamp=272,
            compact_target=blockchain.get_next_compact_target()
        )

        # The hash is bigger than the intended target
        assert block_02.kernel_hash() > compact_target_to_uint256(
            blockchain.get_next_compact_target()
        )
        blockchain.add_block(block_02)

    # This block will be valid
    block_02 = blockchain.get_valid_block(genesis_block.coin_hash())
    assert block_02 is not None

    # The valid block is successfully added to the chain
    chain_work_0 = blockchain.get_chain_work()
    blockchain.add_block(block_02)
    chain_work_1 = blockchain.get_chain_work()

    assert 2 == blockchain.height
    assert chain_work_1 > chain_work_0
    assert chain_work_1 == blockchain.get_chain_work()


def test_blockchain_get_chain_work():
    # When we have more proposers staking, the difficulty increases
    genesis_block = BlockHeader(
        hash_prev_block=b'00000000000000000000000000000abc',
        stake_hash=b'00000000000000000000000000000xyz',
        timestamp=256,
        compact_target=b'\xfe\xff\xff\xff'
    )

    # Creating a "strong" chain
    blockchain_a = BlockChain(
        genesis=genesis_block,
        clock=Clock(257),
        max_future_block_time_seconds=88,  # 11 * 16 / 2
        time_between_blocks=16,
        block_time_mask=1,
        difficulty_adjustment_period=4,
        difficulty_adjustment_window=40
    )

    for _ in range(64):
        # We use all the coins to stake
        stakeable_blocks = blockchain_a.blocks

        min_timestamp = None  # We pass this to avoid repeating work
        candidates = []
        while 0 == len(candidates):
            candidates = sorted(
                [b1 for b1 in (
                    blockchain_a.get_valid_block(b2.coin_hash(), min_timestamp)
                    for b2 in stakeable_blocks
                ) if b1 is not None],
                key=lambda b3: b3.kernel_hash(),
                reverse=True
            )
            blockchain_a.clock.advance_time(1)
            min_timestamp = blockchain_a.clock.time + blockchain_a.max_future_block_time_seconds - 1

        # We append the best candidate block, we do not need validation here
        blockchain_a.add_block_fast(candidates[0])

    # Creating a "weak" chain
    blockchain_b = BlockChain(
        genesis=genesis_block,
        clock=Clock(257),
        max_future_block_time_seconds=176,  # 11 * 16 / 2
        time_between_blocks=16,
        block_time_mask=1,
        difficulty_adjustment_period=1,
        difficulty_adjustment_window=40
    )
    for _ in range(64):
        # We only use half of the coins to stake, that's why is weaker
        stakeable_blocks = blockchain_b.blocks[:max(1, len(blockchain_a.blocks) // 2)]

        min_timestamp = None  # We pass this to avoid repeating work
        candidates = []
        while 0 == len(candidates):
            candidates = sorted(
                [b1 for b1 in (
                    blockchain_b.get_valid_block(b2.coin_hash(), min_timestamp)
                    for b2 in stakeable_blocks
                ) if b1 is not None],
                key=lambda b3: b3.kernel_hash(),
                reverse=True
            )
            blockchain_b.clock.advance_time(1)
            min_timestamp = blockchain_b.clock.time + blockchain_b.max_future_block_time_seconds - 1

        # We append the best candidate block
        blockchain_b.add_block_fast(candidates[0])

    assert blockchain_a.get_next_compact_target() < blockchain_b.get_next_compact_target()
    assert blockchain_a.get_chain_work() > blockchain_b.get_chain_work()
