import platform
import argparse
import time
import json
import re
import os
import shutil
import logging
import base64
import asyncio
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from playwright.async_api import async_playwright, Browser, Page
from prompts import *
from openai import OpenAI
from utils_webarena import get_webarena_accessibility_tree
from cua_utils import CUA_KEY_TO_PLAYWRIGHT_KEY


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


class PlaywrightComputer:
    def __init__(self, args, task):
        self.args = args
        self.task = task
        self._playwright = None
        self._browser = None
        self._page = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        launch_args = [
            f"--window-size={self.args.window_width},{self.args.window_height}",
            "--disable-extensions",
            "--disable-file-system",
        ]
        self._browser = await self._playwright.chromium.launch(
            headless=self.args.headless,
            args=launch_args,
            env={"DISPLAY": ":0"},
        )
        context = await self._browser.new_context(
            viewport={"width": self.args.window_width, "height": self.args.window_height},
            device_scale_factor=1 if self.args.force_device_scale else 1
        )
        self._page = await context.new_page()
        await self._page.goto(self.task['web'], timeout=180000)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def click(self, x: int, y: int, button: str = "left") -> None:
        # Set target=_self if the element has a target attribute
        await self._page.evaluate("""
            ([x, y]) => {
                const elem = document.elementFromPoint(x, y);
                if (elem && 'target' in elem) {
                    elem.setAttribute('target', '_self');
                }
            }
        """, [x, y])

        if button == "back":
            await self.back()
        elif button == "forward":
            await self.forward()
        elif button == "wheel":
            await self._page.mouse.wheel(x, y)
        else:
            await self._page.mouse.click(x, y, button={"left": "left", "right": "right"}.get(button.lower(), "left"))
        await asyncio.sleep(3)

    async def double_click(self, x: int, y: int) -> None:
        await self._page.mouse.dblclick(x, y)
        await asyncio.sleep(3)

    async def scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        await self._page.mouse.move(x, y)
        await self._page.evaluate(f"window.scrollBy({scroll_x}, {scroll_y})")
        await asyncio.sleep(3)

    async def type(self, text: str) -> None:
        await self._page.keyboard.type(text)
        await asyncio.sleep(3)

    async def wait(self, ms: int = 1000) -> None:
        await asyncio.sleep(ms / 1000)

    async def move(self, x: int, y: int) -> None:
        await self._page.mouse.move(x, y)

    async def keypress(self, keys: List[str]) -> None:
        mapped = [CUA_KEY_TO_PLAYWRIGHT_KEY.get(k.lower(), k) for k in keys]
        for k in mapped:
            await self._page.keyboard.down(k)
        for k in reversed(mapped):
            await self._page.keyboard.up(k)

    async def drag(self, path: List[Dict[str, int]]) -> None:
        if not path: return
        await self._page.mouse.move(path[0]["x"], path[0]["y"])
        await self._page.mouse.down()
        for pt in path[1:]:
            await self._page.mouse.move(pt["x"], pt["y"])
        await self._page.mouse.up()
        await asyncio.sleep(3)

    async def goto(self, url: str) -> None:
        try:
            await self._page.goto(url)
        except Exception as e:
            print(f"Error navigating to {url}: {e}")
        await asyncio.sleep(3)

    async def back(self) -> None:
        await self._page.go_back()
        await asyncio.sleep(3)

    async def forward(self) -> None:
        await self._page.go_forward()
        await asyncio.sleep(3)

    async def screenshot(self, path=None) -> str:
        png_bytes = await self._page.screenshot(path=path, timeout=60000) if path else await self._page.screenshot(timeout=60000)
        return base64.b64encode(png_bytes).decode("utf-8")

    def get_environment(self) -> str:
        return "browser"

    def get_current_url(self) -> str:
        return self._page.url


async def handle_item(item, computer: PlaywrightComputer, img_path):
    if item["type"] == "message":
        print(item["content"][0]["text"])
    
    if item["type"] == "reasoning":
        reasoning_text = item["summary"][0]["text"]
        print(f"Thought: {reasoning_text}")

    if item["type"] == "computer_call":
        action = item["action"]
        action_type = action["type"]
        action_args = {k: v for k, v in action.items() if k != "type"}
        print(f"\u2192 {action_type}({action_args})")
        if action_type != "screenshot":
            await getattr(computer, action_type)(**action_args)
        screenshot_base64 = await computer.screenshot(path=img_path)
        call_output = {
            "type": "computer_call_output",
            "call_id": item["call_id"],
            "acknowledged_safety_checks": item.get("pending_safety_checks", []),
            "output": {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{screenshot_base64}",
            },
        }
        return [call_output]


def run_task_sync(task, args, result_dir, trial_id):
    openai_api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=openai_api_key)

    asyncio.run(run_task(task, args, client, args.api_model, result_dir, trial_id))


