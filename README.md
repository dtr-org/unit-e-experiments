# Unit-e Simulations

Tools to simulate Unit-e networks


## Requisites

  * Python 3.6
  * Pipenv ( https://pipenv.readthedocs.io/en/latest/ )

## Setup / Configuration

### Development environment

1. In order to develop the simulations, you will need to install the dev
   packages with the `pipenv` tool.

2. To execute the tests, and all the static checks (pyflake8 & mypy), copy the
   `.env.example` file to the `.env` file and ensure that the paths are correct
   (it will depend on your local environment, that's why `.env` is not
   versioned).

3. It's a good idea to activate the virtual environment executing the command
   `pipenv shell`, this command ensures that `pytest` & `mypy` will be
   available, and that the environment variables are loaded from the `.env`
   file.

### Simulation settings

In order to run the simulations, you must copy the file `settings.py.example` as
`settings.py` and adapt the listed paths to make possible finding some Python
packages available in the Unit-e repository.
