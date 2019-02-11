#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from time import time as time_time
from typing import BinaryIO, Optional


class NetworkStatsCollector:
    """"""

    def __init__(self, output_file: BinaryIO):
        self.output_file = output_file

    def register_event(
            self,
            command_name: str,
            command_size: int,
            src_node_id: Optional[int],
            dst_node_id: Optional[int]
    ):
        self.output_file.write((
            f'{time_time()},{src_node_id},{dst_node_id},{command_name},'
            f'{command_size}\n'
        ).encode())
