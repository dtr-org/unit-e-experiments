#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from asyncio import (
    AbstractEventLoop,
    AbstractServer,
    sleep as asyncio_sleep,
    Transport)
from logging import Logger
from os import getpid
from struct import pack
from subprocess import Popen
from unittest.mock import Mock, patch

import pytest
import test_framework.util as tf_util

from asynctest.mock import CoroutineMock
from test_framework.test_node import TestNode as FakeNode

from network.latencies import LatencyPolicy
from network.utils import get_pid_for_network_server
from network.stats import NetworkStatsCollector
from network.nodes_hub import (
    NodesHub,
    NUM_OUTBOUND_CONNECTIONS,
    ProxyInputConnection,
    ProxyOutputConnection
)


def test_get_port_methods():
    init_environment()

    nodes_hub = NodesHub(
        loop=Mock(spec=AbstractEventLoop),
        latency_policy=Mock(spec=LatencyPolicy),
        nodes=[get_node_mock(node_id) for node_id in range(20)],
        network_stats_collector=Mock(spec=NetworkStatsCollector)
    )

    used_ports = set()
    for node_id in range(20):
        node_port = nodes_hub.get_p2p_node_port(node_id)
        proxy_port = nodes_hub.get_p2p_proxy_port(node_id)

        # We assert port uniqueness
        assert(node_port not in used_ports)
        used_ports.add(node_port)
        assert(proxy_port not in used_ports)
        used_ports.add(proxy_port)


def test_register_p2p_command():
    init_environment()

    network_stats_collector_mock = Mock(spec=NetworkStatsCollector)

    nodes_hub = NodesHub(
        loop=Mock(spec=AbstractEventLoop),
        latency_policy=Mock(spec=LatencyPolicy),
        nodes=[get_node_mock(node_id) for node_id in range(5)],
        network_stats_collector=network_stats_collector_mock
    )

    # With ProxyInputConnection
    proxy_input_connection_mock = Mock(spec=ProxyInputConnection)
    proxy_input_connection_mock.sender_id = 42
    proxy_input_connection_mock.receiver_id = 3
    nodes_hub.register_p2p_command(
        command=b'version',
        connection=proxy_input_connection_mock,
        msglen=65
    )
    network_stats_collector_mock.register_event.assert_called_once_with(
        command_name='version',
        command_size=65,
        src_node_id=42,
        dst_node_id=3
    )

    # With ProxyOutputConnection
    proxy_output_connection_mock = Mock(spec=ProxyOutputConnection)
    proxy_output_connection_mock.input_connection = proxy_input_connection_mock
    nodes_hub.register_p2p_command(
        command=b'version',
        connection=proxy_output_connection_mock,
        msglen=65
    )
    network_stats_collector_mock.register_event.assert_called_with(
        command_name='version',
        command_size=65,
        src_node_id=3,
        dst_node_id=42
    )

    # With invalid connection type
    with pytest.raises(expected_exception=ValueError):
        nodes_hub.register_p2p_command(
            command=b'version', connection=None, msglen=65
        )

    # With missing node IDs
    with patch(
        target='network.nodes_hub.logger',
        spec=Logger
    ) as logger_mock:
        # Missing sender ID
        proxy_input_connection_mock.sender_id = None
        nodes_hub.register_p2p_command(
            command=b'version',
            connection=proxy_input_connection_mock,
            msglen=65
        )
        logger_mock.warning.assert_called_once_with(
            'Register b\'version\' command for unknown sender'
        )

        # Missing receiver ID
        proxy_input_connection_mock.sender_id = 42
        proxy_input_connection_mock.receiver_id = None
        nodes_hub.register_p2p_command(
            command=b'version',
            connection=proxy_input_connection_mock,
            msglen=65
        )
        logger_mock.warning.assert_called_with(
            'Register b\'version\' command for unknown receiver'
        )


