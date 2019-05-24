#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from abc import ABCMeta, abstractmethod
from time import time as time_time
from typing import BinaryIO, Optional


class NetworkStatsCollector(metaclass=ABCMeta):
    @abstractmethod
    def register_event(
        self,
        command_name: str,
        command_size: int,
        src_node_id: Optional[int],
        dst_node_id: Optional[int]
    ):
        raise NotImplementedError

    @abstractmethod
    def close(self):
        pass


class CsvNetworkStatsCollector(NetworkStatsCollector):
    """It dumps networking-related statistics to a CSV file."""

    def __init__(self, output_file: BinaryIO):
        self.output_file = output_file
        self.running = True

    def register_event(
            self,
            command_name: str,
            command_size: int,
            src_node_id: Optional[int],
            dst_node_id: Optional[int]
    ):
        if not self.running:
            return

        self.output_file.write((
            f'{int(time_time()*1000)},{src_node_id},{dst_node_id},'
            f'{command_name},{command_size}\n'
        ).encode())

    def close(self):
        if not self.running:
            return

        self.running = False

        if (
            self.output_file is not None and
            not self.output_file.closed
        ):
            self.output_file.close()


class NullNetworkStatsCollector(NetworkStatsCollector):
    def register_event(
        self,
        command_name: str,
        command_size: int,
        src_node_id: Optional[int],
        dst_node_id: Optional[int]
    ):
        pass

    def close(self):
        pass
