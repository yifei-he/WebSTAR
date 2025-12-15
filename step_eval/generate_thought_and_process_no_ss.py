import argparse
import os
import json
import time
import re
import base64
import concurrent.futures

from openai import OpenAI
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from map_action import map_processed_oai_action, map_oai_action
from prompts import COMPUTER_USE_DOUBAO
from gpt_prompts import GPT_THOUGHT_AUGMENTATION, USER_PROMPT, GPT_STEP_JUDGE_REVISED


def _call_api_with_retry(client, model_name, messages, process_dir, call_type="thought"):
    """Helper function to make API calls with retry and fallback logic."""
    retry = 0
    
    while True:
        retry += 1
        if retry == 20:
            print(f'{process_dir} {call_type} call failed after 20 attempts')
            return None
        
        try:
            response = client.chat.completions.create(
                model=model_name, messages=messages, seed=42, temperature=0
            )
            
            content = response.choices[0].message.content
            
            # For judge calls, we need to validate the score
            if call_type == "judge":
                score = None
                score_patterns = [
                    r'Expected value:\s*(\d+)',
                    r'Expected value:\s*\n\s*(\d+)',
                ]
                for pattern in score_patterns:
                    match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
                    if match:
                        score = int(match.group(1))
                        if 0 <= score <= 10:
                            break
                
                if score is not None:
                    return content, score  # Return both content and score
                else:
                    # Score extraction failed, treat as a retryable error
                    print(f"Warning: No valid score found in judge response, retrying... (attempt {retry}/20) for {process_dir} with model {model_name}")
                    time.sleep(5)
                    continue # continue to next retry iteration
            
            return content # For thought calls

        except Exception as e:
            print(f"Error during {call_type} call: {e}")
            if "ResponsibleAIPolicyViolation" in str(e) or "content_filter" in str(e):
                print(f"Content filter triggered during {call_type} call for {process_dir}. Stopping.")
                return "CONTENT_FILTER_TRIGGERED"
            
            if "Invalid image data." in str(e):
                print(f"Invalid image data during {call_type} call for {process_dir}. Skipping folder {process_dir}.")
                return None

            model_idx += 1
            time.sleep(10)


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def auto_eval_by_gpt(process_dir, openai_client, model_name='o4-mini'):
    interact_path = os.path.join(process_dir, 'interact_messages.json')
    if not os.path.exists(interact_path):
        print(f'File not found: {interact_path}')
        return 0
    
    with open(os.path.join(process_dir, 'interact_messages.json')) as fr:
        it_messages = json.load(fr)
    
    task_info = it_messages[0]["content"]
    if type(task_info) == list:
        task_info = task_info[0]["text"]
    assert 'Now given a task' in task_info
    pattern = r"(.+?)Please interact with"
    matches = re.search(pattern, task_info)
    task_content = matches.group(1).strip()

    action_idx = 0
    whole_content_img = []
    sliding_window = []
    previous_actions = []
    previous_thought_actions = []
    
    start_msg = {
        'role': it_messages[0]['role'],
        'content': it_messages[0]['content'] + '<image>Please analyze the attached screenshot and give the Thought and Action.'
    }
    processed_convo = [start_msg]
    image_list = []

    is_last = False

    # preload base64-encoded screenshots
    annot_dir = os.path.join(process_dir, 'annotated_screenshots')
    zoom_dir = os.path.join(process_dir, 'zoomed_screenshots')
    annotated_b64 = {}
    zoomed_b64 = {}
    if os.path.isdir(annot_dir):
        for fn in os.listdir(annot_dir):
            m = re.match(r'screenshot(\d+)\.png', fn)
            if m:
                idx = int(m.group(1))
                with open(os.path.join(annot_dir, fn), 'rb') as f:
                    annotated_b64[idx] = base64.b64encode(f.read()).decode('utf-8')
    if os.path.isdir(zoom_dir):
        for fn in os.listdir(zoom_dir):
            m = re.match(r'screenshot(\d+)\.png', fn)
            if m:
                idx = int(m.group(1))
                with open(os.path.join(zoom_dir, fn), 'rb') as f:
                    zoomed_b64[idx] = base64.b64encode(f.read()).decode('utf-8')
    action_idx = 0

    for message in it_messages:
        if 'message_type' in message and message['message_type'] in ['action', 'final_answer']:
            if message['message_type'] == 'action':
                action_str = "\nAction: " + map_processed_oai_action(message['content']['parts'][0], follow_prompt=True)

            if message['message_type'] == 'final_answer':
                if 'finished(content=' in message['content']['parts'][0]:
                    action_str = "\nAction: " + message['content']['parts'][0]
                else:
                    action_str = f"\nAction: finished(content='{message['content']['parts'][0]}')"
                is_last = True

            image_list.append(f"{process_dir}/screenshot{action_idx}.png")

            # use preloaded annotated screenshot
            b64_img = annotated_b64.get(action_idx)
            cur_img = {'type':'image_url','image_url':{'url':f"data:image/png;base64,{b64_img}"}}

            # Add to sliding window and maintain size of 5
            sliding_window.append(cur_img)
            if len(sliding_window) > 3:
                sliding_window.pop(0)  # Remove oldest image

            # use preloaded zoomed screenshot if available
            if action_idx in zoomed_b64:
                cur_zoomed_img = {'type':'image_url','image_url':{'url':f"data:image/png;base64,{zoomed_b64[action_idx]}"}}
            else:
                cur_zoomed_img = None
            whole_content_img.append(cur_img)

            user_prompt_tmp = USER_PROMPT.replace('<task>', task_content)
            user_prompt_tmp = user_prompt_tmp.replace('<cur_action>', json.dumps(message))
            user_prompt_tmp = user_prompt_tmp.replace('<previous_actions>', '\n'.join(previous_thought_actions))

            user_judge_prompt_tmp = USER_PROMPT.replace('<task>', task_content)
            user_judge_prompt_tmp = user_judge_prompt_tmp.replace('<cur_action>', json.dumps(message))
            user_judge_prompt_tmp = user_judge_prompt_tmp.replace('<previous_actions>', '\n'.join(previous_actions))

            messages = [
                {'role': 'system', 'content': GPT_THOUGHT_AUGMENTATION},
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': user_prompt_tmp}
                    ]
                    + sliding_window  # Use sliding window instead of just current image
                    + [{'type': 'text', 'text': "Your thought process:\n"}]
                }
            ]

            judge_messages = [
                {'role': 'system', 'content': GPT_STEP_JUDGE_REVISED},
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': user_judge_prompt_tmp}
                    ]
                    + sliding_window + ([cur_zoomed_img] if cur_zoomed_img is not None else [])
                    + [{'type': 'text', 'text': "Your judgement:\n"}]
                }
            ]
            
            thought = None
            judge = None
            score = None

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                # Submit thought and judge calls to run in parallel
                future_thought = executor.submit(
                    _call_api_with_retry,
                    openai_client, model_name, messages, process_dir, "thought"
                )
                
                future_judge = executor.submit(
                    _call_api_with_retry,
                    openai_client, model_name, judge_messages, process_dir, "judge"
                )

                # Wait for results
                thought_result = future_thought.result()
                judge_result = future_judge.result()

            # Process thought result
            if thought_result is None or thought_result == "CONTENT_FILTER_TRIGGERED":
                print(f"Could not get thought for {process_dir}, action {action_idx}. Aborting folder.")
                return None # Or handle as per requirements
            thought = thought_result

            # Process judge result
            if judge_result is None:
                print(f"Could not get judge for {process_dir}, action {action_idx}. Aborting folder.")
                return None # Or handle as per requirements
            if judge_result == "CONTENT_FILTER_TRIGGERED":
                 return {
                    "system": COMPUTER_USE_DOUBAO,
                    "conversations": processed_convo[:-1],
                    "images": image_list,
                }
            judge, score = judge_result

            if thought is None or judge is None or score is None:
                print(f"Failed to get thought/judge/score for {process_dir}. Skipping folder.")
                return None

            previous_actions.append(json.dumps(message))
            thought_str = "Thought: " + thought
            message['thought'] = thought
            
            previous_thought_actions.append(json.dumps(message))
            if len(previous_thought_actions) > 3:
                previous_thought_actions.pop(0)  # Remove oldest image

            action_idx += 1

            processed_convo.append({
                "from": "assistant",
                "value": thought_str + action_str,
                "score": score,
                "judge": judge
            })

            processed_convo.append({
                "from": "user",
                "value": "<image>Please analyze the attached screenshot and give the Thought and Action."
            })

            if is_last:
                break
    
    processed_convo = processed_convo[:-1]
    
    return {
        "system": COMPUTER_USE_DOUBAO,
        "conversations": processed_convo,
        "images": image_list,
    }
