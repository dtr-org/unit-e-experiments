#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from asyncio import (
    AbstractEventLoop,
    start_server,
)
from os import getpid
from random import randint
from socket import (
    AF_INET,
    SOCK_STREAM,
    socket as socket_socket
)

import pytest

from experiments.utils.networking import get_pid_for_local_port


@pytest.mark.asyncio
async def test_get_pid_for_tcp_connection_port(
        event_loop: AbstractEventLoop
):
    # Preparing the server
    server = await __get_server(event_loop)
    listening_port = server.sockets[0].getsockname()[1]

    # Asserting that we can identify the server's PID
    listening_pid = get_pid_for_local_port(port=listening_port, status='LISTEN')
    assert (getpid() == listening_pid)

    # Preparing the client
    client_socket: socket_socket = await event_loop.run_in_executor(
        None, __get_client_socket, listening_port
    )

    # Asserting that we can identify the client's PID
    client_port = client_socket.getsockname()[1]
    client_pid = get_pid_for_local_port(port=client_port, status='ESTABLISHED')
    assert (getpid() == client_pid)

    # Asserting that we can filter by the correct type connection
    with pytest.raises(
        expected_exception=RuntimeError,
        match=r'Found PID with status mismatch \(CLOSED not in \[\'ESTABLISHED\', \'LISTEN\'\]\)'
    ):
        get_pid_for_local_port(port=listening_port, status='CLOSED')
    with pytest.raises(
        expected_exception=RuntimeError,
        match=r'Found PID with status mismatch \(LISTEN not in \[\'ESTABLISHED\'\]\)'
    ):
        get_pid_for_local_port(port=client_port, status='LISTEN')

    client_socket.close()
    server.close()


async def __get_server(event_loop: AbstractEventLoop):
    server = await start_server(
        client_connected_cb=(lambda reader, writer: None),
        host='127.0.0.1',
        port=randint(12000, 13000),
        loop=event_loop
    )

    assert (server.sockets is not None)
    assert (1 == len(server.sockets))

    return server


def __get_client_socket(listening_port: int) -> socket_socket:
    client_socket = socket_socket(AF_INET, SOCK_STREAM)
    client_socket.connect(('127.0.0.1', listening_port))

    return client_socket
