#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


class TestNet:
    def __init__(
        self, *,
        num_proposer_nodes: int,
        num_relay_nodes: int,
    ):
        self.num_proposer_nodes = num_proposer_nodes
        self.num_relay_nodes = num_relay_nodes
