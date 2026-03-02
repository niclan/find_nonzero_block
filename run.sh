#!/bin/bash

echo "Host: $1"
echo "Device: $2"

scp find_first_nonzero_block.py "$1":.
ssh "$1" "sudo python3 find_first_nonzero_block.py $2"
