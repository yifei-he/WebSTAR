from PIL import Image, ImageDraw, ImageFont
import math
import re
import sys
import os
import json

# Add parent directory to path to allow sibling imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import parse_point, parse_box
from map_action import map_oai_action
import concurrent.futures  # For parallel folder processing


def draw_rectangle(draw, box_coords, width=2, outline_color=(0, 255, 0), is_fill=False, bg_color=(0, 255, 0), transparency=50):  
    if is_fill:
        # Calculate the alpha value based on the transparency percentage
        alpha = int((1 - transparency / 100) * 255)

        # Set the fill color with the specified background color and transparency
        fill_color = tuple(bg_color) + (alpha,)

        draw.rectangle(box_coords, width=width, outline=outline_color, fill=fill_color)
    else:
        draw.rectangle(box_coords, width=width, outline=outline_color)

def draw_circle(draw, center, radius=10, width=2, outline_color=(0, 255, 0), is_fill=False, bg_color=(0, 255, 0), transparency=80):
    # Calculate the bounding box coordinates for the circle
    x1 = center[0] - radius
    y1 = center[1] - radius
    x2 = center[0] + radius
    y2 = center[1] + radius
    bbox = (x1, y1, x2, y2)

    # Draw the circle
    if is_fill:
        # Calculate the alpha value based on the transparency percentage
        alpha = int((1 - transparency / 100) * 255)

        # Set the fill color with the specified background color and transparency
        fill_color = tuple(bg_color) + (alpha,)

        draw.ellipse(bbox, width=width, outline=outline_color, fill=fill_color)
    else:
        draw.ellipse(bbox, width=width, outline=outline_color)

def draw_text_with_bg_box(draw, text, view_port, position, 
                          font_size=24, font_color=(0, 0, 0), 
                          bg_padding=10, bg_color=(179, 238, 58)):

    # Define the font and size for the text
    try:
        font = ImageFont.truetype("./NotoSerifSC-SemiBold.otf", font_size)
    except:
        font = ImageFont.truetype("../NotoSerifSC-SemiBold.otf", font_size)

    # Calculate the bounding box of the text
    text_bbox = draw.textbbox((0, 0), text, font=font)

    # Extract the width and height from the bounding box
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]


    # Define the position of the text based on the specified position parameter
    image_width, image_height = view_port
    if position == "top-left":
        text_x = 5
        text_y = 5
    elif position == "bottom-middle":
        text_x = (image_width - text_width) // 2
        text_y = image_height - text_height - 5
    elif position == "top-middle":
        text_x = (image_width - text_width) // 2
        text_y = 5
    elif position.startswith("point"):
        text_x, text_y = position.split("-")[1:]
        text_x, text_y = int(text_x), int(text_y)
    else:
        print("unsupported position")

    # Draw the background box
    draw_rectangle(
        draw,
        [(text_x, text_y), (text_x + text_width + bg_padding, text_y + text_height + bg_padding)],
        outline_color=(154, 205, 50), 
        is_fill=True, 
        bg_color=bg_color
    )


    # Draw the text on top of the background box
    draw.text((text_x + 2, text_y + 2), text, font=font, fill=font_color)

def draw_index_with_bg_box(draw, text, position, 
                          font_size=18, font_color=(255, 255, 255), 
                          bg_padding=10, bg_color=(66, 119, 56)):  
    # Define the font and size for the text
    try:
        font = ImageFont.truetype("./NotoSerifSC-SemiBold.otf", font_size)
    except:
        font = ImageFont.truetype("../NotoSerifSC-SemiBold.otf", font_size)

    # Calculate the bounding box of the text
    text_bbox = draw.textbbox((0, 0), text, font=font)

    # Extract the width and height from the bounding box
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    # Define the position of the text based on the specified position parameter
    text_x, text_y = position

    # Draw the background box
    draw_rectangle(
        draw,
        [(text_x, text_y), (text_x + text_width + bg_padding, text_y + text_height + bg_padding)],
        outline_color=bg_color, 
        is_fill=True, 
        bg_color=bg_color
    )

    # Draw the text on top of the background box
    draw.text((text_x + 2, text_y), text, font=font, fill=font_color)

