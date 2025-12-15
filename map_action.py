import re
import json

COMPUTER_USE_DOUBAO = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
```
Thought: ...
Action: ...
```

## Action Space

click(point='<point>x1 y1</point>')
left_double(point='<point>x1 y1</point>')
right_single(point='<point>x1 y1</point>')
drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')
hotkey(key='ctrl c') # Split keys with a space and use lowerelif action_type ==. Also, do not use more than 3 keys in one hotkey action.
type(content='xxx') # Use escape characters \\', \\\", and \\n in content part to ensure we can parse the content in normal python string format. If you want to submit your input, use \\n at the end of content. 
scroll(point='<point>x1 y1</point>', direction='down or up or right or left') # Show more information on the `direction` side.
wait() #Sleep for 5s and take a screenshot to check for any changes.
finished(content='xxx') # Use escape characters \\', \\", and \\n in content part to ensure we can parse the content in normal python string format.


## Note
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

"""


def map_aguvis_action(action, window_height, window_width):
    # pyautogui.click(x=x1, y=y1) -> click(point='<point>x1 y1</point>')
    # pyautogui.write(message='xxx') -> type(content='xxx')
    # pyautogui.scroll(0.46) -> scroll(point='<point>x1 y1</point>', direction='down or up or right or left')
    if action.startswith('pyautogui.click'):
        # Extract x and y values using regex
        pattern = r"pyautogui\.click\(x=([0-9.]+),\s*y=([0-9.]+)\)"
        match = re.match(pattern, action)
        if match:
            x1, y1 = match.groups()
        x1 = round(float(x1) * window_width)
        y1 = round(float(y1) * window_height)
        
        return f'click(start_box=\'({x1},{y1})\')'
        # return f'click(point=\'<point>{x1} {y1}</point>\')'
    elif action.startswith('pyautogui.write'):
        # Extract message argument using regex
        pattern = r"pyautogui\.write\(message=['\"](.*?)['\"]\)"
        match = re.match(pattern, action)
        if match:
            content = match.group(1)
            return f"type(content='{content}')"
    elif action.startswith('pyautogui.scroll'):
        print(action.split('(')[1].split(')')[0])
        direction = 'down' if float(action.split('(')[1].split(')')[0]) > 0 else 'up'
        return f'scroll(direction=\'{direction}\')'
    elif action.startswith('browser.select_option'):
        # Extract x and y values using regex
        pattern = r"browser\.select_option\(x=([0-9.]+),\s*y=([0-9.]+),\s*value='[^']*'\)"
        match = re.match(pattern, action)
        if match:
            x1, y1 = match.groups()
            x1 = round(float(x1) * window_width, 3)
            y1 = round(float(y1) * window_height, 3)
            return f'click(start_box=\'({x1},{y1})\')'
    else:
        print(f'Unknown action: {action}')
        

def map_oai_action(action, follow_prompt=False):
    """
    Map OAI action dict to UITARS format as specified in COMPUTER_USE_DOUBAO.
    """
    action_type = action['type']

    if action_type == "click":
        x, y = action['x'], action['y']
        button = action['button']
        # # UITARS: click(point='<point>x1 y1</point>'), left_double, right_single
        if follow_prompt:
            # Follow the prompt for button click
            if button == "left":
                return f"click(point=\'<point>{x} {y}</point>\')"
            elif button == "right":
                return f"right_single(point=\'<point>{x} {y}</point>\')"
            elif button == "double":
                return f"left_double(point=\'<point>{x} {y}</point>\')"
            else:
                # Default to left click
                return f'click(point=\'<point>{x} {y}</point>\')'
        else:
            if button == "left":
                return f"click(start_box=\'({x},{y})\')"
            elif button == "right":
                return f"right_single(start_box=\'({x},{y})\')"
            elif button == "double":
                return f"left_double(start_box=\'({x},{y})\')"
            else:
                # Default to left click
                return f'click(start_box=\'({x},{y})\')'
    
    elif action_type == "move":
        x, y = action['x'], action['y']
        if follow_prompt:
            return f"click(point=\'<point>{x} {y}</point>\')"
        else:
            return f"click(start_box=\'({x},{y})\')"

    elif action_type == "scroll":
        x, y = action['x'], action['y']
        scroll_x, scroll_y = action['scroll_x'], action['scroll_y']
        # UITARS: scroll(point='<point>x1 y1</point>', direction='down or up or right or left')
        # Determine direction
        if abs(scroll_y) > abs(scroll_x):
            direction = "down" if scroll_y > 0 else "up"
        else:
            direction = "right" if scroll_x > 0 else "left"
        if follow_prompt:
            return f"scroll(point=\'<point>{x} {y}</point>\', direction='{direction}')"
        else:
            return f"scroll(direction='{direction}', start_box=\'({x},{y})\')"

    elif action_type == "keypress":
        keys = action['keys']
        # UITARS: hotkey(key='ctrl c') (space separated, lower case, max 3 keys)
        keys_str = " ".join([k.lower() for k in keys])[:30]
        return f"hotkey(key='{keys_str}')"

    elif action_type == "type":
        text = action['text']
        # Escape characters as per UITARS spec
        text = text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n")
        return f"type(content='{text}')"

    elif action_type == "wait":
        # UITARS: wait()
        return "wait()"

    elif action_type == "screenshot":
        # UITARS: No direct action, just ignore or return empty
        return ""

    elif action_type == "drag":
        # UITARS: drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')
        start_x, start_y = action['path'][0]['x'], action['path'][0]['y']
        end_x, end_y = action['path'][1]['x'], action['path'][1]['y']
        # start_x, start_y = action['start_x'], action['start_y']
        # end_x, end_y = action['end_x'], action['end_y']
        return f"drag(start_point='<point>{start_x} {start_y}</point>', end_point='<point>{end_x} {end_y}</point>')"

    elif action_type == "finished":
        # UITARS: finished(content='xxx')
        content = action['content']
        content = content.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n")
        return f"finished(content='{content}')"

    else:
        # Unknown action
        return f"# Unknown action: {action_type} {action}"


def map_processed_oai_action(action, follow_prompt=False):
    """
    Map OAI action dict to UITARS format as specified in COMPUTER_USE_DOUBAO.
    """
    action_type = action['action']
    action_args = json.loads(action['args'])

    if action_type == "click":
        x, y = action_args['x'], action_args['y']
        button = action_args['button']
        # # UITARS: click(point='<point>x1 y1</point>'), left_double, right_single
        if follow_prompt:
            # Follow the prompt for button click
            if button == "left":
                return f"click(point=\'<point>{x} {y}</point>\')"
            elif button == "right":
                return f"right_single(point=\'<point>{x} {y}</point>\')"
            elif button == "double":
                return f"left_double(point=\'<point>{x} {y}</point>\')"
            else:
                # Default to left click
                return f'click(point=\'<point>{x} {y}</point>\')'
        else:
            if button == "left":
                return f"click(start_box=\'({x},{y})\')"
            elif button == "right":
                return f"right_single(start_box=\'({x},{y})\')"
            elif button == "double":
                return f"left_double(start_box=\'({x},{y})\')"
            else:
                # Default to left click
                return f'click(start_box=\'({x},{y})\')'
    
    elif action_type == "move":
        x, y = action_args['x'], action_args['y']
        if follow_prompt:
            return f"click(point=\'<point>{x} {y}</point>\')"
        else:
            return f"click(start_box=\'({x},{y})\')"

    elif action_type == "scroll":
        x, y = action_args['x'], action_args['y']
        scroll_x, scroll_y = action_args['scroll_x'], action_args['scroll_y']
        # UITARS: scroll(point='<point>x1 y1</point>', direction='down or up or right or left')
        # Determine direction
        if abs(scroll_y) > abs(scroll_x):
            direction = "down" if scroll_y > 0 else "up"
        else:
            direction = "right" if scroll_x > 0 else "left"
        if follow_prompt:
            return f"scroll(point=\'<point>{x} {y}</point>\', direction='{direction}')"
        else:
            return f"scroll(direction='{direction}', start_box=\'({x},{y})\')"

    elif action_type == "keypress":
        keys = action_args['keys']
        # UITARS: hotkey(key='ctrl c') (space separated, lower case, max 3 keys)
        keys_str = " ".join([k.lower() for k in keys])[:30]
        return f"hotkey(key='{keys_str}')"

    elif action_type == "type":
        text = action_args['text']
        # Escape characters as per UITARS spec
        text = text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n")
        return f"type(content='{text}')"

    elif action_type == "wait":
        # UITARS: wait()
        return "wait()"

    elif action_type == "screenshot":
        # UITARS: No direct action, just ignore or return empty
        return ""

    elif action_type == "drag":
        # UITARS: drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')
        start_x, start_y = action_args['path'][0]['x'], action_args['path'][0]['y']
        end_x, end_y = action_args['path'][1]['x'], action_args['path'][1]['y']
        # start_x, start_y = action['start_x'], action['start_y']
        # end_x, end_y = action['end_x'], action['end_y']
        return f"drag(start_point='<point>{start_x} {start_y}</point>', end_point='<point>{end_x} {end_y}</point>')"

    elif action_type == "finished":
        # UITARS: finished(content='xxx')
        content = action_args['content']
        content = content.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n")
        return f"finished(content='{content}')"

    else:
        # Unknown action
        return f"# Unknown action: {action_type} {action}"
