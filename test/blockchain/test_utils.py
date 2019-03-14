#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from struct import pack

from blockchain.utils import (
    compact_target_to_uint256,
    uint256_to_compact_target
)


def test_compact_target_to_uint256():
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


def test_uint256_to_compact_target():
    for num_leading_zeros in range(232):
        compact_target = pack('B', 255 - num_leading_zeros) + b'xyz'
        test_hash = compact_target_to_uint256(compact_target)

        assert compact_target == uint256_to_compact_target(test_hash)

    # TODO: Test beyond 232, fix bug
