#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from struct import pack


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


def bigint_to_compact_target(bigint: int) -> bytes:
    return uint256_to_compact_target(int.to_bytes(bigint, 32, 'big'))


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
