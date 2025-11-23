#!/bin/bash
source ~/.bashrc
source ~/software/pkg/miniforge3/etc/profile.d/conda.sh
conda activate ubair-data-push
cd ~/gits/brc-tools
python brc_tools/download/get_map_obs.py
