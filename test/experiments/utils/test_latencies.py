#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from experiments.utils.latencies import (
    ExponentiallyDistributedLatencyPolicy,
    StaticLatencyPolicy
)


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

    assert (latency_policy.get_delay(src_node=3, dst_node=4) == 42)
    assert (latency_policy.get_delay(src_node=4, dst_node=3) == 42)


def test_exponentially_distributed_latency_policy():
    # When set to zero, there's no randomness at all
    latency_policy = ExponentiallyDistributedLatencyPolicy(avg_delay=0)
    assert (latency_policy.get_delay(0, 1) == 0)
    assert (latency_policy.get_delay(1, 0) == 0)

    # Global Avg Delay ---------------------------------------------------------
    latency_policy = ExponentiallyDistributedLatencyPolicy(avg_delay=3)

    # Assert delays randomness
    assert (100 == len({latency_policy.get_delay(0, 1) for _ in range(100)}))
    assert (100 == len({latency_policy.get_delay(1, 0) for _ in range(100)}))

    # We check that avg corresponds to exp. dist's avg.
    n = 100000
    assert (abs(
        3 - (sum([latency_policy.get_delay(0, 1) for _ in range(n)]) / n)
    ) < 0.1)
    assert (abs(
        3 - (sum([latency_policy.get_delay(1, 0) for _ in range(n)]) / n)
    ) < 0.1)

    # Edge Avg Delays ----------------------------------------------------------
    latency_policy.set_avg_delay(src_node=3, dst_node=4, avg_delay=1)
    latency_policy.set_avg_delay(src_node=4, dst_node=3, avg_delay=2)

    # Assert delays randomness
    assert (100 == len({latency_policy.get_delay(3, 4) for _ in range(100)}))
    assert (100 == len({latency_policy.get_delay(4, 3) for _ in range(100)}))

    # We check that avg corresponds to exp. dist's avg.
    n = 100000
    assert (abs(
        1 - (sum([latency_policy.get_delay(3, 4) for _ in range(n)]) / n)
    ) < 0.05)
    assert (abs(
        2 - (sum([latency_policy.get_delay(4, 3) for _ in range(n)]) / n)
    ) < 0.05)

    # Removing Edge-specific Avg Delays ----------------------------------------
    latency_policy.set_avg_delay(src_node=3, dst_node=4, avg_delay=None)
    latency_policy.set_avg_delay(src_node=4, dst_node=3, avg_delay=None)

    # We check that avg corresponds to the global exp. dist's avg.
    n = 100000
    assert (abs(
        3 - (sum([latency_policy.get_delay(3, 4) for _ in range(n)]) / n)
    ) < 0.1)
    assert (abs(
        3 - (sum([latency_policy.get_delay(4, 3) for _ in range(n)]) / n)
    ) < 0.1)
