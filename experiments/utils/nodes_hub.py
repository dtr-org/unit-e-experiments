#!/usr/bin/env python3

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from asyncio import (
    AbstractEventLoop,
    Protocol,
    AbstractServer,
    Task,
    Transport,
    gather,
    sleep as asyncio_sleep
)
from logging import getLogger
from struct import pack, unpack
from typing import (
    Dict,
    List,
    Optional,
    Tuple
)

from test_framework.messages import hash256
from test_framework.test_node import TestNode
from test_framework.util import p2p_port


MSG_HEADER_LENGTH = 4 + 12 + 4 + 4
VERSION_PORT_OFFSET = 4 + 8 + 8 + 26 + 8 + 16


logger = getLogger('TestFramework.nodes_hub')


class NodesHub:
    """
    A central hub to connect all the nodes at test/simulation time. It has many
    purposes:
      - Give us the ability to capture & analyze traffic
      - Give us the ability to add arbitrary delays/latencies between any node

    The hub will open many ports at the same time to handle inbound connections,
    one for each node. When a node A wants to send a message to node B, the
    message will travel through the hub (H hereinafter). So, if A wants to be
    connected to B and C, it will establish two connections to H (every open
    port of H will represent a specific node), and H will establish one new
    connection to B, and another one to C.

    In this class, we refer to the nodes through their index in the self.nodes
    property.
    """

    def __init__(
            self,
            loop: AbstractEventLoop,
            nodes: List[TestNode],
            host: str = '127.0.0.1'
    ):
        self.loop = loop
        self.nodes = nodes

        self.host = host

        # This allows us to specify asymmetric delays
        self.node2node_delays: Dict[Tuple[int, int], float] = {}
        self.inbound_delays: Dict[int, float] = {}

        self.proxy_servers: List[AbstractServer] = []
        self.relay_tasks: Dict[Tuple[int, int], Task] = {}
        self.ports2nodes_map: Dict[int, int] = {}

        # Lock-like object used by NodesHub.connect_nodes
        self.pending_connection: Optional[Tuple[int, int]] = None

    def sync_start_proxies(self):
        """
        This method creates (& starts) a listener proxy for each node, the
        connections from each proxy to the real node that they represent will be
        done whenever a node connects to the proxy.

        It starts the nodes's proxies.
        """
        for node_id in range(len(self.nodes)):
            self.ports2nodes_map[self.get_node_port(node_id)] = node_id
            self.ports2nodes_map[self.get_proxy_port(node_id)] = node_id

        self.proxy_servers = self.loop.run_until_complete(gather(*[
            self.loop.create_server(
                protocol_factory=lambda: ProxyInputConnection(
                    hub_ref=self, node_id=node_id
                ),
                host=self.host,
                port=self.get_proxy_port(node_id)
            )
            for node_id, node in enumerate(self.nodes)
        ]))

    def sync_biconnect_nodes_as_linked_list(self, nodes_list=None):
        """
        Helper to make easier using NodesHub in non-asyncio aware code.
        Connects nodes as a linked list.
        """
        if nodes_list is None:
            nodes_list = range(len(self.nodes))

        if 0 == len(nodes_list):
            return

        connection_futures = []

        for i, j in zip(nodes_list, nodes_list[1:]):
            connection_futures.append(self.connect_nodes(i, j))
            connection_futures.append(self.connect_nodes(j, i))

        self.loop.run_until_complete(gather(*connection_futures))

    def sync_connect_nodes(self, graph_edges: set):
        """
        Helper to make easier using NodesHub in non-asyncio aware code. Allows
        to setup a network given an arbitrary graph (in the form of edges set).
        """
        self.loop.run_until_complete(
            gather(*[self.connect_nodes(i, j) for (i, j) in graph_edges])
        )

    def close(self):
        for server in self.proxy_servers:
            server.close()

    @staticmethod
    def get_node_port(node_idx):
        return p2p_port(node_idx)

    def get_proxy_port(self, node_idx):
        return p2p_port(len(self.nodes) + 1 + node_idx)

    def get_proxy_address(self, node_idx):
        return '%s:%s' % (self.host, self.get_proxy_port(node_idx))

    def set_nodes_delay(self, outbound_idx: int, inbound_idx: int, delay: float):
        if delay == 0:
            self.node2node_delays.pop((outbound_idx, inbound_idx), None)
        else:
            self.node2node_delays[(outbound_idx, inbound_idx)] = delay

    def set_inbound_delay(self, inbound_idx: int, delay: float):
        if delay == 0:
            self.inbound_delays.pop(inbound_idx, None)
        else:
            self.inbound_delays[inbound_idx] = delay

    async def connect_nodes(self, outbound_idx: int, inbound_idx: int):
        """
        :param outbound_idx: Refers the "sender" (asking for a new connection)
        :param inbound_idx: Refers the "receiver" (listening for new connections)
        """

        # We have to wait until all the proxies are configured and listening
        while len(self.proxy_servers) < len(self.nodes):
            await asyncio_sleep(0)

        # We have to be sure that all the previous calls to connect_nodes have
        # finished. Because we are using cooperative scheduling we don't have to
        # worry about race conditions, this while loop is enough.
        while self.pending_connection is not None:
            await asyncio_sleep(0)

        # We acquire the lock. This tuple is also useful for the NodeProxy
        # instance.
        self.pending_connection = (outbound_idx, inbound_idx)
        self.connect_sender_to_proxy(*self.pending_connection)

        # We wait until we know that all the connections have been created
        while self.pending_connection is not None:
            await asyncio_sleep(0)

    def connect_sender_to_proxy(self, outbound_idx, inbound_idx):
        """
        Establishes a connection between a real node and the proxy representing
        another node
        """
        sender_node = self.nodes[outbound_idx]
        proxy_address = self.get_proxy_address(inbound_idx)

        # Add the proxy to the outgoing connections list
        sender_node.addnode(proxy_address, 'add')
        # Connect to proxy. Will trigger ProxyInputConnection.connection_made
        sender_node.addnode(proxy_address, 'onetry')

    def process_buffer(self, buffer, transport: Transport):
        """
        This function helps the hub to impersonate nodes by modifying 'version'
        messages changing the "from" addresses.
        """

        # We do nothing until we have (magic + command + length + checksum)
        while len(buffer) > MSG_HEADER_LENGTH:

            # We only care about command & msglen
            msglen = unpack("<i", buffer[4 + 12:4 + 12 + 4])[0]

            # We wait until we have the full message
            if len(buffer) < MSG_HEADER_LENGTH + msglen:
                return

            command = buffer[4:4 + 12].split(b'\x00', 1)[0]
            logger.debug('Processing command %s' % str(command))

            if b'version' == command:
                msg = buffer[MSG_HEADER_LENGTH:MSG_HEADER_LENGTH + msglen]

                node_port: int = unpack(
                    '!H', msg[VERSION_PORT_OFFSET:VERSION_PORT_OFFSET + 2]
                )[0]
                if node_port != 0:
                    proxy_port = self.get_proxy_port(self.ports2nodes_map[node_port])
                else:
                    proxy_port = 0  # The node is not listening for connections

                msg = (
                    msg[:VERSION_PORT_OFFSET] +
                    pack('!H', proxy_port) +
                    msg[VERSION_PORT_OFFSET + 2:]
                )

                msg_checksum = hash256(msg)[:4]  # Truncated double sha256
                new_header = buffer[:MSG_HEADER_LENGTH - 4] + msg_checksum

                transport.write(new_header + msg)
            else:
                # We pass an unaltered message
                transport.write(buffer[:MSG_HEADER_LENGTH + msglen])

            buffer = buffer[MSG_HEADER_LENGTH + msglen:]

        return buffer


