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

## Troubleshooting

### Import Error while running Jupyter notebooks

It turns out that Jupyter starts Python kernels at the path where the `*.ipynb`
files are located. So, if you are using relative paths in your `.env` file, this
is the most probable cause. It can be fixed just by using absolute paths
instead.