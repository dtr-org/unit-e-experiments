#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from collections import defaultdict
from itertools import product as cartesian_product

from experiments.graph import (
    compute_degrees,
    create_simple_dense_graph,
    create_static_graph,
    create_growing_graph,
    create_network_graph,
    create_preferential_attachment_graph,
    degrees_distribution,
    enforce_nodes_reconnections,
    get_node_neighbours,
    weighted_random_int,
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
    for _ in range(10000):
        rnd = weighted_random_int([1, 12, 25, 50, 100])
        counter[rnd] += 1
        assert rnd in range5
    for i in range(1, 5):
        assert counter[i - 1] < counter[i]

    counter = defaultdict(int)
    for _ in range(10000):
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


def test_compute_degrees():
    # Very basic cases
    degrees, _ = compute_degrees(torus_grid_7x7_rd, 7 * 7)
    assert 7 * 7 == len(degrees)
    for i in degrees:
        assert 4 == degrees[i]

    degrees, _ = compute_degrees(torus_grid_7x7_lu, 7 * 7)
    assert 7 * 7 == len(degrees)
    for i in degrees:
        assert 4 == degrees[i]

    # Altering the graph alters the results
    g = torus_grid_7x7_rd.copy()
    g.add((3, 19))
    degrees, _ = compute_degrees(g, 7 * 7)
    assert 5 == degrees[3]
    assert 5 == degrees[19]
    for i in degrees:
        assert i in [3, 19] or 4 == degrees[i]

    # The function does not consider edge direction
    g.add((19, 3))
    degrees, processed_edges = compute_degrees(g, 7 * 7)
    assert 5 == degrees[3]
    assert 5 == degrees[19]
    for i in degrees:
        assert i in [3, 19] or 4 == degrees[i]

    # The function is able to reuse previous work
    g = g.union({
        (49, 17), (49, 45), (49, 21), (49, 50),
        (50, 49), (50, 45)
    })

    degrees, _ = compute_degrees(g, 7 * 7 + 2, processed_edges, degrees)
    assert 4 == degrees[49]
    assert 2 == degrees[50]
    assert 5 == degrees[17]
    assert 6 == degrees[45]
    assert 5 == degrees[21]
    for i in degrees:
        assert i in [3, 19, 49, 50, 17, 45, 21] or 4 == degrees[i]


def test_enforce_nodes_reconnections():
    g = torus_grid_7x7_rd.copy()
    idg = {i: 2 for i in range(7 * 7)}

    g2, idg2 = enforce_nodes_reconnections(graph_edges=g, inbound_degrees=idg)

    assert g is not g2
    assert len(g) == len(g2)

    assert idg is not idg2
    assert set(idg.keys()) == set(idg2.keys())
    assert min(idg2.values()) >= 0
    assert max(idg2.values()) <= 4

    degrees, _ = compute_degrees(g2, 7 * 7)
    assert min(degrees) >= 2
    assert max(degrees) <= 4
    for d in idg2:
        assert idg2[d] <= degrees[d]


def test_create_static_graph():
    g, d = create_static_graph(num_nodes=13, num_outbound_connections=5)

    assert 5 * 13 == len(g)
    for i in range(13):
        assert 5 == len({e for e in g if e[0] == i})
        assert (i, i) not in g


def test_create_growing_graph():
    g, d = create_growing_graph(num_nodes=17, num_outbound_connections=5)

    assert 17 * 5 == len(g)
    for i in range(17):
        assert 5 == len({e for e in g if e[0] == i})
        assert (i, i) not in g

    assert max(d.values()) >= 5
    assert d[16] == 0


def test_create_preferential_attachment_graph():
    g, d = create_preferential_attachment_graph(
        num_nodes=17, num_outbound_connections=5
    )

    assert 17 * 5 == len(g)
    for i in range(17):
        assert 5 == len({e for e in g if e[0] == i})
        assert (i, i) not in g

    assert max(d.values()) >= 5
    assert d[16] == 0


def test_create_simple_dense_graph():
    all_node_ids = list(range(1, 33, 2))

    for graph_size, outbound_degree in cartesian_product(
        range(5, 17), range(2, 9)
    ):
        node_ids = all_node_ids[:graph_size]
        graph = create_simple_dense_graph(
            node_ids=node_ids,
            num_outbound_connections=outbound_degree
        )

        for node_id in node_ids:
            assert (node_id, node_id) not in graph
            assert len({
                (i, j) for i, j in graph if i == node_id
            }) == min(len(node_ids) - 1, outbound_degree)


def test_create_network_graph():
    for _ in range(10):
        # Execute multiple times to take into account the randomness effects.
        graph_edges = create_network_graph(
            num_nodes=100,
            num_outbound_connections=8,
            max_inbound_connections=125,
            graph_model='preferential_attachment'
        )

        # First, we'll check that every node has 8 outbound connections
        outbound_peers_by_node = {
            src: {dst for _src, dst in graph_edges if _src == src}
            for src in {_src for _src, _dst in graph_edges}
        }
        for outbound_peers in outbound_peers_by_node.values():
            assert 8 == len(outbound_peers)

        # Second, we'll check that every node hast at least 1 inbound
        # connection, and at most 125 inbound connections
        inbound_peers_by_node = {
            dst: {src for src, _dst in graph_edges if _dst == dst}
            for dst in {_dst for _src, _dst in graph_edges}
        }
        for inbound_peers in inbound_peers_by_node.values():
            assert 1 <= len(inbound_peers) <= 125
