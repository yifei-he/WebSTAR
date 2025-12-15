import argparse
import os
import json
import time
import re
import base64

from openai import OpenAI

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

SYSTEM_PROMPT = """As an evaluator, you will be presented with three primary components to assist you in your role:

1. Web Task Instruction: This is a clear and specific directive provided in natural language, detailing the online activity to be carried out. These requirements may include conducting searches, verifying information, comparing prices, checking availability, or any other action relevant to the specified web service (such as Amazon, Apple, ArXiv, BBC News, Booking etc).

2. Result Screenshots: This is a visual representation of the screen showing the result or intermediate state of performing a web task. It serves as visual proof of the actions taken in response to the instruction.

3. Result Response: This is a textual response obtained after the execution of the web task. It serves as textual result in response to the instruction.

-- You DO NOT NEED to interact with web pages or perform actions such as booking flights or conducting searches on websites.
-- You SHOULD NOT make assumptions based on information not presented in the screenshot when comparing it to the instructions.
-- Your primary responsibility is to conduct a thorough assessment of the web task instruction against the outcome depicted in the screenshot and in the response, evaluating whether the actions taken align with the given instructions.
-- NOTE that the instruction may involve more than one task, for example, locating the garage and summarizing the review. Failing to complete either task, such as not providing a summary, should be considered unsuccessful.
-- NOTE that the screenshot is authentic, but the response provided by LLM is generated at the end of web browsing, and there may be discrepancies between the text and the screenshots.
-- Note the difference: 1) Result response may contradict the screenshot, then the content of the screenshot prevails, 2) The content in the Result response is not mentioned on the screenshot, choose to believe the content.

You should elaborate on how you arrived at your final evaluation and then provide a definitive verdict on whether the task has been successfully accomplished, either as 'SUCCESS' or 'NOT SUCCESS'."""
USER_PROMPT = """TASK: <task>
Result Response: <answer>
<num> screenshots at the end: """


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def auto_eval_by_gpt4v(process_dir, openai_client, img_num):
    print(f'--------------------- {process_dir} ---------------------')
    res_files = sorted(os.listdir(process_dir))
    interact_path = os.path.join(process_dir, 'interact_messages.json')
    task_id = os.path.basename(process_dir)
    if not os.path.exists(interact_path):
        print(f'File not found: {interact_path}')
        return task_id, {
            'accuracy': 0,
            'gpt_4v_res': f'File not found: {interact_path}'
        }
    
    with open(os.path.join(process_dir, 'interact_messages.json')) as fr:
        it_messages = json.load(fr)

    if len(it_messages) == 1:
        print('Not find answer for ' + process_dir + ' only system messages')
        print()
        return task_id, {
            'accuracy': 0,
            'gpt_4v_res': 'Not find answer for ' + process_dir
        }

    task_info = it_messages[1]["content"]
    if type(task_info) == list:
        task_info = task_info[0]["text"]
        
    if 'Now given a task' not in task_info:
        print('Not find task info for ' + process_dir)
        print()
        return task_id, {
            'accuracy': 0,
            'gpt_4v_res': 'Not find task info for ' + process_dir
        }
    # assert 'Now given a task' in task_info
    pattern = r"Now given a task:(.+?)Please interact with"
    matches = re.search(pattern, task_info)
    task_content = matches.group(1).strip()

    ans_info = it_messages[-1]["content"]
    if 'Action: ANSWER' not in ans_info and 'finished(content=' not in ans_info:
        print('Not find answer for ' + process_dir)
        print()
        return task_id, {
            'accuracy': 0,
            'gpt_4v_res': 'Not find answer for ' + process_dir
        }
    
    if 'finished(content=' in ans_info:
        pattern_finished = r"finished\(content=(?:'|\")(?P<answer>.*)(?:'|\")\)"
        matches_ans = re.search(pattern_finished, ans_info, re.DOTALL)
        if matches_ans:
            answer_content = matches_ans.group(1).strip()
        else:
            print('Answer not found')
            return task_id, {
                'accuracy': 0,
                'gpt_4v_res': 'Answer not found'
            }
    elif 'ANSWER' in ans_info:
        pattern_ans = r"ANSWER[; ]+\[?(.[^\]]*)\]?"
        matches_ans = re.search(pattern_ans, ans_info)
        answer_content = matches_ans.group(1).strip()

    # max_screenshot_id = max([int(f[10:].split('.png')[0]) for f in os.listdir(process_dir) if '.png' in f])
    # final_screenshot = f'screenshot{max_screenshot_id}.png'
    # b64_img = encode_image(os.path.join(process_dir, final_screenshot))
    whole_content_img = []
    pattern_png = r'screenshot(\d+)\.png'
    matches = [(filename, int(re.search(pattern_png, filename).group(1))) for filename in res_files if re.search(pattern_png, filename)]
    matches.sort(key=lambda x: x[1])
    end_files = matches[-img_num:]
    for png_file in end_files:
        b64_img = encode_image(os.path.join(process_dir, png_file[0]))
        whole_content_img.append(
            {
                'type': 'image_url',
                'image_url': {"url": f"data:image/png;base64,{b64_img}"}
            }
        )

    user_prompt_tmp = USER_PROMPT.replace('<task>', task_content)
    user_prompt_tmp = user_prompt_tmp.replace('<answer>', answer_content)
    user_prompt_tmp = user_prompt_tmp.replace('<num>', str(img_num))
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': user_prompt_tmp}
            ]
            + whole_content_img
            + [{'type': 'text', 'text': "Your verdict:\n"}]
        }
    ]
    api_models = ['gpt-4o-pika', 'gpt-4o-global', 'gpt-4o']
    retry = 0
    model_idx = 0
    while True:
        retry += 1
        if retry == 10: 
            print('API call failed')
            
            return task_id, {
                'accuracy': 0,
                'gpt_4v_res': 'API call failed'
            }
        try:
            cur_model = api_models[model_idx % len(api_models)]
            print('Calling gpt4v API to get the auto evaluation......')
            openai_response = openai_client.chat.completions.create(
                model=cur_model, messages=messages, max_tokens=1000, seed=42, temperature=0
            )
            print('Prompt Tokens:', openai_response.usage.prompt_tokens, ';',
                  'Completion Tokens:', openai_response.usage.completion_tokens)
            print('Cost:', openai_response.usage.prompt_tokens/1000 * 0.01
                  + openai_response.usage.completion_tokens / 1000 * 0.03)

            print('API call complete...')
            break
        except Exception as e:
            print(e)
            model_idx += 1
            if type(e).__name__ == 'RateLimitError':
                time.sleep(10)
            elif type(e).__name__ == 'APIError':
                time.sleep(15)
            elif type(e).__name__ == 'InvalidRequestError':
                exit(0)
            else:
                time.sleep(10)
    gpt_4v_res = openai_response.choices[0].message.content
    print_message = messages[1]
    for idx in range(len(print_message['content'])):
        if print_message['content'][idx]['type'] == 'image_url':
            print_message['content'][idx]['image_url'] = {"url": "data:image/png;base64, b64_img"}

    # print_message[1]['content'][1]['image_url'] = {"url": "data:image/png;base64, b64_img"}
    print(print_message)
    print(gpt_4v_res)

    auto_eval_res = 0 if 'NOT SUCCESS' in gpt_4v_res else 1
    if 'SUCCESS' not in gpt_4v_res:
        auto_eval_res = None
    print('Auto_eval_res:', auto_eval_res)
    print()
    # return auto_eval_res
    return task_id, {
        'accuracy': auto_eval_res,
        'gpt_4v_res': gpt_4v_res.strip()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api_key", default="key", type=str, help="YOUR_OPENAI_API_KEY")
    parser.add_argument('--process_dir', type=str, default='results')
    parser.add_argument("--api_model", default="gpt-4o", type=str,
                        choices=['gpt-4o-pika', 'gpt-4o-global', 'gpt-4o'])
    parser.add_argument("--max_attached_imgs", type=int, default=1)
    parser.add_argument("--workers", type=int, default=64)
    args = parser.parse_args()

    # init Azure client once
    client = OpenAI(api_key=args.api_key)


    webs = ['Allrecipes', 'Amazon', 'Apple', 'ArXiv', 'BBC News', 'Booking',
            'Cambridge Dictionary', 'Coursera', 'ESPN', 'GitHub',
            'Google Flights', 'Google Map', 'Google Search',
            'Huggingface', 'Wolfram Alpha']

    # gather all existing task directories
    tasks = []
    for web in webs:
        for idx in range(46):
            d = os.path.join(args.process_dir, f'task{web}--{idx}')
            if os.path.isdir(d):
                tasks.append(d)

    # run in parallel
    results = {}
    out_path = os.path.join(args.process_dir, 'results.json')
    dump_every = 100
    count = 0
    with ThreadPoolExecutor(max_workers=args.workers) as exe:
        futures = {
            exe.submit(auto_eval_by_gpt4v, d, client, args.max_attached_imgs): d
            for d in tasks
        }

        for fut in as_completed(futures):
            task_dir = futures[fut]
            try:
                task_id, out = fut.result()
                results[task_id] = out
            except Exception as e:
                tid = os.path.basename(task_dir)
                results[tid] = {
                    'accuracy': None,
                    'gpt_4v_res': f'ERROR: {e}'
                }

            count += 1

            # every 100 tasks, write out the current dict
            if count % dump_every == 0:
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=4, ensure_ascii=False)
                print(f"Flushed {count} tasks")

    # write master results.json
    with open(out_path, 'w') as wf:
        json.dump(results, wf, indent=4, ensure_ascii=False)

    print(f"Wrote {len(results)} entries to {out_path}")

if __name__ == '__main__':
    main()