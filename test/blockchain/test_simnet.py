#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from blockchain.simnet import SimNet


def test_simnet_run():
    simnet = SimNet(
        simulation_time=600,  # 10 minutes
        num_proposer_nodes=10,
        num_relay_nodes=10,
        time_between_blocks=8,
        block_time_mask=2,
        difficulty_adjustment_window=6,
        difficulty_adjustment_period=1,
        num_blocks_for_median_timestamp=3,
        max_future_block_time_seconds=16,
        latency=0.1,
        processing_time=0.001
    )
    simnet.run()

    assert len(simnet.nodes) == 20
    for node in simnet.nodes:
        # The 1.3 coefficient was decided as a simple rule of thumb
        assert 600 / 8 / 1.3 < node.main_chain.height < 600 * 1.3 / 8
