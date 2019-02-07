#!/usr/bin/env python3

# Copyright (c) 2018-2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.


from typing import BinaryIO
from unittest.mock import Mock, patch

from experiments.utils.network_stats import NetworkStatsCollector


def test_network_stats_collector():
    mocked_file: Mock = Mock(spec=BinaryIO)
    network_stats_collector = NetworkStatsCollector(output_file=mocked_file)

    with patch(
        target='experiments.utils.network_stats.time_time',
        new=lambda: 1549551476.292045
    ):
        network_stats_collector.register_event(
            command_name='version',
            command_size=65,
            src_node_id=13,
            dst_node_id=29
        )

    mocked_file.write.assert_called_once_with(
        b'1549551476.292045, 13, 29, version, 65\n'
    )
