#!/bin/bash
DIR=<path_to_your_directory>
python -u auto_eval_parallel.py \
    --api_key YOUR_OPENAI_API_KEY \
    --process_dir $DIR\
    --max_attached_imgs 50 > $DIR/eval.txt