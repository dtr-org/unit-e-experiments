# Unit-e Simulations

[![Build Status](https://travis-ci.com/dtr-org/unit-e-simulations.svg?token=1uWjuV23YgNxZQ98zqxB&branch=master)](https://travis-ci.com/dtr-org/unit-e-simulations)

Tools to simulate Unit-e networks

## License

This code published in this repository is released under the terms of the MIT
license. See [LICENSE](LICENSE) for more information or see
https://opensource.org/licenses/MIT.

## Requirements

  * Python 3.6
  * Pipenv ( https://pipenv.readthedocs.io/en/latest/ )

## Setup / Configuration

1. Copy the `.env.example` file to the `.env` file and ensure that the paths are
   correct (it will depend on your local environment, that's why `.env` is not
   versioned).

2. In order to develop the simulations, you will need to install the dev
   packages with the `pipenv` tool by executing `pipenv install --dev`.

## Executing commands

1. Execute the command `pipenv shell` to enter into the virtual environment.
2. Execute `pytest` to run the tests & the static checks.
3. The experiments are in the `experiments` package, to run one of them just
   type `./experiments/experiment_name.py`.

## Running simulations & experiments

### Using the C++ binaries

Here you can find a very basic example that allows us to create a local network
using the C++-implemented nodes.

```python
from asyncio import get_event_loop

from experiments.forking_simulation import ForkingSimulation

import test_framework.util as tf_util


# Because we use part of Unit-e's functional tests framework (specifically the
# TestNode wrapper), we have to set some global properties.
tf_util.MAX_NODES = 500  # has to be greater than 2n+2 where n = num_nodes
tf_util.PortSeed.n = 314159  # We want reproducible pseudo-random numbers


# In order to run a simulation, we'll create a `ForkingSimulation` instance that
# will manage everything for us.
simulation = ForkingSimulation(
    loop=get_event_loop(),
    latency=0.5,
    num_proposer_nodes=45,
    num_relay_nodes=5,
    simulation_time=600,  # Measured in seconds
    sample_time=1,  # Measured in seconds
    graph_model='preferential_attachment',
    block_time_seconds=16,  # Measured in seconds
    block_stake_timestamp_interval_seconds=4,  # Measured in seconds
    network_stats_file_name='network_stats.csv',
    nodes_stats_directory='/home/user/experiment_results/'
)

# Don't close the loop if you want to run more simulations after this one
simulation.safe_run(close_loop=False)

# Once the experiment is executed, the data has to be gathered from the
# `network_stats.csv` file and all the stats files generated individually by
# each node. Usually this is done using Pandas or other similar libraries.
```

### Using the simplified Python code

Here you can find a very basic example that allows us to run a PoSv3 simulation
using pure Python code (simulating several hours or days in much less time).

```python
from blockchain.simnet import SimNet

simulated_network = SimNet(
    simulation_time=600,
    num_proposer_nodes=45,
    num_relay_nodes=5,
    num_coins_per_proposer=3,
    coins_amount=1000,

    time_between_blocks=16,
    block_time_mask=4,
    difficulty_adjustment_window=2048,
    difficulty_adjustment_period=1,

    max_future_block_time_seconds=600,
    latency=0.1,
    processing_time=0.001,

    # This parameter exists to check a vulnerability that depends on how we
    # pick the consensus parameters
    num_greedy_proposers=0,

    # In Bitcoin, the "past median timestamp" is used to validate the current's
    # block timestamp, not just the past block's timestamp (this is done to
    # avoid issues due to out-of-sync clocks). This parameter controls how to
    # compute such median timestamp.
    num_blocks_for_median_timestamp=13,
)

# Once this function call finishes, we'll be able to inspect its state to gather
# all the data we need.
simulated_network.run()

for node in simulated_network.nodes:
    pass # do something here
```

## Troubleshooting

### Import Error while running Jupyter notebooks

It turns out that Jupyter starts Python kernels at the path where the `*.ipynb`
files are located. So, if you are using relative paths in your `.env` file, this
is the most probable cause. It can be fixed just by using absolute paths
instead.