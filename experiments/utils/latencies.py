#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from abc import ABCMeta, abstractmethod
from random import expovariate
from typing import Dict, Optional, Tuple


class LatencyPolicy(metaclass=ABCMeta):
    @abstractmethod
    def get_delay(self, src_node: int, dst_node: int) -> float:
        raise NotImplementedError


class StaticLatencyPolicy(LatencyPolicy):
    def __init__(self, base_delay: float = 0.0):
        self.base_delay = base_delay
        self.node2node_delays: Dict[Tuple[int, int], float] = {}

    def set_delay(self, src_node: int, dst_node: int, delay: Optional[float]):
        if delay is None:
            self.node2node_delays.pop((src_node, dst_node), None)
        else:
            self.node2node_delays[(src_node, dst_node)] = delay

    def get_delay(self, src_node: int, dst_node: int) -> float:
        if (src_node, dst_node) in self.node2node_delays:
            return self.node2node_delays[(src_node, dst_node)]
        return self.base_delay


class ExponentiallyDistributedLatencyPolicy(LatencyPolicy):
    def __init__(self, avg_delay: float = 0.0):
        self.avg_delay = avg_delay
        self.node2node_avg_delays: Dict[Tuple[int, int], float] = {}

    def set_avg_delay(
            self, src_node: int, dst_node: int, avg_delay: Optional[float]
    ):
        if avg_delay is None:
            self.node2node_avg_delays.pop((src_node, dst_node), None)
        else:
            self.node2node_avg_delays[(src_node, dst_node)] = avg_delay

    def get_delay(self, src_node: int, dst_node: int) -> float:
        if (src_node, dst_node) in self.node2node_avg_delays:
            avg_delay = self.node2node_avg_delays[(src_node, dst_node)]
        else:
            avg_delay = self.avg_delay

        if avg_delay == 0.0:
            return 0.0

        return expovariate(1.0 / avg_delay)