async def run_task(task, args, client, api_model, result_dir, trial_id):
    task_dir = os.path.join(result_dir, f'task{task["id"]}-{trial_id}')
    os.makedirs(task_dir, exist_ok=True)
    setup_logger(task_dir)
    logging.info(f'########## TASK{task["id"]}-{trial_id} ##########')

    logging.info(f"Using model: {api_model} for task {task['id']} trial {trial_id}")

    async with PlaywrightComputer(args, task) as computer:
        for f in os.listdir(args.download_dir):
            os.remove(os.path.join(args.download_dir, f))

        tools = [
            {
                "type": "computer_use_preview", 
                "display_width": args.window_width, 
                "display_height": args.window_height, 
                "environment": "browser"
            }
        ]
        items = [{"role": "user", "content": f"Now given a task: {task['ques']} Please interact with {task['web']} and get the answer. Once you have found the answer, please reply by providing the answer as finished(content='<your_answer>') and exit the task."}]
        it = 0
        raw_logs = [items[0]]
        processed_logs = [items[0]]
        
        while it < args.max_iter:
            retry_count = 0
            max_retries = 20
            while retry_count < max_retries:
                try:
                    if it == 0:
                        img_path = os.path.join(task_dir, f'screenshot{it}.png')
                        screenshot_base64 = await computer.screenshot(path=img_path)
                        input = [{
                            "role": "user", 
                            "content": [
                                {
                                    'type': 'input_text',
                                    'text': f"Now given a task: {task['ques']} Please interact with {task['web']} and get the answer. Once you have found the answer, please reply by providing the answer as finished(content='<your_answer>') and exit the task."
                                },
                                {
                                    'type': 'input_image',
                                    'image_url': f"data:image/png;base64,{screenshot_base64}"
                                }
                            ]
                        }]
                    response = client.responses.create(
                        model=api_model,
                        previous_response_id=response['id'] if it > 0 else None,
                        input=input,
                        tools=tools,
                        reasoning={"summary": "concise"},
                        truncation='auto',
                        temperature=1
                    ).to_dict()

                    for output in response.get('output', []):
                        if output.get('type') == 'computer_call':
                            message_type = 'action'
                            action_no_type = {k: v for k, v in output["action"].items() if k != "type"}
                            action_str = json.dumps(action_no_type)
                            content = {
                                "action": output["action"]["type"],
                                "args": action_str
                            }
                        elif output.get('type') == 'reasoning':
                            message_type = 'thought'
                            content = output["summary"][0]["text"]
                        elif output.get('type') == 'message':
                            message_type = 'final_answer'
                            content = output["content"][0]["text"]

                        processed_output = {
                            "author": "assistant",
                            "message_type": message_type,
                            "content": {
                                "content_type": "text",
                                "parts": [content]
                            }
                        }
                        processed_logs.append(processed_output)
                        
                    raw_logs.extend(response['output'])
                    break
                except Exception as e:
                    retry_count += 1
                    err_name = type(e).__name__
                    print(e)
                    print(f"Retry {retry_count}/{max_retries} for task {task['id']}-{trial_id} after error: {err_name}: {e} with model {api_model}")
                    logging.warning(f"Retry {retry_count}/{max_retries} for task {task['id']}-{trial_id} after error: {err_name}: {e}")
                    await asyncio.sleep(10)

            if "output" not in response:
                raise ValueError("No output from model")
            items += response["output"]

            reached_final_answer = False
            for item in response["output"]:
                img_path = os.path.join(task_dir, f'screenshot{it+1}.png')
                call_output = await handle_item(item, computer, img_path)
                if call_output:
                    input = call_output
                if item['type'] == 'message':
                    reached_final_answer = True
                    break
            
            if reached_final_answer:
                break

            it += 1

        logging.info(f"Task {task['id']} completed in {it + 1} iterations.")
        with open(os.path.join(task_dir, 'output.json'), 'w', encoding='utf-8') as f:
            json.dump(raw_logs, f, ensure_ascii=False, indent=4)
        with open(os.path.join(task_dir, 'interact_messages.json'), 'w', encoding='utf-8') as f:
            json.dump(processed_logs, f, ensure_ascii=False, indent=4)
        logging.info("Task complete")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_file', type=str, default='data/test.json')
    parser.add_argument('--max_iter', type=int, default=5)
    parser.add_argument("--api_key", default="key", type=str)
    parser.add_argument("--api_model", default="gpt-4-vision-preview", type=str)
    parser.add_argument("--output_dir", type=str, default='results')
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max_attached_imgs", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--download_dir", type=str, default="downloads")
    parser.add_argument("--text_only", action='store_true')
    parser.add_argument("--headless", action='store_true')
    parser.add_argument("--save_accessibility_tree", action='store_true')
    parser.add_argument("--force_device_scale", action='store_true')
    parser.add_argument("--window_width", type=int, default=1024)
    parser.add_argument("--window_height", type=int, default=768)
    parser.add_argument("--fix_box_color", action='store_true')
    parser.add_argument("--model", type=str, default='gpt', choices=['gpt', 'uitars'])
    parser.add_argument("--model_name", type=str, default="ByteDance-Seed/UI-TARS-1.5-7B")
    parser.add_argument("--num_trials", type=int, default=1)
    
    args = parser.parse_args()

    current_time = time.strftime("%Y%m%d_%H_%M_%S", time.localtime())
    result_dir = os.path.join(args.output_dir, current_time)
    os.makedirs(result_dir, exist_ok=True)

    with open(args.test_file, 'r', encoding='utf-8') as f:
        tasks = [json.loads(line) for line in f]

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = []
        for task in tasks:
            for i in range(args.num_trials):
                trial_id = i + 1
                futures.append(
                    executor.submit(
                        run_task_sync, task, args, result_dir, trial_id
                    )
                )

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logging.error(f"Error in task execution: {e}")

if __name__ == '__main__':
    main()
    print('End of process')
