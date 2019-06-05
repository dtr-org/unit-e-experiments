#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from collections import defaultdict
from functools import reduce
from random import (
    randint,
    sample,
    shuffle
)
from typing import (
    DefaultDict,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)


def create_directed_graph(
        num_nodes: int,
        num_outbound_connections: int = 8,
        max_inbound_connections: int = 125,
        graph_seed_size: Optional[int] = None,
        model: str = 'static',
) -> Tuple[Set[Tuple[int, int]], Dict[int, int]]:
    """
    This function returns a set of directed edges between numbered nodes
    representing a directed graph. The graph generation models rely on the
    following assumptions:
      - There's no distinction between node types
      - The number of nodes is fixed
      - The number of outbound connections per each node is fixed (not the same
        for ingoing connections)
      - There's a maximum number of ingoing connections that a node can accept

    We can specify which model do we want to use with the `model` parameter,
    that accepts the following values:
      - 'static':
          All connections are specified at the same time. It's one of the
          simplest models, but far from being realistic.
      - 'growing':
          This model assumes a growing graph, creating connections as the nodes
          join the network. Given that the number of outbound connections is
          fixed, it has to start with a "seed" graph, with a number of nodes
          equal or greater to num_nodes + 1, if graph_seed_size is None, the
          starting size will be automatically picked. This model exhibits higher
          ingoing degree for the older nodes, in opposition of what happens with
          the static model. The rational for picking this model is that new
          nodes can only connect to nodes that were already there.
      - 'preferential_attachment':
          This model is similar to the 'growing' model, but with a small
          modification that enforces a correlation between the node's degree and
          the probability of receiving new ingoing connections. The rational for
          picking this model is that better connected nodes will be advertised
          more times by their peers when a new node asks for node listings.
    """
    if 'static' == model:
        return create_static_graph(
            num_nodes, num_outbound_connections, max_inbound_connections
        )
    elif 'growing' == model:
        return create_growing_graph(
            num_nodes, num_outbound_connections, max_inbound_connections,
            graph_seed_size
        )
    elif 'preferential_attachment' == model:
        return create_preferential_attachment_graph(
            num_nodes, num_outbound_connections, max_inbound_connections,
            graph_seed_size
        )

    raise ValueError('Not supported graph model')


def create_static_graph(
        num_nodes: int,
        num_outbound_connections: int = 8,
        max_ingoing_connections: int = 125,
) -> Tuple[Set[Tuple[int, int]], Dict[int, int]]:
    if max_ingoing_connections < num_outbound_connections:
        raise RuntimeError(
            'max_inbound_connections must be greater than or equal to num_outbound_connections'
        )

    graph_edges: Set[Tuple[int, int]] = set()
    inbound_degrees: DefaultDict[int, int] = defaultdict(int)

    for src_id in range(num_nodes):
        for _ in range(min(num_outbound_connections, num_nodes - 1)):
            dst_id = randint(0, num_nodes - 1)
            while (
                    dst_id == src_id or
                    (src_id, dst_id) in graph_edges or
                    inbound_degrees[dst_id] >= max_ingoing_connections
            ):
                dst_id = randint(0, num_nodes - 1)

            graph_edges.add((src_id, dst_id))
            inbound_degrees[dst_id] += 1

    return graph_edges, inbound_degrees


def create_growing_graph(
        num_nodes: int,
        num_outbound_connections: int = 8,
        max_inbound_connections: int = 125,
        graph_seed_size: Optional[int] = None,
) -> Tuple[Set[Tuple[int, int]], Dict[int, int]]:
    if graph_seed_size is None:
        graph_seed_size = min(num_nodes, num_outbound_connections + 1)
    elif graph_seed_size > num_nodes:
        raise RuntimeError(
            'graph_seed_size has to be lower or equal to num_nodes'
        )

    graph_edges, inbound_degrees = create_static_graph(
        graph_seed_size, num_outbound_connections, max_inbound_connections
    )

    graph_size = graph_seed_size

    for src_id in range(graph_seed_size, num_nodes):
        for _ in range(num_outbound_connections):
            dst_id = randint(0, graph_size - 1)
            while (
                    (src_id, dst_id) in graph_edges or
                    inbound_degrees[dst_id] >= max_inbound_connections
            ):
                dst_id = randint(0, graph_size - 1)

            graph_edges.add((src_id, dst_id))
            inbound_degrees[dst_id] += 1

        graph_size += 1

    return graph_edges, inbound_degrees


