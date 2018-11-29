#!/usr/bin/env python3

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from collections import defaultdict

from experiments.utils.graph import (
    degrees_distribution,
    weighted_random_int,
    get_node_neighbours,
)


torus_grid_7x7_rd = {  # The edges point "to the right" and down
    e for ep in {
        ((i * 7 + j, i * 7 + (j + 1) % 7), (i * 7 + j, (((i + 1) % 7) * 7 + j)))
        for i in range(7) for j in range(7)
    } for e in ep
}
torus_grid_7x7_lu = {  # The edges point "to the left" and up
    e for ep in {
        ((i * 7 + j, i * 7 + (j - 1) % 7), (i * 7 + j, (((i - 1) % 7) * 7 + j)))
        for i in range(7) for j in range(7)
    } for e in ep
}


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


def test_get_node_neighbours():
    assert {1, 7, 6, 42} == get_node_neighbours(
        node_id=0, graph_edges=torus_grid_7x7_rd, degree=1
    )
    assert {1, 7, 6, 42} == get_node_neighbours(
        node_id=0, graph_edges=torus_grid_7x7_lu, degree=1
    )
    assert {47, 41, 42, 6} == get_node_neighbours(
        node_id=48, graph_edges=torus_grid_7x7_rd, degree=1
    )
    assert {47, 41, 42, 6} == get_node_neighbours(
        node_id=48, graph_edges=torus_grid_7x7_lu, degree=1
    )

    assert {1, 7, 6, 42, 2, 8, 43, 14, 5, 48, 13, 35} == get_node_neighbours(
        node_id=0, graph_edges=torus_grid_7x7_rd, degree=2
    )
    assert {1, 7, 6, 42, 2, 8, 43, 14, 5, 48, 13, 35} == get_node_neighbours(
        node_id=0, graph_edges=torus_grid_7x7_lu, degree=2
    )
    assert {47, 41, 42, 6, 0, 5, 34, 35, 40, 43, 13, 46} == get_node_neighbours(
        node_id=48, graph_edges=torus_grid_7x7_rd, degree=2
    )
    assert {47, 41, 42, 6, 0, 5, 34, 35, 40, 43, 13, 46} == get_node_neighbours(
        node_id=48, graph_edges=torus_grid_7x7_lu, degree=2
    )
