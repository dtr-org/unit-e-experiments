from asyncio import (
    AbstractEventLoop,
    AbstractServer,
    sleep as asyncio_sleep
)
from os import getpid
from subprocess import Popen
from unittest.mock import Mock, patch

import pytest
import test_framework.util as tf_util

from asynctest.mock import CoroutineMock
from test_framework.test_node import TestNode as FakeNode

from experiments.utils.latencies import LatencyPolicy
from experiments.utils.networking import get_pid_for_local_port
from experiments.utils.nodes_hub import NodesHub, NUM_OUTBOUND_CONNECTIONS


def test_get_port_methods():
    init_environment()

    nodes_hub = NodesHub(
        loop=Mock(spec=AbstractEventLoop),
        latency_policy=Mock(spec=LatencyPolicy),
        nodes=[get_node_mock(node_id) for node_id in range(20)]
    )

    used_ports = set()
    for node_id in range(20):
        node_port = nodes_hub.get_node_port(node_id)
        proxy_port = nodes_hub.get_proxy_port(node_id)

        # We assert port uniqueness
        assert(node_port not in used_ports)
        used_ports.add(node_port)
        assert(proxy_port not in used_ports)
        used_ports.add(proxy_port)


@pytest.mark.asyncio
async def test_start_proxies(event_loop: AbstractEventLoop):
    init_environment()

    nodes_hub = NodesHub(
        loop=event_loop,
        latency_policy=Mock(spec=LatencyPolicy),
        nodes=[get_node_mock(node_id) for node_id in range(5)]
    )
    await nodes_hub.start_proxies()  # System Under Test

    # We have 5 proxy instances as expected
    assert (len(nodes_hub.proxy_servers) == 5)
    for proxy_server in nodes_hub.proxy_servers:
        assert isinstance(proxy_server, AbstractServer)

    test_pid = getpid()

    # The proxy instances are listening as expected
    for node_id in range(5):
        assert (test_pid == get_pid_for_local_port(
            port=nodes_hub.get_proxy_port(node_id),
            status='LISTEN'
        ))

    nodes_hub.close()


@pytest.mark.asyncio
async def test_wait_for_pending_connections(event_loop: AbstractEventLoop):
    init_environment()

    async def fake_sleep(_delay):
        await asyncio_sleep(0)

    with patch(
        target='experiments.utils.nodes_hub.asyncio_sleep',
        new=fake_sleep  # We avoid sleeping, but need to switch context
    ), patch(
        target='experiments.utils.nodes_hub.NodesHub.connect_sender_to_proxy',
        new=CoroutineMock(spec=NodesHub.connect_sender_to_proxy)
    ):
        nodes_hub = NodesHub(
            loop=event_loop,
            latency_policy=Mock(spec=LatencyPolicy),
            nodes=[get_node_mock(node_id) for node_id in range(5)]
        )
        # nodes_hub.connect_sender_to_proxy = fake_connect_sender_to_proxy

        # 1st: Blocked because we still have to try establishing connections
        wait_task = event_loop.create_task(
            nodes_hub.wait_for_pending_connections()  # SUT
        )
        await asyncio_sleep(0)  # Switching context
        assert (not wait_task.done())
        nodes_hub.num_connection_intents = 5 * NUM_OUTBOUND_CONNECTIONS
        await asyncio_sleep(0)  # Switching context
        assert (wait_task.done())

        # 2nd: Blocked because we tried to connect, and we're waiting for results
        nodes_hub.pending_connections = {(0, 1), (1, 2), (2, 3)}
        wait_task = event_loop.create_task(
            nodes_hub.wait_for_pending_connections()  # SUT
        )
        await asyncio_sleep(0)  # Switching context
        assert (not wait_task.done())
        nodes_hub.pending_connections = set()
        for _ in range(10):
            await asyncio_sleep(0)  # Switching context
        assert (wait_task.done())

        nodes_hub.close()


@pytest.mark.asyncio
async def test_biconnect_nodes_as_linked_list(event_loop: AbstractEventLoop):
    init_environment()

    with patch(
        target='experiments.utils.nodes_hub.NodesHub.connect_nodes',
        new=CoroutineMock(spec=NodesHub.connect_nodes)
    ) as fake_connect_nodes, patch(
        target='experiments.utils.nodes_hub.NodesHub.wait_for_pending_connections',
        new=CoroutineMock(spec=NodesHub.wait_for_pending_connections)
    ) as fake_wait_for_pending_connections:
        nodes_hub = NodesHub(
            loop=event_loop,
            latency_policy=Mock(spec=LatencyPolicy),
            nodes=[get_node_mock(node_id) for node_id in range(5)]
        )
        await nodes_hub.biconnect_nodes_as_linked_list()  # SUT

        # 5 nodes as a list give us 4 edges, with 2 directions => 8 calls
        assert (8 == fake_connect_nodes.await_count)

        # We assert that we try to wait for pending connections
        fake_wait_for_pending_connections.assert_awaited()

        nodes_hub.close()


@pytest.mark.asyncio
async def test_connect_nodes_graph(event_loop: AbstractEventLoop):
    init_environment()

    graph_edges = {(0, 1), (1, 3), (3, 4), (4, 0)}

    with patch(
            target='experiments.utils.nodes_hub.NodesHub.connect_nodes',
            new=CoroutineMock(spec=NodesHub.connect_nodes)
    ) as fake_connect_nodes, patch(
        target='experiments.utils.nodes_hub.NodesHub.wait_for_pending_connections',
        new=CoroutineMock(spec=NodesHub.wait_for_pending_connections)
    ) as fake_wait_for_pending_connections:
        nodes_hub = NodesHub(
            loop=event_loop,
            latency_policy=Mock(spec=LatencyPolicy),
            nodes=[get_node_mock(node_id) for node_id in range(5)]
        )
        await nodes_hub.connect_nodes_graph(graph_edges)  # SUT

        # We call connect_nodes 1 time per graph edge
        assert (4 == fake_connect_nodes.await_count)

        # We assert that we try to wait for pending connections
        fake_wait_for_pending_connections.assert_awaited()

        nodes_hub.close()


def init_environment():
    # Sadly, we have to touch this almost-global properties to make things work
    tf_util.MAX_NODES = 500
    tf_util.PortSeed.n = 314159


def get_node_mock(node_id: int) -> Mock:
    test_node = Mock(spec=FakeNode)
    test_node.process = Mock(spec=Popen)
    test_node.process.pid = node_id + 1000

    return test_node