## Removed process_single_folder; auto_eval_by_gpt returns directly


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--api_model', type=str, default='o4-mini', help='api model name', choices=['o4-mini', 'gpt-4o'])
    parser.add_argument('--process_dir', type=str, default='results')
    parser.add_argument('--max-workers', type=int, default=32, help='threads for folder-level parallelism')
    parser.add_argument('--correct-only', action='store_true', help='only process folders with correct results')
    parser.add_argument('--finished-only', action='store_true', help='only process folders that have finished the task')
    args = parser.parse_args()

    openai_api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=openai_api_key)

    main_folder = args.process_dir
    subfolders = [f.path for f in os.scandir(main_folder) if f.is_dir()]
    if args.correct_only:
        result_file = os.path.join(main_folder, 'results.json')
        # read from result_file
        with open(result_file, 'r') as fr:
            eval_res = json.load(fr)

    # Filter folders as needed
    filtered_folders = []
    for folder in subfolders:
        # if 'GitHub' in folder:
        #     continue
        output_path = os.path.join(folder, 'output_thought_judge_o4mini.json')
        if os.path.exists(output_path):
            # print(f'Skipping {folder} as output already exists')
            continue
        
        interact_path = os.path.join(folder, 'interact_messages.json')
        if not os.path.exists(interact_path):
            # print(f'Skipping {folder} as no interaction exists')
            continue
        
        # skip folders with booking, cvs, imdb, yelp, ikea
        if 'agoda' in folder or 'enterprise' in folder or 'airbnb' in folder or 'booking' in folder or 'cvs' in folder or 'imdb' in folder or 'yelp'in folder or 'discogs' in folder or 'eventbrite' in folder or 'flightaware' in folder or 'koa' in folder or 'last.fm' in folder or 'marriot' in folder or 'nyc' in folder or 'resy' in folder or 'ryanair' in folder or 'target' in folder or 'thetrainline' in folder or 'tvguide' in folder:
            # print(f'Skipping {folder} as it is an invalid task')
            continue

        if args.correct_only:
            task_name = folder.split('/')[-1]
            if task_name not in eval_res or eval_res[task_name] == 0:
                continue

        if args.finished_only:
            # check whether screenshot100.png exists in the folder
            if os.path.exists(os.path.join(folder, 'screenshot100.png')):
                # print(f'Skipping {folder} as it does not finish the task')
                continue
        
        filtered_folders.append(folder)
    
    print(f'Found {len(filtered_folders)} folders to process')
    
    # Process folders in parallel
    completed_count = 0
    # folder-level parallelism using configurable worker count
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        # Submit all tasks by calling auto_eval_by_gpt directly
        future_to_folder = {
            executor.submit(auto_eval_by_gpt, folder, client, args.api_model): folder
            for folder in filtered_folders
        }
        
        # Process completed tasks as they finish
        for future in concurrent.futures.as_completed(future_to_folder):
            folder = future_to_folder[future]
            try:
                full_output = future.result()
                if isinstance(full_output, dict):
                    # save output JSON
                    out_path = os.path.join(folder, 'output_thought_judge_o4mini.json')
                    with open(out_path, 'w') as fw:
                        json.dump(full_output, fw, indent=4, ensure_ascii=False)
                    completed_count += 1
                    print(f'✓ Completed {completed_count}/{len(filtered_folders)}: {folder}')
                else:
                    print(f'✗ No output for: {folder}')
            except Exception as exc:
                print(f'✗ Error processing {folder}: {exc}')
    
    print(f'Processing complete. Successfully processed {completed_count}/{len(filtered_folders)} folders.')


if __name__ == '__main__':
    main()