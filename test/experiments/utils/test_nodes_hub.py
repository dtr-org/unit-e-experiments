from asyncio import AbstractEventLoop
from subprocess import Popen
from unittest.mock import Mock

import test_framework.util as tf_util

from test_framework.test_node import TestNode

from experiments.utils.nodes_hub import NodesHub
from experiments.utils.latencies import LatencyPolicy


def test_get_port_methods():
    # Sadly, we have to touch this almost-global properties to make things work
    tf_util.MAX_NODES = 500
    tf_util.PortSeed.n = 314159

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


def get_node_mock(node_id: int) -> Mock:
    test_node = Mock(spec=TestNode)
    test_node.process = Mock(spec=Popen)
    test_node.process.pid = node_id + 1000

    return test_node
