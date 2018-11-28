#!/usr/bin/env python3

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from collections import defaultdict

from experiments.utils.graph import (
    degrees_distribution,
    weighted_random_int
)


def test_degrees_distribution():
    assert [1, 3, 6, 10, 15, 21] == degrees_distribution([1, 2, 3, 4, 5, 6])
    assert [6, 11, 15, 18, 20, 21] == degrees_distribution([6, 5, 4, 3, 2, 1])


def test_weighted_random_int():
    range5 = list(range(5))

    counter = defaultdict(int)
    for i in range(10000):
        rnd = weighted_random_int([1, 12, 25, 50, 100])
        counter[rnd] += 1
        assert rnd in range5
    for i in range(1, 5):
        assert counter[i - 1] < counter[i]

    counter = defaultdict(int)
    for i in range(10000):
        rnd = weighted_random_int([50, 75, 88, 99, 100])
        counter[rnd] += 1
        assert rnd in range5
    for i in range(1, 5):
        assert counter[i - 1] > counter[i]
