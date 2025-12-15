#!/usr/bin/env bash

MODEL=${1:-"ByteDance-Seed/UI-TARS-1.5-7B"}
BASE_PORT=8001

# Use first argument as number of ports/instances; default to 8 if not given
NUM_PORTS=8

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_DIR="logs/$TIMESTAMP"
mkdir -p "$LOG_DIR"

echo "Launching $NUM_PORTS vLLM servers for model '$MODEL', starting at port $BASE_PORT..."

for ((i=0; i<NUM_PORTS; i++)); do
  PORT=$((BASE_PORT + i))
  echo "Starting vLLM on GPU $i at port $PORT"
  
  CUDA_VISIBLE_DEVICES=$i VLLM_LOG_LEVEL=warning nohup python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --tensor-parallel-size 1 \
    --port "$PORT" \
    --uvicorn-log-level warning \
    --disable-uvicorn-access-log \
    --download_dir ~/.cache/vllm1 \
    > "$LOG_DIR/vllm_gpu${i}.log" 2>&1 &
done

echo "All vLLM servers launched on ports $BASE_PORT to $((BASE_PORT + NUM_PORTS - 1))."

    # --limit-mm-per-prompt image=5 \