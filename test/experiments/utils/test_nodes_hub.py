from asyncio import AbstractEventLoop, AbstractServer
from os import getpid
from subprocess import Popen
from unittest.mock import Mock

import pytest

import test_framework.util as tf_util

from test_framework.test_node import TestNode as FakeNode

from experiments.utils.latencies import LatencyPolicy
from experiments.utils.networking import get_pid_for_local_port
from experiments.utils.nodes_hub import NodesHub


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
async def test_start_proxies(event_loop):
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


def init_environment():
    # Sadly, we have to touch this almost-global properties to make things work
    tf_util.MAX_NODES = 500
    tf_util.PortSeed.n = 314159


def get_node_mock(node_id: int) -> Mock:
    test_node = Mock(spec=FakeNode)
    test_node.process = Mock(spec=Popen)
    test_node.process.pid = node_id + 1000

    return test_node
