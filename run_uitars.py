import platform
import argparse
import time
import json
import re
import os
import shutil
import logging

from playwright.async_api import async_playwright

from prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_TEXT_ONLY, COMPUTER_USE_DOUBAO
from openai import OpenAI
from utils import get_web_element_rect, encode_image, extract_information, print_message,\
    get_webarena_accessibility_tree, get_pdf_retrieval_ans_from_assistant, clip_message_and_obs, clip_message_and_obs_text_only

import os
import base64

from transformers import AutoModelForVision2Seq, AutoProcessor
from qwen_vl_utils import process_vision_info
from uitars_action_parser import parse_action_to_structure_output, parsing_response_to_selenium_code
import ast
import asyncio
import concurrent.futures
from cua_utils import CUA_KEY_TO_PLAYWRIGHT_KEY

def setup_main_logger(log_file_path):
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)  # Ensure directory exists
    logger = logging.getLogger("main")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

def get_task_logger(task_dir, task_id, trial_id):
    logger = logging.getLogger(f"task_{task_id}_{trial_id}")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(os.path.join(task_dir, 'agent.log'))
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    # Avoid adding multiple handlers if logger already has one
    if not logger.handlers:
        logger.addHandler(handler)
    return logger

def setup_logger(folder_path):
    log_file_path = os.path.join(folder_path, 'agent.log')

    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ── Playwright Browser Launch ─────────────────────────────────────────────────
async def launch_browser(args):
    pw = await async_playwright().start()
    launch_args = [
        f"--window-size={args.window_width},{args.window_height}",
        "--disable-extensions",
        "--disable-file-system",
    ]
    browser = await pw.chromium.launch(
        chromium_sandbox=True,
        headless=args.headless, 
        args=launch_args,
        env={"DISPLAY": ":0"},
    )
    context = await browser.new_context(
        viewport={"width": args.window_width, "height": args.window_height},
        device_scale_factor=1 if args.force_device_scale else 1
    )
    page = await context.new_page()
    return pw, browser, page


def format_msg(it, init_msg, pdf_obs, warn_obs, web_img_b64, web_text):
    if it == 1:
        init_msg += f"Please proceed with your Thought and Action."
        init_msg_format = {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': init_msg},
            ]
        }
        init_msg_format['content'].append({"type": "image_url",
                                           "image_url": {"url": f"data:image/png;base64,{web_img_b64}"}})
        return init_msg_format
    else:
        if not pdf_obs:
            curr_msg = {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': f"Observation:{warn_obs} please analyze the attached screenshot and give the Thought and Action. "},
                    {
                        'type': 'image_url',
                        'image_url': {"url": f"data:image/png;base64,{web_img_b64}"}
                    }
                ]
            }
        else:
            curr_msg = {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': f"Observation: {pdf_obs} Please analyze the response given by Assistant, then consider whether to continue iterating or not. The screenshot of the current page is also attached, give the Thought and Action. "},
                    {
                        'type': 'image_url',
                        'image_url': {"url": f"data:image/png;base64,{web_img_b64}"}
                    }
                ]
            }
        return curr_msg


def format_msg_text_only(it, init_msg, pdf_obs, warn_obs, ac_tree):
    if it == 1:
        init_msg_format = {
            'role': 'user',
            'content': init_msg + '\n' + ac_tree
        }
        return init_msg_format
    else:
        if not pdf_obs:
            curr_msg = {
                'role': 'user',
                'content': f"Observation:{warn_obs} please analyze the accessibility tree and give the Thought and Action.\n{ac_tree}"
            }
        else:
            curr_msg = {
                'role': 'user',
                'content': f"Observation: {pdf_obs} Please analyze the response given by Assistant, then consider whether to continue iterating or not. The accessibility tree of the current page is also given, give the Thought and Action.\n{ac_tree}"
            }
        return curr_msg

