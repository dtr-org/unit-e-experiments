#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from psutil import net_connections


def get_pid_for_network_client(server_port: int, client_port: int) -> int:
    enforce_host = ('0.0.0.0', '127.0.0.1')
    all_connections = net_connections(kind='tcp4')

    for connection in all_connections:
        if (
            connection.laddr == () or
            connection.raddr == () or
            connection.laddr[0] not in enforce_host or
            connection.raddr[0] not in enforce_host
        ):
            continue  # We only look for local connections
        if client_port == connection.laddr[1]:
            if server_port != connection.raddr[1]:
                continue
        else:
            continue
        if 'LISTEN' == connection.status:
            continue  # We are looking for clients, not servers

        return connection.pid

    raise RuntimeError('Unable to find associated PID')


def get_pid_for_network_server(server_port: int) -> int:
    enforce_host = ('0.0.0.0', '127.0.0.1')
    all_connections = net_connections(kind='tcp4')

    for connection in all_connections:
        if connection.laddr[0] not in enforce_host:
            continue
        if server_port != connection.laddr[1]:
            continue
        if 'LISTEN' != connection.status:
            continue

        return connection.pid

    raise RuntimeError('Unable to find assocaited PID')
