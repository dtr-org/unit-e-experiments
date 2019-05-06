#!/usr/bin/env python3

# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

from unittest.mock import Mock

from blockchain.block import Block
from blockchain.blockchain import BlockChain, Clock
from blockchain.simple_node import SimpleNode
from network.latencies import LatencyPolicy, StaticLatencyPolicy


def test_receive_message():
    # Because in our simulations the nodes won't be running all the time, and we
    # only advance the clock second by second, we fake the processing time by
    # adding it to the propagation time, then all the side effects are applied
    # "instantly" without advancing the clock.
    node = SimpleNode(
        node_id=0,
        latency_policy=Mock(spec=LatencyPolicy),
        chain=BlockChain(genesis=Block.genesis()),
        initial_coins=set(),
        processing_time=0.5
    )

    assert 0 == len(node.incoming_messages)

    fake_block = Mock(spec=Block)
    node.receive_message(arrival_time=3.0, msg=fake_block, source_id=42)
    node.receive_message(arrival_time=2.0, msg=fake_block, source_id=5)
    node.receive_message(arrival_time=5.0, msg=fake_block, source_id=34)

    # Basically we're testing that the messages are ordered by arrival time,
    # processing time is not important here because it's constant for all msgs.
    assert 3 == len(node.incoming_messages)
    assert (2.5, fake_block, 5) == node.incoming_messages[0]
    assert (3.5, fake_block, 42) == node.incoming_messages[1]
    assert (5.5, fake_block, 34) == node.incoming_messages[2]


def test_process_messages():
    clock = Clock(first_time=0)
    latency_policy = StaticLatencyPolicy(base_delay=1.5)
    genesis = Block.genesis(
        timestamp=0,
        compact_target=b'\xff\xff\xff\xff',
        vout=[100, 100, 100, 100]
    )
    funds_a = set(genesis.coinstake_tx.get_all_coins()[:2])
    funds_d = set(genesis.coinstake_tx.get_all_coins()[2:])

    # Preparing the nodes
    node_a = SimpleNode(
        node_id=0,
        latency_policy=latency_policy,
        chain=BlockChain(genesis=genesis, clock=clock),
        initial_coins=funds_a,
        processing_time=0.1,
        is_proposer=True
    )
    node_b = SimpleNode(
        node_id=1,
        latency_policy=latency_policy,
        chain=BlockChain(genesis=genesis, clock=clock),
        initial_coins=set(),
        processing_time=0.1,
        is_proposer=False
    )
    node_c = SimpleNode(
        node_id=2,
        latency_policy=latency_policy,
        chain=BlockChain(genesis=genesis, clock=clock),
        initial_coins=set(),
        processing_time=0.1,
        is_proposer=False
    )

    # node_a --> node_b --> node_c
    node_a.add_outbound_peer(node_b)
    node_b.add_outbound_peer(node_c)

    # Let's test message propagation
    ############################################################################
    clock.advance_time(1)  # time == 1

    assert node_a.main_chain.height == 0
    assert node_a.try_to_propose()  # True because the target is trivial

    assert node_a.main_chain.height == 1
    assert node_b.main_chain.height == 0
    assert node_c.main_chain.height == 0

    node_b.process_messages()  # 1.5 + 0.1 seconds left
    node_c.process_messages()
    assert node_a.main_chain.height == 1
    assert node_b.main_chain.height == 0
    assert node_c.main_chain.height == 0

    clock.advance_time(1)  # time == 2
    node_b.process_messages()  # 0.6 seconds left...
    node_c.process_messages()
    assert node_a.main_chain.height == 1
    assert node_b.main_chain.height == 0
    assert node_c.main_chain.height == 0

    clock.advance_time(1)  # time == 3
    node_b.process_messages()
    node_c.process_messages()
    assert node_a.main_chain.height == 1
    assert node_b.main_chain.height == 1  # The message "arrived" at time=2.6
    assert node_c.main_chain.height == 0

    clock.advance_time(1)  # time == 4
    node_b.process_messages()
    node_c.process_messages()
    assert node_a.main_chain.height == 1
    assert node_b.main_chain.height == 1
    assert node_c.main_chain.height == 0  # 0.2 seconds left to add the block

    clock.advance_time(1)  # time == 5
    node_b.process_messages()
    node_c.process_messages()
    assert node_a.main_chain.height == 1
    assert node_b.main_chain.height == 1
    assert node_c.main_chain.height == 1  # The message "arrived" at time=4.2

    # We'll create some forks now, but let's check some pre-conditions before
    ############################################################################
    assert 0 == len(node_a.alternative_chains)
    assert 0 == len(node_b.alternative_chains)
    assert 0 == len(node_c.alternative_chains)

    node_d = SimpleNode(
        node_id=3,
        latency_policy=latency_policy,
        chain=BlockChain(genesis=genesis, clock=clock),
        initial_coins=funds_d,
        processing_time=0.1,
        is_proposer=True
    )
    # node_a ----> node_b --> node_c
    # node_d --┘
    node_d.add_outbound_peer(node_b)

    assert node_d.try_to_propose()  # Let's create a fork (from b's perspective)
    chain_b = node_b.main_chain  # We cache the reference just in case of re-org

    clock.advance_time(2)  # time == 7
    node_b.process_messages()

    assert node_d.main_chain.height == 1
    assert node_b.main_chain.height == 1  # the height was not changed
    assert len(node_d.alternative_chains) == 0  # d does not see any fork
    assert len(node_b.alternative_chains) == 1  # We have a fork

    # node_b didn't do re-org, because chain work is the same for both forks
    assert node_b.main_chain is chain_b

    # Let's extend the fork, to force a re-org
    ############################################################################
    assert node_d.try_to_propose()
    clock.advance_time(2)  # time == 9
    node_b.process_messages()

    assert node_d.main_chain.height == 2
    assert node_b.main_chain.height == 2
    assert len(node_d.alternative_chains) == 0  # Nothing changed here
    assert len(node_b.alternative_chains) == 1  # Nothing changed here
    assert node_b.main_chain is not chain_b  # We had a re-org :) .

    # Now we'll check that SimpleNode is able to deal with orphan blocks
    ############################################################################
    assert len(node_a.orphan_blocks) == 0

    # node_a will receive a message from nowhere...
    node_a.receive_message(
        arrival_time=9.5,
        msg=node_d.main_chain.blocks[-1],  # node_a won't know its parent,
        source_id=node_d.node_id
    )
    clock.advance_time(1)  # time == 10

    node_a.process_messages()
    assert len(node_a.orphan_blocks) == 1  # as expected, the block is orphan
    assert len(node_a.alternative_chains) == 0  # Nothing changed here
    assert node_a.main_chain.height == 1  # Nothing changed here

    # node_a receives the missing parent
    node_a.receive_message(
        arrival_time=10.5,
        msg=node_d.main_chain.blocks[-2],  # this is the orphan's parent
        source_id=node_d.node_id
    )
    clock.advance_time(1)  # time == 11

    node_a.process_messages()
    assert len(node_a.orphan_blocks) == 0  # No orphans anymore
    assert len(node_a.alternative_chains) == 1  # Now we have a fork
    assert node_a.main_chain.height == 2  # And did also a re-org