def draw_point(draw, center, radius1=3, radius2=6, color=(0, 255, 0)):
    draw_circle(draw, center, radius=radius1, outline_color=color)
    draw_circle(draw, center, radius=radius2, outline_color=color)

def draw_line_with_arrow(draw, start_point, end_point, color=(0, 255, 0), width=3, arrow_size=10):   
    # Draw the line
    x1, y1 = start_point
    x2, y2 = end_point
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    
    # Compute the angle between the line and the x-axis
    angle = math.atan2(y2 - y1, x2 - x1)
    
    # Calculate coordinates for arrowhead
    x_arrow = x2 - arrow_size * math.cos(angle + math.pi/6)
    y_arrow = y2 - arrow_size * math.sin(angle + math.pi/6)
    x_arrow2 = x2 - arrow_size * math.cos(angle - math.pi/6)
    y_arrow2 = y2 - arrow_size * math.sin(angle - math.pi/6)
    
    # Draw arrowhead
    draw.polygon([(x2, y2), (x_arrow, y_arrow), (x_arrow2, y_arrow2)], fill=color) 


def parse_action_string(action_str):
    match = re.match(r"(\w+)\((.*)\)", action_str)
    if not match:
        return None, None
    
    action_type = match.group(1)
    args_str = match.group(2)
    
    args = {}
    # Use regex to find all key-value pairs
    kv_pairs = re.findall(r"(\w+)=(?:'([^']*)'|\"([^\"]*)\")", args_str)
    for key, val1, val2 in kv_pairs:
        args[key] = val1 if val1 else val2

    return action_type, args

