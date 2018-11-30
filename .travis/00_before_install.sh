#!/usr/bin/env bash

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

export TRAVIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
openssl aes-256-cbc -K $encrypted_3508967e0358_key -iv $encrypted_3508967e0358_iv -in "${TRAVIS_DIR}/ssh_key.enc" -out "${TRAVIS_DIR}/ssh_key" -d
