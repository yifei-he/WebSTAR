#!/bin/bash
start=`date +%s`
python -u run_operator.py \
    --test_file data/openwebvoyager_full_clean.jsonl \
    --output_dir "<path to the output directory>" \
    --api_key '' \
    --max_iter 100 \
    --max_attached_imgs 1 \
    --temperature 1 \
    --fix_box_color \
    --seed 42 \
    --headless \
    --model gpt \
    --model_name computer_use_preview \
    --num_trials 4 \

end=`date +%s`

runtime=$((end-start))
echo "Script executed in $runtime seconds."