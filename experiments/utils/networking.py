#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from typing import Optional

from psutil import net_connections


def get_pid_for_local_port(
        port: int,
        enforce_host: Optional[str] = '127.0.0.1',
        status: Optional[str] = 'ESTABLISHED'
) -> int:
    all_connections = net_connections(kind='tcp4')

    found_status = []
    for connection in all_connections:
        if port != connection.laddr[1]:
            continue
        if enforce_host is not None and enforce_host != connection.laddr[0]:
            continue
        if status is not None and status != connection.status:
            found_status.append(connection.status)
            continue

        return connection.pid

    if len(found_status) > 0:
        raise RuntimeError(
            'Found PID with status mismatch '
            f'({status} not in {sorted(found_status)})'
        )
    else:
        raise RuntimeError('Unable to find associated PID')