def test_process_buffer():
    init_environment()

    with patch(
        target='network.nodes_hub.NodesHub.register_p2p_command',
        new=CoroutineMock(spec=NodesHub.register_p2p_command)
    ):
        nodes_hub = NodesHub(
            loop=Mock(spec=AbstractEventLoop),
            latency_policy=Mock(spec=LatencyPolicy),
            nodes=[get_node_mock(node_id) for node_id in range(5)],
            network_stats_collector=Mock(spec=NetworkStatsCollector)
        )

        connection_mock = Mock(spec=Transport)
        connection_mock.id = 1234

        # Incomplete messages are not processed, the buffer remains untouched
        assert (b'0123456789' == nodes_hub.process_buffer(
            buffer=b'0123456789',  # Shorter than MSG_HEADER_LENGTH
            transport=Mock(spec=Transport),
            connection=connection_mock
        ))

        # Processing 'verack' message
        buffer = (
            b'\x00\x00\x00\x00verack\x00\x00\x00\x00\x00\x00' +
            pack('<i', 0)[:4] +  # Msg length (without the header)
            b'\x5d\xf6\xe0\xe2'  # Msg checksum
            b'123456'            # A little bit of noise
        )
        processed_buffer = nodes_hub.process_buffer(
            buffer=buffer,
            transport=Mock(spec=Transport),
            connection=connection_mock
        )
        # The message is consumed, the next incomplete message remains unprocessed
        assert (b'123456' == processed_buffer)

        # Processing 'version' message
        buffer = (
            # Message Header
            b'\xfa\xbf\xb5\xda'             # Network-type
            b'version\x00\x00\x00\x00\x00'  # Command-type
            b't\x00\x00\x00'                # Msg length (without the header)
            b'\x1c\x1d\xce\xb0'             # Msg checksum
            # Message Body
            b'\x7f\x11\x01\x00\r\x84\x00\x00\x00\x00\x00\x00\xfcQa\\\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\r\x84\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            b'\x00\x00\x00\x00\x00\x00Nz:+\x86\xbb\xef\xe4\x1e'
            b'/Feuerland:0.16.3(testnode25)/\x00\x00\x00\x00\x01'
        )
        transport_mock = Mock(spec=Transport)
        processed_buffer = nodes_hub.process_buffer(
            buffer=buffer,
            transport=transport_mock,
            connection=connection_mock
        )
        assert (b'' == processed_buffer)
        # The node is not listening connections, so it specifies port 0, hence we
        # we pass the original message without any changes.
        transport_mock.write.assert_called_once_with(buffer)


@pytest.mark.asyncio
async def test_start_proxies(event_loop: AbstractEventLoop):
    init_environment()

    nodes_hub = NodesHub(
        loop=event_loop,
        latency_policy=Mock(spec=LatencyPolicy),
        nodes=[get_node_mock(node_id) for node_id in range(5)],
        network_stats_collector=Mock(spec=NetworkStatsCollector)
    )
    await nodes_hub.start_proxies()  # System Under Test

    # We have 5 proxy instances as expected
    assert (len(nodes_hub.proxy_servers) == 5)
    for proxy_server in nodes_hub.proxy_servers:
        assert isinstance(proxy_server, AbstractServer)

    test_pid = getpid()

    # The proxy instances are listening as expected
    for node_id in range(5):
        assert (test_pid == get_pid_for_network_server(
            server_port=nodes_hub.get_p2p_proxy_port(node_id),
        ))

    nodes_hub.close()


@pytest.mark.asyncio
async def test_wait_for_pending_connections(event_loop: AbstractEventLoop):
    init_environment()

    async def fake_sleep(_delay):
        await asyncio_sleep(0)

    with patch(
        target='network.nodes_hub.asyncio_sleep',
        new=fake_sleep  # We avoid sleeping, but need to switch context
    ), patch(
        target='network.nodes_hub.NodesHub.connect_sender_to_proxy',
        new=CoroutineMock(spec=NodesHub.connect_sender_to_proxy)
    ):
        nodes_hub = NodesHub(
            loop=event_loop,
            latency_policy=Mock(spec=LatencyPolicy),
            nodes=[get_node_mock(node_id) for node_id in range(5)],
            network_stats_collector=Mock(spec=NetworkStatsCollector)
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
        target='network.nodes_hub.NodesHub.connect_nodes',
        new=CoroutineMock(spec=NodesHub.connect_nodes)
    ) as fake_connect_nodes, patch(
        target='network.nodes_hub.NodesHub.wait_for_pending_connections',
        new=CoroutineMock(spec=NodesHub.wait_for_pending_connections)
    ) as fake_wait_for_pending_connections:
        nodes_hub = NodesHub(
            loop=event_loop,
            latency_policy=Mock(spec=LatencyPolicy),
            nodes=[get_node_mock(node_id) for node_id in range(5)],
            network_stats_collector=Mock(spec=NetworkStatsCollector)
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
            target='network.nodes_hub.NodesHub.connect_nodes',
            new=CoroutineMock(spec=NodesHub.connect_nodes)
    ) as fake_connect_nodes, patch(
        target='network.nodes_hub.NodesHub.wait_for_pending_connections',
        new=CoroutineMock(spec=NodesHub.wait_for_pending_connections)
    ) as fake_wait_for_pending_connections:
        nodes_hub = NodesHub(
            loop=event_loop,
            latency_policy=Mock(spec=LatencyPolicy),
            nodes=[get_node_mock(node_id) for node_id in range(5)],
            network_stats_collector=Mock(spec=NetworkStatsCollector)
        )
        await nodes_hub.connect_nodes_graph(graph_edges)  # SUT

        # We call connect_nodes 1 time per graph edge
        assert (4 == fake_connect_nodes.await_count)

        # We assert that we try to wait for pending connections
        fake_wait_for_pending_connections.assert_awaited()

        nodes_hub.close()


# ------------------------------------------------------------------------------
# Helper functions:
# ------------------------------------------------------------------------------


def init_environment():
    # Sadly, we have to touch this almost-global properties to make things work
    tf_util.MAX_NODES = 500
    tf_util.PortSeed.n = 314159


def get_node_mock(node_id: int) -> Mock:
    test_node = Mock(spec=FakeNode)
    test_node.process = Mock(spec=Popen)
    test_node.process.pid = node_id + 1000

    return test_node
