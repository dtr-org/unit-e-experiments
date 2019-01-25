#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from experiments.utils.latencies import StaticLatencyPolicy


def test_static_latency_policy():
    latency_policy = StaticLatencyPolicy(base_delay=42)

    assert (latency_policy.get_delay(0, 1) == 42)
    assert (latency_policy.get_delay(1, 0) == 42)

    latency_policy.set_delay(src_node=3, dst_node=4, delay=15)
    latency_policy.set_delay(src_node=4, dst_node=3, delay=12)

    assert (latency_policy.get_delay(3, 4) == 15)
    assert (latency_policy.get_delay(4, 3) == 12)

    latency_policy.set_delay(src_node=3, dst_node=4, delay=None)
    latency_policy.set_delay(src_node=4, dst_node=3, delay=None)

    latency_policy.set_delay(src_node=3, dst_node=4, delay=42)
    latency_policy.set_delay(src_node=4, dst_node=3, delay=42)
