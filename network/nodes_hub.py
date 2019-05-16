#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from asyncio import (
    AbstractEventLoop,
    AbstractServer,
    Protocol,
    Transport,
    WriteTransport,
    gather,
    sleep as asyncio_sleep
)
from logging import getLogger
from socket import socket as socket_cls
from struct import pack, unpack
from typing import (
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union
)

from network.latencies import LatencyPolicy
from network.utils import get_pid_for_network_client
from network.stats import NetworkStatsCollector
from test_framework.messages import hash256
from test_framework.test_node import TestNode
from test_framework.util import (
    p2p_port,
    rpc_port
)

NUM_OUTBOUND_CONNECTIONS = 8
NUM_INBOUND_CONNECTIONS = 125

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
            latency_policy: LatencyPolicy,
            nodes: List[TestNode],
            network_stats_collector: NetworkStatsCollector,
            host: str = '127.0.0.1'
    ):
        self.loop = loop
        self.latency_policy = latency_policy
        self.nodes = nodes
        self.pid2node_id: Dict[int, int] = {
            node.process.pid: node_id for node_id, node in enumerate(self.nodes)
            # Could be that some nodes are not started
            if node.process is not None
        }

        self.host = host

        self.proxy_servers: List[AbstractServer] = []
        self.ports2nodes_map: Dict[int, int] = {}

        self.pending_connections: Set[Tuple[int, int]] = set()
        self.state = 'constructed'

        self.num_connection_intents = 0
        self.num_unexpected_connections = 0
        self.tried_connections: Set[Tuple[int, int]] = set()

        self.network_stats_collector = network_stats_collector

    def sync_start_proxies(self, node_ids: Optional[List[int]] = None):
        """Sync wrapper around start_proxies"""
        self.loop.run_until_complete(self.start_proxies(node_ids))

    async def start_proxies(self, node_ids: Optional[List[int]] = None):
        """
        This method creates (& starts) a listener proxy for each node, the
        connections from each proxy to the real node that they represent will be
        done whenever a node connects to the proxy.

        It starts the nodes's proxies.
        """

        if node_ids is None:
            node_ids = list(range(len(self.nodes)))

        for node_id in node_ids:
            self.ports2nodes_map[self.get_p2p_node_port(node_id)] = node_id
            self.ports2nodes_map[self.get_p2p_proxy_port(node_id)] = node_id

        self.proxy_servers = await gather(*[
            self.loop.create_server(
                protocol_factory=ProxyInputConnection.deferred_constructor(
                    hub_ref=self, node_id=node_id
                ),
                host=self.host,
                port=self.get_p2p_proxy_port(node_id)
            )
            for node_id in node_ids
        ])

        self.state = 'started_proxies'

    def sync_biconnect_nodes_as_linked_list(self, nodes_list=None):
        """Sync wrapper around biconnect_nodes_as_linked_list"""
        self.loop.run_until_complete(self.biconnect_nodes_as_linked_list(
            nodes_list
        ))

    async def biconnect_nodes_as_linked_list(self, nodes_list=None):
        """Connects nodes as a linked list."""
        if nodes_list is None:
            nodes_list = range(len(self.nodes))

        if 0 == len(nodes_list):
            return

        connection_futures = [self.wait_for_pending_connections()]

        for i, j in zip(nodes_list, nodes_list[1:]):
            connection_futures.append(self.connect_nodes(i, j))
            connection_futures.append(self.connect_nodes(j, i))

        await gather(*connection_futures)

    def sync_connect_nodes_graph(self, graph_edges: set):
        """Sync wrapper around connect_nodes_graph"""
        self.loop.run_until_complete(self.connect_nodes_graph(graph_edges))

    async def connect_nodes_graph(self, graph_edges: set):
        """
        Allows to setup a network given an arbitrary graph (in the form of edges
        set).
        """
        num_proxies = len(
            {i for i, _ in graph_edges}.union({j for _, j in graph_edges})
        )

        await gather(*(
            [
                self.connect_nodes(i, j, num_expected_proxies=num_proxies)
                for (i, j) in graph_edges
            ] +
            [self.wait_for_pending_connections(len(graph_edges))]
        ))

    def close(self):
        if self.state in ['closing', 'closed']:
            return
        self.state = 'closing'
        logger.info('Shutting down NodesHub instance')

        for node in self.nodes:
            node.disconnect_p2ps()

        self.network_stats_collector.close()

        for server in self.proxy_servers:
            server.close()
            if server.sockets is not None:
                for socket in server.sockets:
                    socket.close()
        self.proxy_servers = []  # Remove references

        self.state = 'closed'

    @staticmethod
    def get_rpc_node_port(node_idx):
        return rpc_port(node_idx)

    @staticmethod
    def get_p2p_node_port(node_idx):
        return p2p_port(node_idx)

    def get_p2p_proxy_port(self, node_idx):
        return p2p_port(len(self.nodes) + 1 + node_idx)

    def get_proxy_address(self, node_idx):
        return f'{self.host}:{self.get_p2p_proxy_port(node_idx)}'

    async def connect_nodes(
        self,
        outbound_idx: int,
        inbound_idx: int,
        num_expected_proxies: Optional[int] = None
    ):
        """
        :param outbound_idx: Refers the "sender" (asking for a new connection)
        :param inbound_idx: Refers the "receiver" (listening for new connections)
        :param num_expected_proxies: Only for corner-case usages
        """

        if num_expected_proxies is None:
            num_expected_proxies = len(self.nodes)

        # We have to wait until all the proxies are configured and listening
        while len(self.proxy_servers) < num_expected_proxies:
            await asyncio_sleep(0)

        await self.connect_sender_to_proxy(outbound_idx, inbound_idx)

    async def connect_sender_to_proxy(
            self, outbound_idx: int, inbound_idx: int, retry: bool = False
    ):
        """
        Establishes a connection between a real node and the proxy representing
        another node
        """

        sender_node = self.nodes[outbound_idx]
        proxy_address = self.get_proxy_address(inbound_idx)
        retry = retry or (outbound_idx, inbound_idx) in self.tried_connections

        # self.pending_connections is used as a sort of semaphore
        if not retry:
            self.pending_connections.add((outbound_idx, inbound_idx))
            # Add the proxy to the outgoing connections list
            try:
                sender_node.addnode(proxy_address, 'add')
                self.num_connection_intents += 1
            except BaseException as e:
                if str(e) == 'Error: Node already added (-23)':
                    pass
                else:
                    raise e
            finally:
                self.tried_connections.add((outbound_idx, inbound_idx))

        # Connect to proxy. Will trigger ProxyInputConnection.connection_made
        sender_node.addnode(proxy_address, 'onetry')

    async def wait_for_pending_connections(
        self,
        num_expected_connections: Optional[int] = None
    ):
        if num_expected_connections is None:
            num_expected_connections = len(self.nodes) * NUM_OUTBOUND_CONNECTIONS

        # The first time we give some margin to the other coroutines so they can
        # start adding pending connections.
        while self.num_connection_intents < num_expected_connections:
            await asyncio_sleep(0.005)

        # We wait until we know that all the connections have been created
        while len(self.pending_connections) - self.num_unexpected_connections > 0:
            logger.debug(
                'Remaining connections to be fully established: '
                f'{len(self.pending_connections)} '
            )

            # We retry becase the 'onetry' RPC call not always succeed
            for outbound_idx, inbound_idx in self.pending_connections:
                await self.connect_sender_to_proxy(
                    outbound_idx, inbound_idx, retry=True
                )

            await asyncio_sleep(0.005)

        if self.num_unexpected_connections > 0:
            logger.warning(
                'Some unexpected connections were established '
                f'({self.num_unexpected_connections})'
            )
        if self.num_unexpected_connections - len(self.pending_connections) > 0:
            logger.warning('The simulated network is bigger than intended')

        logger.info('All pending connections have been established')

    def process_buffer(
            self,
            buffer: bytes,
            transport: WriteTransport,
            connection: Union['ProxyInputConnection', 'ProxyOutputConnection']
    ) -> bytes:
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
                return buffer

            command = buffer[4:4 + 12].split(b'\x00', 1)[0]
            logger.debug(
                f'{connection.__class__.__name__} {connection.id}: '
                f'Processing command {str(command)}'
            )

            self.register_p2p_command(command, connection, MSG_HEADER_LENGTH + msglen)

            if b'version' == command:
                msg = buffer[MSG_HEADER_LENGTH:MSG_HEADER_LENGTH + msglen]

                node_port: int = unpack(
                    '!H', msg[VERSION_PORT_OFFSET:VERSION_PORT_OFFSET + 2]
                )[0]
                if node_port != 0:
                    proxy_port = self.get_p2p_proxy_port(
                        self.ports2nodes_map[node_port]
                    )
                    msg = (
                        msg[:VERSION_PORT_OFFSET] +
                        pack('!H', proxy_port) +
                        msg[VERSION_PORT_OFFSET + 2:]
                    )
                    msg_checksum = hash256(msg)[:4]  # Truncated double sha256
                    new_header = buffer[:MSG_HEADER_LENGTH - 4] + msg_checksum

                    transport.write(new_header + msg)
                else:
                    transport.write(buffer[:MSG_HEADER_LENGTH + msglen])
            else:
                # We pass an unaltered message
                transport.write(buffer[:MSG_HEADER_LENGTH + msglen])

            buffer = buffer[MSG_HEADER_LENGTH + msglen:]

        return buffer

    def register_p2p_command(
            self,
            command: bytes,
            connection: Union['ProxyInputConnection', 'ProxyOutputConnection'],
            msglen: int
    ):
        if isinstance(connection, ProxyInputConnection):
            src_node_id: Optional[int] = connection.sender_id
            dst_node_id: Optional[int] = connection.receiver_id
        elif isinstance(connection, ProxyOutputConnection):
            src_node_id = connection.input_connection.receiver_id
            dst_node_id = connection.input_connection.sender_id
        else:
            raise ValueError('Incorrect type for connection')

        if src_node_id is None:
            logger.warning(f'Register {command} command for unknown sender')
        if dst_node_id is None:
            logger.warning(f'Register {command} command for unknown receiver')

        self.network_stats_collector.register_event(
            command_name=command.decode(),
            command_size=msglen,
            src_node_id=src_node_id,
            dst_node_id=dst_node_id
        )