class ProxyInputConnection(Protocol):
    def __init__(self, hub_ref: NodesHub, node_id: int):
        self.hub_ref = hub_ref
        self.receiver_id = node_id

        self.sender_id: Optional[int] = None

        self.transport: Optional[Transport] = None
        self.output_connection: Optional[ProxyOutputConnection] = None

        self.recvbuf = b''

    def connection_made(self, transport):
        if self.hub_ref.pending_connection is not None:
            self.sender_id = self.hub_ref.pending_connection[0]

        self.transport = transport

        self.transport.pause_reading()
        self.pause_writing()

        proxy_output_coroutine = self.hub_ref.loop.create_connection(
            protocol_factory=lambda: ProxyOutputConnection(
                input_connection=self
            ),
            host=self.hub_ref.host,
            port=self.hub_ref.get_node_port(self.receiver_id)
        )
        self.hub_ref.loop.create_task(proxy_output_coroutine)

        logger.debug(f'''Created proxy input connection {(
            self.sender_id,
            self.receiver_id
        )}''')

    def connection_lost(self, exc):
        if not self.transport.is_closing():
            self.transport.close()
        if not self.output_connection.transport.is_closing():
            self.output_connection.transport.close()

        logger.debug(f'''Lost proxy input connection {(
            self.sender_id,
            self.receiver_id
        )}''')

    def data_received(self, data):
        self.hub_ref.loop.create_task(self.__handle_received_data(data))

    async def __handle_received_data(self, data):
        while (
            self.output_connection is None or
            self.output_connection.transport is None
        ):  # This should not happen, just defensive programming
            await asyncio_sleep(0)

        if (
            self.sender_id is not None and
            (self.sender_id, self.receiver_id) in self.hub_ref.node2node_delays
        ):
            await asyncio_sleep(
                self.hub_ref.node2node_delays[(self.sender_id, self.receiver_id)]
            )
        elif self.receiver_id in self.hub_ref.inbound_delays:
            await asyncio_sleep(self.hub_ref.inbound_delays[self.receiver_id])

        if len(data) > 0:
            logger.debug(
                f'Proxy input connection {(self.sender_id, self.receiver_id)} '
                f'received {len(data)} bytes'
            )
            self.recvbuf += data
            self.recvbuf = self.hub_ref.process_buffer(
                buffer=self.recvbuf,
                transport=self.output_connection.transport
            )