# use vllm openai client
def call_uitars(args, messages, model, processor):
    # Preparation for inference
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    inputs = inputs.to("cuda")

    # Inference: Generation of the output
    generated_ids = model.generate(**inputs, max_new_tokens=1000)
    generated_ids_trimmed = [
        out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )

    return inputs['input_ids'].shape[1], len(generated_ids_trimmed[0]), False, output_text[0]


def call_gpt4v_api(args, client, messages, model_name):
    retry_times = 0
    
    while True:
        try:
            openai_response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_completion_tokens=1000,
                stop=None,
                stream=False,
                seed=args.seed
            ).to_dict()
            
            prompt_tokens = openai_response['usage']['prompt_tokens']
            completion_tokens = openai_response['usage']['completion_tokens']

            logging.info(f'Prompt Tokens: {prompt_tokens}; Completion Tokens: {completion_tokens}')

            gpt_call_error = False
            return prompt_tokens, completion_tokens, gpt_call_error, openai_response

        except Exception as e:
            logging.info(f'Error occurred, retrying. Error type: {type(e).__name__}')

            if type(e).__name__ == 'RateLimitError':
                time.sleep(10)

            elif type(e).__name__ == 'APIError':
                time.sleep(15)

            elif type(e).__name__ == 'InvalidRequestError':
                gpt_call_error = True
                return None, None, gpt_call_error, None

            else:
                gpt_call_error = True
                return None, None, gpt_call_error, None

        retry_times += 1
        if retry_times == 10:
            logging.info('Retrying too many times')
            return None, None, True, None


# ── Action Executors (Playwright) ─────────────────────────────────────────────
async def exec_action_click(info, page):
    x, y = info['x'], info['y']
    
    # Set target=_self if the element has a target attribute
    await page.evaluate("""
        ([x, y]) => {
            const elem = document.elementFromPoint(x, y);
            if (elem && 'target' in elem) {
                elem.setAttribute('target', '_self');
            }
        }
    """, [x, y])

    await page.mouse.click(x, y)
    await asyncio.sleep(3)


async def exec_action_type(info, page):
    await page.keyboard.type(info['content'])
    await page.keyboard.press('Enter')
    await asyncio.sleep(3)


async def perform_hotkey(page, key_str: str):
    """
    Perform a hotkey (e.g., 'ctrl a', 'pagedown') on the page.
    Ensures the page has a focused element before sending the keys.

    Args:
        page: Playwright Page object
        key_str: string like 'ctrl a', 'pagedown'
        fallback_focus_selector: selector to focus if no input is focused (defaults to 'body')
    """

    keys = key_str.strip().lower().split()

    mapped_keys = [CUA_KEY_TO_PLAYWRIGHT_KEY.get(key, key) for key in keys]
    for key in mapped_keys:
        await page.keyboard.down(key)
        await asyncio.sleep(1)
    for key in reversed(mapped_keys):
        await page.keyboard.up(key)
        await asyncio.sleep(1)


async def exec_action_scroll(info, page, args, box):
    x = box[0]*1000
    y = box[1]*1000
    await page.mouse.move(x, y)
    dist = args.window_height * 1 // 3
    scroll_y = dist if info.get("direction") == "down" else -dist
    await page.evaluate(f"window.scrollBy(0, {scroll_y})")
    # delta = dist if info.get('direction') == 'down' else -dist
    # await page.mouse.wheel(0, delta)
    await asyncio.sleep(3)


async def exec_action_drag(info, page):
    # Raw coordinate drag: mouse down, move, mouse up
    x1, y1, x2, y2 = info['x1'], info['y1'], info['x2'], info['y2']
    await page.mouse.move(x1, y1)
    await page.mouse.down()
    await page.mouse.move(x2, y2)
    await page.mouse.up()
    await asyncio.sleep(3)


