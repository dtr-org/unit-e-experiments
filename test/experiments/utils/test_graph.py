#!/usr/bin/env python3

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from experiments.utils.graph import degrees_distribution


def test_degrees_distribution():
    assert [1, 3, 6, 10, 15, 21] == degrees_distribution([1, 2, 3, 4, 5, 6])
    assert [6, 11, 15, 18, 20, 21] == degrees_distribution([6, 5, 4, 3, 2, 1])