class ProxyInputConnection(Protocol):
    """
    Represents connections made from nodes to node's proxies
    """
    def __init__(self, hub_ref: NodesHub, node_id: int):
        self.hub_ref = hub_ref
        self.receiver_id = node_id

        self.sender_id: Optional[int] = None

        self.transport: Optional[Transport] = None
        self.output_connection: Optional[ProxyOutputConnection] = None

        self.recvbuf = b''

        # Debugging related properties:
        self.id = hex(id(self))
        self.received_data_before_init = False

        logger.debug(
            f'ProxyInputConnection {self.id}: __init__ (receiver_id={node_id})'
        )

    @classmethod
    def deferred_constructor(cls, hub_ref: NodesHub, node_id: int) -> Callable:
        """
        The lambda is declared here to ensure that we don't accidentally capture
        a fixed node_id for all the proxy listeners.
        """
        return lambda: cls(hub_ref, node_id)

    def connection_made(self, transport):

        try:
            transport_socket: socket_cls = transport._sock
            peer_port = transport_socket.getpeername()[1]
            server_port = transport_socket.getsockname()[1]
            assert server_port == self.hub_ref.get_p2p_proxy_port(self.receiver_id)

            peer_pid = get_pid_for_network_client(
                client_port=peer_port,
                server_port=server_port
            )
            self.sender_id = self.hub_ref.pid2node_id[peer_pid]

            # We wait until ProxyOutputConnection is created to remove pair from
            # self.nodes_hub.pending_connections
        except AttributeError:
            # If this happens (theoretically possible due to the fact that we
            # are accessing a "protected" property, we'll have to change how we
            # obtain the socket.
            logger.critical('Unable to obtain socket from transport')
            exit(-1)

        if self.transport is not None:
            logger.critical('ProxyInputConnection has been reused')
            exit(-1)

        self.transport: Transport = transport

        self.transport.pause_reading()
        self.pause_writing()

        self.hub_ref.loop.create_task(self.hub_ref.loop.create_connection(
            protocol_factory=lambda: ProxyOutputConnection(
                input_connection=self
            ),
            host=self.hub_ref.host,
            port=self.hub_ref.get_p2p_node_port(self.receiver_id)
        ))

        logger.debug(f'''ProxyInputConnection {self.id}: connection_made {(
            self.sender_id,
            self.receiver_id
        )}''')

    def connection_lost(self, exc):
        if self.transport is not None:
            if not self.transport.is_closing():
                self.transport.close()
            if (
                    self.output_connection is not None and
                    self.output_connection.transport is not None and
                    not self.output_connection.transport.is_closing()
            ):
                self.output_connection.transport.close()
        else:
            logger.warning(
                f'ProxyInputConnection {self.id}: connection_lost (too early)'
            )

        logger.debug(f'''ProxyInputConnection {self.id}: connection_lost {(
            self.sender_id,
            self.receiver_id
        )}''')

    def data_received(self, data):
        self.hub_ref.loop.create_task(self.__handle_received_data(data))

    async def __handle_received_data(self, data):
        while (
            self.output_connection is None or
            self.output_connection.transport is None
        ):
            self.received_data_before_init = True
            if self.output_connection is None:
                logger.debug(
                    f'ProxyInputConnection {self.id}: Received data before '
                    'being able to handle it. (output_connection is None)'
                )
            else:
                logger.debug(
                    f'ProxyInputConnection {self.id}: Received data before '
                    'being able to handle it. (transport is None)'
                )
            await asyncio_sleep(0.0005)

        if self.received_data_before_init:
            logger.debug(
                f'ProxyInputConnection {self.id}: '
                'Initialized output_connection & transport'
            )
            self.received_data_before_init = False

        await asyncio_sleep(self.hub_ref.latency_policy.get_delay(
            self.sender_id, self.receiver_id
        ))

        if len(data) > 0:
            logger.debug(
                f'ProxyInputConnection {self.id}: {(self.sender_id, self.receiver_id)} '
                f'received {len(data)} bytes'
            )
            self.recvbuf += data
            self.recvbuf = self.hub_ref.process_buffer(
                buffer=self.recvbuf,
                transport=self.output_connection.transport,
                connection=self
            )