async def run_task(task_id, task, trial_id, args, result_dir, client):
    task_dir = os.path.join(result_dir, f'task{task["id"]}-{trial_id}')
    os.makedirs(task_dir, exist_ok=True)
    # setup_logger(task_dir)
    task_logger = get_task_logger(task_dir, task["id"], trial_id)
    task_logger.info(f'########## TASK{task["id"]} Trial {trial_id} ##########')

    pw, browser, page = await launch_browser(args)
    await page.goto(task['web'], timeout=180000)
    await asyncio.sleep(5)

    for filename in os.listdir(args.download_dir):
        file_path = os.path.join(args.download_dir, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)

    download_files = []
    fail_obs = ""
    pdf_obs = ""
    warn_obs = ""
    pattern = r'Thought:|Action:|Observation:'

    messages = [{'role': 'system', 'content': COMPUTER_USE_DOUBAO}]
    obs_prompt = "Observation: please analyze the attached screenshot and give the Thought and Action. "
    if args.text_only:
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT_TEXT_ONLY}]
        obs_prompt = "Observation: please analyze the accessibility tree and give the Thought and Action."

    init_msg = f"""Now given a task: {task['ques']}  Please interact with https://www.example.com and get the answer. \n"""
    init_msg = init_msg.replace('https://www.example.com', task['web'])
    init_msg = init_msg + obs_prompt

    it = 0
    accumulate_prompt_token = 0
    accumulate_completion_token = 0

    while it < args.max_iter:
        print(f'Iter: {it}')
        task_logger.info(f'Iter: {it}')
        it += 1

        img_path = os.path.join(task_dir, f'screenshot{it}.png')
        await page.screenshot(path=img_path, timeout=60000)
        b64_img = encode_image(img_path)

        if not fail_obs:
            # message formatting unchanged
            if not args.text_only:
                msg = format_msg(it, init_msg, pdf_obs, warn_obs, b64_img, None)
                messages = clip_message_and_obs(messages + [msg], max_img_num=args.max_attached_imgs)
            else:
                ac_tree, _ = get_webarena_accessibility_tree(page, task_dir)
                msg = format_msg_text_only(it, init_msg, pdf_obs, warn_obs, ac_tree)
                messages = clip_message_and_obs_text_only(messages + [msg], max_img_num=args.max_attached_imgs)
        else:
            curr_msg = {
                'role': 'user',
                'content': fail_obs
            }
            messages.append(curr_msg)

        if not args.text_only:
            messages = clip_message_and_obs(messages, args.max_attached_imgs)
        else:
            messages = clip_message_and_obs_text_only(messages, args.max_attached_imgs)

        if args.model == 'gpt': 
            task_logger.info('Calling gpt4o API...')
            model_name = 'gpt-4o'
        elif args.model == 'uitars': 
            task_logger.info('Calling uitars API...')
            model_name = args.model_name

        prompt_tokens, completion_tokens, gpt_call_error, openai_response = call_gpt4v_api(args, client, messages, model_name)
        if openai_response is None:
            print("API ERROR: The API call failed, please try again.")
        model_res = openai_response['choices'][0]['message']['content']

        accumulate_prompt_token += prompt_tokens
        accumulate_completion_token += completion_tokens
        task_logger.info(f'Accumulate Prompt Tokens: {accumulate_prompt_token}; Accumulate Completion Tokens: {accumulate_completion_token}')
        task_logger.info('API call complete...')

        messages.append({'role': 'assistant', 'content': model_res})

        try:
            assert 'Action:' in model_res
        except AssertionError as e:
            logging.error(e)
            fail_obs = "Format ERROR: 'Action' must be included in your reply."
            continue

        # chosen_action = re.split(pattern, model_res)[2].strip()
        # print(model_res)
        # print(f'Chosen action: {chosen_action}')

        if "Action: finished" in model_res:
            break

        factor = 1000
        try: 
            parsed_dict = parse_action_to_structure_output(
                model_res,
                factor=factor,
                origin_resized_height=args.window_height,
                origin_resized_width=args.window_width,
                model_type="doubao"
            )
        except Exception as e:
            logging.error('Error when parsing action to structure output:')
            logging.error(e)
            fail_obs = "Format ERROR: The Action format is not correct, please follow the format: Action: <action_type>(<action_inputs>)"
            continue
        
        print(parsed_dict)
        for parsed in parsed_dict:
            action_key = parsed['action_type']
            action_inputs = parsed['action_inputs']
            print(action_key, action_inputs)

            fail_obs = ""
            pdf_obs = ""
            warn_obs = ""
            try:
                if action_key in ['click','left_double','right_single']:
                    box = ast.literal_eval(action_inputs['start_box'])
                    x, y = box[0]*1000, box[1]*1000
                    await exec_action_click({'x':x,'y':y}, page)
                elif action_key=='type':
                    box = ast.literal_eval(action_inputs.get('start_box','(0,0)'))
                    await exec_action_type({'x':box[0]*1000,'y':box[1]*1000,'content':action_inputs['content']}, page)
                elif action_key=='hotkey': 
                    await perform_hotkey(page, action_inputs['key'])
                elif action_key=='scroll': 
                    box = ast.literal_eval(action_inputs['start_box'])
                    await exec_action_scroll(action_inputs, page, args, box)
                elif action_key=='drag':
                    box = ast.literal_eval(action_inputs['start_box'])
                    await exec_action_drag({'x1':box[0]*1000,'y1':box[1]*1000,'x2':box[2]*1000,'y2':box[3]*1000}, page)
                elif action_key=='finished': 
                    break
                await asyncio.sleep(3)
            except Exception as e:
                logging.error(f"Exec error: {e}")
                fail_obs = "The action cannot be executed. Please revise."
                await asyncio.sleep(3)
                continue

    print_message(messages, task_dir)
    await browser.close()
    await pw.stop()
    task_logger.info(f'Total cost: {accumulate_prompt_token / 1000 * 0.01 + accumulate_completion_token / 1000 * 0.03}')



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_file', type=str, default='data/test.json')
    parser.add_argument('--max_iter', type=int, default=5)
    parser.add_argument("--api_key", default="key", type=str, help="YOUR_OPENAI_API_KEY")
    parser.add_argument("--api_model", default="gpt-4-vision-preview", type=str, help="api model name")
    parser.add_argument("--output_dir", type=str, default='results')
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max_attached_imgs", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--download_dir", type=str, default="downloads")
    parser.add_argument("--text_only", action='store_true')
    parser.add_argument("--num_trials", type=int, default=1, help="Number of times to run each task.")
    # for web browser
    parser.add_argument("--headless", action='store_true', help='The window of selenium')
    parser.add_argument("--save_accessibility_tree", action='store_true')
    parser.add_argument("--force_device_scale", action='store_true')
    parser.add_argument("--window_width", type=int, default=1024)
    parser.add_argument("--window_height", type=int, default=768)  # for headless mode, there is no address bar
    parser.add_argument("--fix_box_color", action='store_true')
    parser.add_argument("--model", type=str, default='gpt', choices=['gpt', 'uitars'])
    parser.add_argument("--model_name", type=str, default="ByteDance-Seed/UI-TARS-1.5-7B")

    args = parser.parse_args()

    current_time = time.strftime("%Y%m%d_%H_%M_%S", time.localtime())
    log_file_path = os.path.join(os.path.join(args.output_dir, current_time), 'main.log')

    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed",  # Dummy key to satisfy the client
    )

    # Save Result file
    result_dir = os.path.join(args.output_dir, current_time)
    print(result_dir)
    os.makedirs(result_dir, exist_ok=True)

    # Load tasks
    tasks = []
    with open(args.test_file, 'r', encoding='utf-8') as f:
        for line in f:
            tasks.append(json.loads(line))
    
    # Use ThreadPoolExecutor for parallelism
    def run_task_sync(task_id, trial_id):
        asyncio.run(run_task(task_id, tasks[task_id], trial_id, args, result_dir, client))

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for task_id in range(len(tasks)):
            for trial_id in range(1, args.num_trials + 1):
                futures.append(executor.submit(run_task_sync, task_id, trial_id))
        for future in concurrent.futures.as_completed(futures):
            future.result()
        
        

if __name__ == '__main__':
    main()
    print('End of process')