def actions_visual(action_group: list, pil_img: Image, ins_cmd: str, color=(255, 48, 48), from_eval=False):
    draw = ImageDraw.Draw(pil_img)

    image_h = pil_img.height
    image_w = pil_img.width

    if isinstance(action_group, str):
        action_group = [action_group]

    name_group = ""
    text_group = ""
    action_centers = []  # Store action center points for zooming
    for i, action_str in enumerate(action_group):
        action_type, args = parse_action_string(action_str)
        if not action_type:
            continue

        name_group += f"{i+1}. {action_type}\n"

        # Draw point for click, right_single, left_double
        if action_type in ["click", "right_single", "left_double"]:
            if 'point' in args:
                point_str = args['point']
                match = re.search(r'<point>(\d+)\s(\d+)</point>', point_str)
                if match:
                    x, y = int(match.group(1)), int(match.group(2))
                    center = (x, y)
                    action_centers.append((x, y, None, None, 'click'))
                    draw_point(draw, center, color=color)
                    draw_index_with_bg_box(draw, str(i+1), (center[0], center[1]-10), font_size=10, bg_padding=2)
            elif 'start_box' in args:
                box_str = args['start_box']
                # Handle both integer and decimal coordinates in start_box format
                match = re.search(r'\(([0-9.]+),([0-9.]+)\)', box_str)
                if match:
                    x, y = float(match.group(1)), float(match.group(2))
                    x, y = int(x), int(y)  # Convert to integers for drawing
                    center = (x, y)
                    action_centers.append((x, y, None, None, 'click'))
                    draw_point(draw, center, color=color)
                    draw_index_with_bg_box(draw, str(i+1), (center[0], center[1]-10), font_size=10, bg_padding=2)

        # Draw drag line
        elif action_type == "drag":
            if 'start_point' in args and 'end_point' in args:
                start_str, end_str = args['start_point'], args['end_point']
                start_match = re.search(r'<point>(\d+)\s(\d+)</point>', start_str)
                end_match = re.search(r'<point>(\d+)\s(\d+)</point>', end_str)
                if start_match and end_match:
                    start_point = (int(start_match.group(1)), int(start_match.group(2)))
                    end_point = (int(end_match.group(1)), int(end_match.group(2)))
                    # For drag, store both points to ensure full range is visible
                    center_x = (start_point[0] + end_point[0]) // 2
                    center_y = (start_point[1] + end_point[1]) // 2
                    action_centers.append((center_x, center_y, start_point, end_point, 'drag'))
                    draw_point(draw, start_point, color=color)
                    draw_line_with_arrow(draw, start_point, end_point, color=color)
                    draw_index_with_bg_box(draw, str(i+1), (start_point[0], start_point[1]-10), font_size=10, bg_padding=2)

        # Draw scroll arrow
        elif action_type == "scroll":
            start_point = (image_w // 2, image_h // 2)
            direction = args.get('direction', 'down')
            scroll_dist = 50
            if direction == 'down':
                end_point = (start_point[0], start_point[1] + scroll_dist)
            elif direction == 'up':
                end_point = (start_point[0], start_point[1] - scroll_dist)
            elif direction == 'right':
                end_point = (start_point[0] + scroll_dist, start_point[1])
            elif direction == 'left':
                end_point = (start_point[0] - scroll_dist, start_point[1])
            
            # For scroll, store both points to show the full scroll range
            center_x = (start_point[0] + end_point[0]) // 2
            center_y = (start_point[1] + end_point[1]) // 2
            action_centers.append((center_x, center_y, start_point, end_point, 'scroll'))
            draw_point(draw, start_point, color=color)
            draw_line_with_arrow(draw, start_point, end_point, color=color)

        # Accumulate text for 'type' action
        elif action_type == "type":
            if 'content' in args:
                text = args['content'].replace("\\n", "\n")
                text_with_tabs = text.replace('\n', '\t')
                text_group += f"{i+1}. {text_with_tabs}\n"
        
        elif action_type == 'hotkey':
            text_group = args['key']
        
        elif action_type == 'finished':
            text_group = args['content']
            
    # Draw action_names
    draw_text_with_bg_box(
        draw,
        text=name_group, 
        view_port=(image_w, image_h),
        position = "top-left", 
        font_size=16
    )

    # Draw text
    if text_group != "":
        draw_text_with_bg_box(
            draw,
            text=text_group, 
            view_port=(image_w, image_h),
            position = "bottom-middle", 
            font_size=16
        )

    # Draw instruction
    # draw_text_with_bg_box(
    #     draw,
    #     text=ins_cmd, 
    #     view_port=(image_w, image_h),
    #     position = "top-middle", 
    #     font_size=16
    # )

    return pil_img, action_centers


def create_zoomed_action_image(original_img: Image, action_center_info, zoom_size=200, color=(255, 48, 48)):
    """
    Create a zoomed-in image around the action center point with annotations.
    
    Args:
        original_img: PIL Image object
        action_center_info: tuple (center_x, center_y, start_point, end_point, action_type)
        zoom_size: int, size of the zoomed image (default 200x200)
        color: tuple, color for annotations
    
    Returns:
        PIL Image object of size zoom_size x zoom_size with annotations
    """
    if not action_center_info:
        # If no action center, return a resized version of the original
        return original_img.resize((zoom_size, zoom_size))
    
    center_x, center_y, start_point, end_point, action_type = action_center_info
    half_size = zoom_size // 2
    
    # For drag and scroll actions, ensure we capture the full range
    if action_type in ['drag', 'scroll'] and start_point and end_point:
        # Calculate bounds that include both start and end points
        min_x = min(start_point[0], end_point[0]) - 50  # Add padding
        max_x = max(start_point[0], end_point[0]) + 50
        min_y = min(start_point[1], end_point[1]) - 50
        max_y = max(start_point[1], end_point[1]) + 50
        
        # Ensure the crop area is at least zoom_size x zoom_size
        width_needed = max(zoom_size, max_x - min_x)
        height_needed = max(zoom_size, max_y - min_y)
        
        # Center the crop area
        center_crop_x = (min_x + max_x) // 2
        center_crop_y = (min_y + max_y) // 2
        
        left = max(0, center_crop_x - width_needed // 2)
        top = max(0, center_crop_y - height_needed // 2)
        right = min(original_img.width, center_crop_x + width_needed // 2)
        bottom = min(original_img.height, center_crop_y + height_needed // 2)
    else:
        # For click actions, use the center point
        left = max(0, center_x - half_size)
        top = max(0, center_y - half_size)
        right = min(original_img.width, center_x + half_size)
        bottom = min(original_img.height, center_y + half_size)
    
    # Crop the image
    cropped = original_img.crop((left, top, right, bottom))
    
    # Resize to target size if needed
    if cropped.size != (zoom_size, zoom_size):
        cropped = cropped.resize((zoom_size, zoom_size))
    
    # Add annotations to the cropped image
    draw = ImageDraw.Draw(cropped)
    
    # Calculate the offset for coordinates in the cropped image
    if action_type in ['drag', 'scroll'] and start_point and end_point:
        # For resized images, calculate scaling factors
        scale_x = zoom_size / (right - left)
        scale_y = zoom_size / (bottom - top)
        
        # Convert original coordinates to cropped image coordinates
        start_x = int((start_point[0] - left) * scale_x)
        start_y = int((start_point[1] - top) * scale_y)
        end_x = int((end_point[0] - left) * scale_x)
        end_y = int((end_point[1] - top) * scale_y)
        
        # Draw the annotation
        draw_point(draw, (start_x, start_y), color=color)
        draw_line_with_arrow(draw, (start_x, start_y), (end_x, end_y), color=color)
        draw_index_with_bg_box(draw, "1", (start_x, max(0, start_y-10)), font_size=10, bg_padding=2)
    else:
        # For click actions
        scale_x = zoom_size / (right - left)
        scale_y = zoom_size / (bottom - top)
        
        click_x = int((center_x - left) * scale_x)
        click_y = int((center_y - top) * scale_y)
        
        draw_point(draw, (click_x, click_y), color=color)
        draw_index_with_bg_box(draw, "1", (click_x, max(0, click_y-10)), font_size=10, bg_padding=2)
    
    return cropped

def process_folder_visualization(file_dir):
    """Process a single folder for data visualization."""
    print(f'Processing folder: {file_dir}')
    trajectory_path = os.path.join(file_dir, "output.json")
    if not os.path.exists(trajectory_path):
        print(f'Skipping {file_dir}: output.json not found')
        return

    with open(trajectory_path, 'r') as f:
        trajectory = json.load(f)

    ins_cmd = trajectory[0]['content']
    action_id = 0
    os.makedirs(os.path.join(file_dir, 'annotated_screenshots'), exist_ok=True)
    os.makedirs(os.path.join(file_dir, 'zoomed_screenshots'), exist_ok=True)

    for i, action in enumerate(trajectory):
        if i == 0:
            continue
        if action['type'] == 'computer_call' or action['type'] == 'message':
            if action['type'] == 'message':
                action['action'] = {
                    'type': 'finished',
                    'content': action['content'][0]['text']
                }
            action_str = map_oai_action(action['action'], follow_prompt=True)
            pil_img = Image.open(os.path.join(file_dir, f"screenshot{action_id}.png"))
            vis_img, action_centers = actions_visual([action_str], pil_img.copy(), ins_cmd)
            vis_img.save(os.path.join(file_dir, 'annotated_screenshots', f"screenshot{action_id}.png"))
            if action_centers:
                info = action_centers[0]
                zoomed_img = create_zoomed_action_image(pil_img, info, zoom_size=200)
                zoomed_img.save(os.path.join(file_dir, 'zoomed_screenshots', f"screenshot{action_id}.png"))
            action_id += 1
    print(f'Completed folder: {file_dir}')


main_folder = '<path to the folder containing the trajectories>'
subfolders = [f.path for f in os.scandir(main_folder) if f.is_dir() and os.path.exists(os.path.join(f.path, "output.json")) and not os.path.exists(os.path.join(f.path, "annotated_screenshots"))]

max_workers = min(64, len(subfolders))
with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(process_folder_visualization, d): d for d in subfolders}
    for future in concurrent.futures.as_completed(futures):
        folder = futures[future]
        try:
            future.result()
        except Exception as e:
            print(f'Error processing folder {folder}: {e}')