class ProxyOutputConnection(Protocol):
    """
    Represents connections made from proxies to the nodes they are representing,
    instances of this class are created when ProxyInputConnection's
    connection_made method is called.
    """

    def __init__(self, input_connection: ProxyInputConnection):
        self.input_connection = input_connection
        self.hub_ref = input_connection.hub_ref
        self.transport: Optional[Transport] = None

        self.recvbuf = b''
        input_connection.output_connection = self

        # Debugging related properties:
        self.id = hex(id(self))

        logger.debug(f'ProxyOutputConnection {self.id}: __init__')

    def connection_made(self, transport):
        self.transport = transport

        self.input_connection.transport.resume_reading()
        self.input_connection.resume_writing()

        conn_key = (
            self.input_connection.sender_id, self.input_connection.receiver_id
        )
        if conn_key in self.hub_ref.pending_connections:
            self.hub_ref.pending_connections.remove(conn_key)
        else:
            self.hub_ref.num_unexpected_connections += 1
            logger.debug(
                f'ProxyOutputConnection {self.id}: connection_made '
                ' (spontaneous connection)'
            )

        logger.debug(f'''ProxyOutputConnection {self.id}: connection_made {(
            self.input_connection.sender_id,
            self.input_connection.receiver_id
        )}''')

    def connection_lost(self, exc):
        if self.transport is not None:
            if not self.transport.is_closing():
                self.transport.close()
            if not self.input_connection.transport.is_closing():
                self.input_connection.transport.close()
        else:
            logger.warning(
                f'ProxyOutputConnection {self.id}: connection_lost (too early)'
            )

        logger.debug(f'''ProxyOutputConnection {self.id}: connection_lost {(
            self.input_connection.sender_id,
            self.input_connection.receiver_id
        )}''')

    def data_received(self, data):
        self.hub_ref.loop.create_task(self.__handle_received_data(data))

    async def __handle_received_data(self, data):
        receiver2sender_pair = (
            self.input_connection.receiver_id, self.input_connection.sender_id
        )

        await asyncio_sleep(self.hub_ref.latency_policy.get_delay(
            *receiver2sender_pair
        ))

        if len(data) > 0:
            logger.debug(
                f'ProxyOutputConnection {self.id}: {receiver2sender_pair[::-1]} '
                f'received {len(data)} bytes'
            )
            self.recvbuf += data
            self.recvbuf = self.hub_ref.process_buffer(
                buffer=self.recvbuf,
                transport=self.input_connection.transport,
                connection=self
            )
