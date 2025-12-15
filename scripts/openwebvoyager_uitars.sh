#!/bin/bash
start=`date +%s`
python -u run_uitars.py \
    --test_file data/openwebvoyager_full_clean.jsonl \
    --output_dir <path to the output directory> \
    --api_key '' \
    --max_iter 100 \
    --max_attached_imgs 1 \
    --temperature 0 \
    --fix_box_color \
    --seed 42 \
    --headless \
    --model uitars \

end=`date +%s`

runtime=$((end-start))
echo "Script executed in $runtime seconds."