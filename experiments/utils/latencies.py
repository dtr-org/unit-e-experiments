#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from abc import ABCMeta, abstractmethod
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
        if delay is None or delay == self.base_delay:
            self.node2node_delays.pop((src_node, dst_node), None)
        else:
            self.node2node_delays[(src_node, dst_node)] = delay

    def get_delay(self, src_node: int, dst_node: int) -> float:
        if (src_node, dst_node) in self.node2node_delays:
            return self.node2node_delays[(src_node, dst_node)]
        return self.base_delay