def create_preferential_attachment_graph(
        num_nodes: int,
        num_outbound_connections: int = 8,
        max_inbound_connections: int = 125,
        graph_seed_size: Optional[int] = None,
) -> Tuple[Set[Tuple[int, int]], Dict[int, int]]:
    if graph_seed_size is None:
        graph_seed_size = min(num_nodes, num_outbound_connections + 1)
    elif graph_seed_size > num_nodes:
        raise RuntimeError(
            'graph_seed_size has to be lower or equal to num_nodes'
        )

    directed_edges, inbound_degrees = create_static_graph(
        graph_seed_size, num_outbound_connections, max_inbound_connections
    )

    degrees, normalized_edges = compute_degrees(directed_edges, graph_seed_size)
    degrees_dist = degrees_distribution(degrees)

    graph_size = graph_seed_size

    for src_id in range(graph_seed_size, num_nodes):
        for _ in range(num_outbound_connections):
            dst_id = weighted_random_int(degrees_dist)
            while (
                    (src_id, dst_id) in directed_edges or
                    inbound_degrees[dst_id] >= max_inbound_connections
            ):
                dst_id = weighted_random_int(degrees_dist)

            directed_edges.add((src_id, dst_id))
            inbound_degrees[dst_id] += 1

            degrees, normalized_edges = compute_degrees(
                graph_edges={(src_id, dst_id)},
                num_nodes=graph_size + 1,
                processed_edges=normalized_edges,
                degrees=degrees
            )

        degrees_dist = degrees_distribution(degrees)
        graph_size += 1

    return directed_edges, inbound_degrees


def create_simple_dense_graph(
    node_ids: List[int],
    num_outbound_connections: int = 8
) -> Set[Tuple[int, int]]:
    """
    This function takes specific node/vertex ids and creates a densely connected
    directed graph, when len(node_ids) <= num_outbound_connections, the graph
    will be a clique.
    """
    directed_edges = set()

    for idx, node_id in enumerate(node_ids):
        num_cons = 0
        peers = node_ids[idx + 1:] + node_ids[:idx]
        for peer_id in peers:
            if num_cons >= min(num_outbound_connections, len(node_ids) - 1):
                break
            directed_edges.add((node_id, peer_id))
            num_cons += 1

    return directed_edges


def create_network_graph(
    num_nodes: int,
    num_outbound_connections: int,
    max_inbound_connections: int,
    graph_model: str = 'preferential_attachment',
) -> Set[Tuple[int, int]]:
    """
    This function creates a graph ensuring that it holds some properties that
    makes it suitable to represent a Unit-e network's topology without isolated
    nor sink nodes.
    """
    graph_edges, inbound_degrees = create_directed_graph(
        num_nodes=num_nodes,
        num_outbound_connections=num_outbound_connections,
        max_inbound_connections=max_inbound_connections,
        model=graph_model
    )

    # We try to avoid having sink sub-graphs
    graph_edges, inbound_degrees = enforce_nodes_reconnections(
        graph_edges=graph_edges,
        inbound_degrees=inbound_degrees,
        num_reconnection_rounds=1,
    )

    # This fix the rare case where some nodes don't have inbound connections
    graph_edges, _ = ensure_one_inbound_connection_per_node(
        num_nodes=num_nodes,
        graph_edges=graph_edges,
        inbound_degrees=inbound_degrees,
    )

    return graph_edges


def enforce_nodes_reconnections(
        graph_edges: Set[Tuple[int, int]],
        inbound_degrees: Dict[int, int],
        num_reconnection_rounds: int = 1,
) -> Tuple[Set[Tuple[int, int]], Dict[int, int]]:
    """
    This function tries to 'shuffle' the graph by simulating nodes
    re-connections, this is useful to decrease the probability of having "sink
    nodes" or "sink sub-graphs" (where information arrives, but does not flow to
    the rest of the graph), a clear side effect of using the preferential
    attachment model on a directed graph.
    """
    graph_edges = graph_edges.copy()
    inbound_degrees = inbound_degrees.copy()

    node_ids = list({e[0] for e in graph_edges})

    for _ in range(num_reconnection_rounds):
        shuffle(node_ids)  # We randomize the reconnection steps

        for node_id in node_ids:
            neighbours2dg = get_node_neighbours(node_id, graph_edges, 1)

            inbound_neighbours = {e[0] for e in graph_edges if e[1] == node_id}
            neighbours_neighbours = {
                neighbour: get_node_neighbours(neighbour, graph_edges, 1)
                for neighbour in inbound_neighbours
            }

            # Disconnecting node, just for an instant
            num_outbound_connections = 0
            for e in graph_edges.copy():
                if e[0] == node_id or e[1] == node_id:
                    graph_edges.remove(e)
                    inbound_degrees[e[1]] -= 1
                    if e[0] == node_id:
                        num_outbound_connections += 1

            # Reconnecting the node to others
            num_recreated_outbound_connections = 0
            while num_recreated_outbound_connections < num_outbound_connections:
                e = (node_id, sample(neighbours2dg, 1)[0])
                if e not in graph_edges:
                    graph_edges.add(e)
                    inbound_degrees[e[1]] += 1
                    num_recreated_outbound_connections += 1

            # Reconnecting inbound neighbours
            for old_neighbour in inbound_neighbours:
                e = (
                    old_neighbour,
                    sample(neighbours_neighbours[old_neighbour], 1)[0]
                )
                while e in graph_edges:
                    e = (
                        old_neighbour,
                        sample(neighbours_neighbours[old_neighbour], 1)[0]
                    )
                graph_edges.add(e)
                inbound_degrees[e[1]] += 1

    return graph_edges, inbound_degrees