class ProxyOutputConnection(Protocol):
    def __init__(self, input_connection: ProxyInputConnection):
        self.input_connection = input_connection
        self.hub_ref = input_connection.hub_ref
        self.transport: Optional[Transport] = None

        self.recvbuf = b''
        input_connection.output_connection = self

    def connection_made(self, transport):
        self.transport = transport

        self.input_connection.transport.resume_reading()
        self.input_connection.resume_writing()
        self.hub_ref.pending_connection = None  # We release the lock

        logger.debug(f'''Created proxy output connection {(
            self.input_connection.sender_id,
            self.input_connection.receiver_id
        )}''')

    def connection_lost(self, exc):
        if not self.transport.is_closing():
            self.transport.close()
        if not self.input_connection.transport.is_closing():
            self.input_connection.transport.close()

        logger.debug(f'''Lost proxy output connection {(
            self.input_connection.sender_id,
            self.input_connection.receiver_id
        )}''')

    def data_received(self, data):
        self.hub_ref.loop.create_task(self.__handle_received_data(data))

    async def __handle_received_data(self, data):
        receiver2sender_pair = (
            self.input_connection.receiver_id, self.input_connection.sender_id
        )

        # if self.receiver2sender_pair in self.hub_ref.node2node_delays:
        if (
            self.input_connection.sender_id is not None and
            receiver2sender_pair in self.hub_ref.node2node_delays
        ):
            await asyncio_sleep(
                self.hub_ref.node2node_delays[receiver2sender_pair]
            )
        elif self.input_connection.sender_id in self.hub_ref.inbound_delays:
            await asyncio_sleep(
                self.hub_ref.inbound_delays[self.input_connection.sender_id]
            )

        if len(data) > 0:
            logger.debug(
                f'Proxy output connection {receiver2sender_pair[::-1]} '
                f'received {len(data)} bytes'
            )
            self.recvbuf += data
            self.recvbuf = self.hub_ref.process_buffer(
                buffer=self.recvbuf,
                transport=self.input_connection.transport
            )
