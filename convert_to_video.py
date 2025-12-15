import base64
import code
import os
import pickle
import shutil
import textwrap
import time
from glob import glob
from io import BytesIO

import cv2
import matplotlib.pyplot as plt
import numpy as np
from IPython.display import clear_output, display
from matplotlib.gridspec import GridSpec
from PIL import Image
import json

def resize_and_pad(img, target_size=(1920, 1080)):
    target_w, target_h = target_size
    h, w = img.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h))
    pad_w = target_w - new_w
    pad_h = target_h - new_h
    top = pad_h // 2
    bottom = pad_h - top
    left = pad_w // 2
    right = pad_w - left
    color = [255, 255, 255]  # white padding
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return padded


def convo_to_video(convo, image_folder, video_name="output.mp4", frame_folder="temp_figs"):
    # Extract Base64 frames from `data.messages`
    base64_frames_2 = []
    # messages = convo[1:]
    messages = convo
    total_len = len(messages)
    cmd = ""

    # Create directories to save results
    save_dir = frame_folder
    os.makedirs(save_dir, exist_ok=True)

    # clean folder
    shutil.rmtree(save_dir)
    os.makedirs(save_dir, exist_ok=True)

    time.sleep(0.5)  # Pause for visibility
    img_pil = None
    cmd = None

    for i in range(total_len):  # Process messages in pairs

        if i < len(messages):# and messages[i]["role"] == "user":
            try:
                img_pil = Image.open(f'{image_folder}/screenshot{i//2}.png')
            # if no file found, make img_pil a blank image
            except FileNotFoundError:
                print(f"Warning: screenshot{i//2}.png not found, using the previous image.")
                pass
                # img_pil = Image.new('RGB', (1920, 1080), color='white')

        # Second video frame
        if i > 1 and i < len(messages) and messages[i]["from"] == "assistant":
            try:
                cmd = messages[i]['value']
            except AttributeError:
                pass

        # Ensure long text does not distort the figure
        MAX_LENGTH = 500

        if i == 0:
            cmd = "USER Prompt: \n" + str(messages[i]['content'])
        elif i == 1:
            cmd = "Computer Initialization"

        wrapped_cmd = "\n".join(textwrap.wrap(str(cmd)[:MAX_LENGTH], width=30)) + (
            "..." if len(str(cmd)) > MAX_LENGTH else ""
        )
        # wrapped_cmd = str(cmd)

        if i >= (len(messages) - 1):
            wrapped_cmd += "\n TASK COMPLETED: SUCCESS"

        if i < 2 or i == total_len - 1:
            # Create a figure with two rows: Videos (top) and Text (bottom)
            fig = plt.figure(figsize=(24, 12))
            plt.text(0.05, 0.5, cmd, fontsize=20, ha="left", va="center", wrap=True)
            plt.axis("off")
        else:
            # Create a figure with two rows: Videos (top) and Text (bottom)
            fig = plt.figure(figsize=(24, 12))
            gs = GridSpec(1, 2, width_ratios=[4, 2], wspace=0.0)  # Grid layout

            # Left: First Video
            ax_img2 = fig.add_subplot(gs[0, 0])
            if img_pil:
                ax_img2.imshow(img_pil)
            ax_img2.axis("off")

            # Right: Second Video
            ax_text = fig.add_subplot(gs[0, 1])
            ax_text.text(0.15, 0.5, wrapped_cmd, fontsize=20, ha="left", va="center", wrap=True)
            ax_text.axis("off")

        # Save the full display
        result_path = os.path.join(save_dir, f"display_step_{i+1}.png")
        fig.savefig(result_path, bbox_inches="tight", dpi=150)  # Save figure
        plt.close()

    # Folder containing saved frames
    output_video = video_name

    # Get all image file paths and sort numerically
    frame_files = sorted(
        glob(os.path.join(frame_folder, "display_step_*.png")),
        key=lambda x: int(x.split("_")[-1].split(".")[0]),
    )

    # Check if there are frames to process
    if not frame_files:
        print("No frames found in the folder. Please check your directory.")
        exit()

    # Read first frame to get video size
    first_frame = cv2.imread(frame_files[0])
    if first_frame is None:
        print("Error: Unable to read the first frame.")
        exit()

    height, width, _ = first_frame.shape

    # Define video writer explicitly using 'mp4v' for MP4 format
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # MP4 codec
    fps = 1  # Set FPS (adjustable)
    # After reading the first frame and before creating the VideoWriter:
    target_size = (1920, 1080)
    video_writer = cv2.VideoWriter(output_video, fourcc, fps, target_size)

    for frame_file in frame_files:
        frame = cv2.imread(frame_file)
        if frame is None:
            print(f"Warning: Skipping unreadable frame {frame_file}")
            continue
        if frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        frame = resize_and_pad(frame, target_size)
        video_writer.write(frame)

    # Release resources
    video_writer.release()
    print(f"Video successfully saved as {output_video}") 

traj_dir = '<path to the trajectory directory>'

with open(f"{traj_dir}/output_thought_judge_o4mini.json", "r", encoding="utf-8") as f:
    convo = json.load(f)['conversations']

convo_to_video(
    convo, image_folder=traj_dir + '/annotated_screenshots', video_name=f"{traj_dir}/video/amazon-21.mp4", frame_folder=f"{traj_dir}/video"
)  