def get_node_neighbours(
        node_id: int,
        graph_edges: Set[Tuple[int, int]],
        degree: int = 1
) -> Set[int]:
    """Returns the second-degree neighbours of a node in a given graph"""
    neighbours = {e[0] for e in graph_edges if e[1] == node_id}.union({
        e[1] for e in graph_edges if e[0] == node_id
    })

    for _ in range(1, degree):
        neighbours = {e[0] for e in graph_edges if e[1] in neighbours}.union({
            e[1] for e in graph_edges if e[0] in neighbours
        }).union(neighbours)

    return neighbours.difference({node_id})


def compute_degrees(
        graph_edges: Set[Tuple[int, int]],
        num_nodes: int,
        processed_edges: Optional[Set[Tuple[int, int]]] = None,
        degrees: Optional[List[int]] = None
) -> Tuple[List[int], Set[Tuple[int, int]]]:
    """
    Computes the node degrees without making distinctions between inbound &
    outbound connections. It returns the list of processed edges as well in
    order to allow incremental processing.
    """

    if processed_edges is None:
        processed_edges = set()

    if degrees is None:
        degrees = []
    if len(degrees) < num_nodes:
        degrees = degrees + [0] * (num_nodes - len(degrees))

    for edge in graph_edges:
        normalized_edge = (max(edge), min(edge))

        if normalized_edge in processed_edges:
            continue

        degrees[edge[0]] += 1
        degrees[edge[1]] += 1
        processed_edges.add(normalized_edge)

    return degrees, processed_edges


def degrees_distribution(degrees: List[int]) -> List[int]:
    """
    Given an ordered list of degrees, it returns a distribution suitable for
    weighed random selections
    """
    return reduce(lambda dd, d: dd + [dd[-1] + d], degrees, [0])[1:]


def weighted_random_int(degrees_dist: List[int]) -> int:
    """
    Returns a random integer between 0 and L, being L the length of an
    accumulated integer weights list
    """
    uniform_rnd = randint(1, degrees_dist[-1])
    for idx, accumulated_weight in enumerate(degrees_dist):
        if uniform_rnd <= accumulated_weight:
            return idx
    raise ValueError(
        'The provided degrees_dist input does not conform to the expected structure'
    )


def ensure_one_inbound_connection_per_node(
        num_nodes: int,
        graph_edges: Set[Tuple[int, int]],
        inbound_degrees: Dict[int, int]
) -> Tuple[Set[Tuple[int, int]], Dict[int, int]]:
    """
    This function tries to enforce that each node has at least 1 inbound
    connection by performing a small amount of changes without altering most of
    the network's properties.
    """

    graph_edges = graph_edges.copy()
    inbound_degrees = inbound_degrees.copy()

    lonely_nodes = [i for i in range(num_nodes) if inbound_degrees[i] == 0]
    nodes_by_popularity = sorted(
        inbound_degrees.items(), key=lambda x: x[1], reverse=True
    )

    for lonely_node in lonely_nodes:
        popular_node, popularity = nodes_by_popularity[0]

        edge_to_remove = [e for e in graph_edges if e[1] == popular_node][0]

        graph_edges.remove(edge_to_remove)
        graph_edges.add((edge_to_remove[0], lonely_node))

        inbound_degrees[popular_node] -= 1
        inbound_degrees[lonely_node] += 1
        nodes_by_popularity = sorted(
            inbound_degrees.items(), key=lambda x: x[1], reverse=True
        )

    return graph_edges, inbound_degrees
