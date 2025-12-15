USER_PROMPT = """TASK: <task>
Previous trajectory: <previous_actions>
Current action: <cur_action>"""

GPT_THOUGHT_AUGMENTATION = """You are given the action and thought of the previous several steps of a web browsing agent, the current screenshot annotated with the current action, and a action dictionary describing the specific parameters of the current action. Optionally, you will be given previous screenshots about previous states. The goal is to output the detailed thought process that leads to the current action. 

The action space of the assistant includes:
- click(x, y) where (x, y) are the coordinates of the element to click on.
- scroll(x, y, scroll_x, scroll_y) where (x, y) are the coordinates of the element to scroll on and (scroll_x, scroll_y) are the scroll amounts in pixels.
- keypress(keys) where keys is a string of keys to press.
- type(text) where text is a string to type. To type in a searchbox, the assistant needs to first click on it, then type.
- wait
- screenshot
- final_answer(answer) where answer is the final answer to the user task.

Your response should contain the following components:
1. **Situation Description**: Describe your observation of the screenshot in detail. Do not only focus on the regions where the action takes place. Rather, identify key areas and elements that contribute to the decision-making process, such as relevant text, images, or layout features that inform the next steps. Then, arrive at the decision to interact with certain area of interest, and relate it to the goal to achieve. 
2. **Reasoning Alignment**: Ensure your reasoning aligns with the current action and how it contributes to achieving the goal, but avoid using the current action or the annotation on the screenshot as reasoning support, as they represent hindsight rather than predictive insight. Think about the previous steps and how they lead to the current action. Do not output completely equivalent reasoning to the current action even if it is the same action as previous actions. Rather, think about why this action is repeated, and how it is different from previous attempts.
3. **Actionable Instruction**: Conclude with a clear, actionable instruction in one sentence, but no need to use any specific format. Make sure that the instruction matches the provided action.

Important notes:
1. Aim to reason through the task as if solving it, rather than simply reflecting on the outcome. Use the first-person perspective to represent the annotator's thought process.
2. The actions are not necessarily optimal or correct. STICK TO THE GIVEN CURRENT ACTION AND DO NOT COME UP WITH YOUR OWN ACTION or impose your idea about what is the correct action in the current step. Instead, focus on finding rationale and reasoning for the given action.
3. The screenshots are annotated with the actions. On the top left corner, there is the action label, such as click, scroll, wait, type etc. For clicking, there is a red target dot with green label, indicating the clicking position. Do not confuse it with other red elements in the screenshot. For scroll, there is a red target dot for the scrolling centroid, and a red arrow points to the scrolling direction. For drag, there is a red arrow pointing towards the direction of drag, with the dragging start point annotated by a green label.
4. The assistant can only perform one action in each step.
5. If the assistant is on the first step, provide a brief overview of the task and decompose it into smaller steps.
6. The effect of the current action is NOT reflected in the latest screenshot, as the assistant has not executed the action yet. The latest screenshot is just a snapshot of the current state before the action is executed.
7. For final answer, the action is "finished", but the answer shown on the annotated screenshot may be truncated, so focus on the content of the answer provided in text. The agent will finish the task after this step, so do not plan for any further steps or actions.

There is no need to explicitly state the titles of the components, just write them in one paragraph."""

GPT_STEP_JUDGE = """
You are a critic helping an assistant, and you are evaluating the expected value of an assistant proposed next action in leading to successful task completion of a given user task AND being the most promising next action out of all possible next assistant actions (no regrets).

The action space of the assistant includes:
- click(x, y) where (x, y) are the coordinates of the element to click on.
- scroll(x, y, scroll_x, scroll_y) where (x, y) are the coordinates of the element to scroll on and (scroll_x, scroll_y) are the scroll amounts in pixels.
- keypress(keys) where keys is a string of keys to press.
- type(text) where text is a string to type. To type in a searchbox, the assistant needs to first click on it, then type.
- wait
- screenshot
- final_answer(answer) where answer is the final answer to the user task.

The user will give you a user task and assistant system message, the latest (up to MAX_IMAGES) screenshots from the assistant trying to complete the user task, and the proposed next action from the assistant along with zoomed in sections of the latest screenshot indicating which elements the assistant proposing to localize and interact with (if any). 

IMPORTANT: In each step, the assistant can only perform ONE of the above action. Your proposed next step can also only take from the above action space.

The screenshots are annotated with the proposed action, and the annotations often consist of red circles, red arrows or green labels. Do not confuse the annotation with other elements in the screenshot.
- On the top left corner, there is the green action label, such as click, scroll, wait, type etc. NOTE: This is NOT the actual place that action takes place, but just a label for the action.
- For clicking, there is a red target circle with green label, indicating the clicking position. 
- For scroll, there is a red target circle for the scrolling centroid, and a red arrow points to the scrolling direction. 
- For drag, there is a red arrow pointing towards the direction of drag, with the dragging start point annotated by a red target circle and a green label. For sliders, PAY PARTICULAR ATTENTION about the drag direction and which knob the assistant is actually dragging, as there may be multiple knobs on the slider.

Note: 
- While the assistant must follow the assistant system message instructions, the proposed next action you must evaluate contains only the action itself without any discussion or reward that would normally be in the proposed next assistant response. You just need to evaluate the expected value of executing the proposed next action in leading to successful task completion of the user task AND being the most promising next action.
- The effect of the current action is NOT reflected in the latest screenshot, as the assistant has not executed the action yet. The latest screenshot is just a snapshot of the current state before the action is executed.
- The assistant only interacts with the screenshot as well. This means that for actions like drag, it will not get real-time feedback on the drag effect, and it will only see the final state after the drag is completed. If the dragging knob and direction is correct, but the coordinate is off, still give it a score over 5.
- The step of providing the final answer will not have screenshot associated. Only evaluate the textual response.

Your goal is to analyze the latest screenshot, decompose and define the task completion success criteria, analyze the current assistant progress, re-state your understanding of the proposed next assistant action, simulate rollouts of likely future states and actions, analyze the assistant's best next alternative actions, evaluate the expected value of the proposed response in completing the user task and being the most promising next action, and conclude with a final expected value for the proposed response.

Specifically, your task is to:
1) Latest Screenshot Analysis - First, thoroughly describe the screenshots and then what specifically the annotations are. You are also provided a zoomed-in screenshot (if any) to focus on the area that the assistant action takes place. Focus on the annotation types that are described above. Prioritize objectivity and accuracy over brevity. If the center point of the circles are not directly hovering over any element, just say that the red circle seems to not be hovering over any element. Be strict because the red circles is exactly where the cursor will move to, so if it's close to neighboring elements but not directly on top of them, then it's not on those neighboring elements. However, the red circles do not need to be at the center of the element.

Then, describe the latest computer screenshot and all relevant elements on the screenshot to build strong contextual understanding of the latest screenshot and what the latest action was. 

2) Success and rejection criteria - Decompose the user task into different parts that need to be completed and validated to consider the task as completed (success criteria), and what factors would mean that the task is not completed successfully (rejection critera). Ensure your success and rejection criteria are very strict to maximize user satisfaction of task completion. You **MUST** follow the assistant system message rules though such as no taking irreversible actions without user approval, etc. as the assistant must still abide by these and the expected values are based on user satisfaction of task completion.

3) Progress Analysis - Go through EACH screenshot to figure out exactly what steps the assistant was taking and analyze if any of the success criteria were completed and what's still left to be completed. Note: you must cover every screenshot of what action likely took place so you don't mistakenly think part of the success criteria was not completed when it was actually completed.

4) Proposed Next Assistant Action - a) re-state your understanding of the proposed next assistant action based on the current state analysis and the proposed next assistant action AND b) if the proposed next assistant action makes sense or not and why based on the progress analysis and success and rejection criteria. If the current state is already wrong, and the assistant fixes a previous mistake, the score should be higher than 5. For the dragging action, if the dragging knob and direction is correct, but the coordinate is off, still give it a score over 5. AND c) if the proposed next assistant action is only partially correct and does not fully make sense, say that the expected value should be no higher than 5, otherwise if the action makes full sense and is fully correct, say that the expected value should be higher than 5. Note that for clicking, there is no need to click at exactly the center of the web element. As long as it is on the web element and is not too far from center, it should be treated as correct. You should restate the proposed action in plain language.

5) Simulation - In a few paragraphs, rollout the most likely a) best case potential gain and b) worst case riskiest risk of potential future state(s) and action(s) and their likelihoods based on the current state after the assistant executes the proposed response as its next action. 

6) Alternatives Analysis - a) Generate the assistant's best next alternative actions based on the success and rejection criteria and the progress analysis and current screenshot (IMPORTANT: the alternative action must be ONE action from the aforementioned action space), b) checking if the alternative actions' elements (if any) are currently in the current screenshot, c) do rollouts for each of those actions. Then d) do a quick comparison analysis based on the current state and screenshot between each alternative and the proposed action to determine if the alternative action is better or worse than the proposed action in terms of successful task completion and user satisfaction. This is to determine if the proposed action is the current most promising next action out out the possible next assistant actions. Make sure you double check the latest screenshot to ground your analysis and alternatives evaluation. e) If the proposed action is STRICTLY worse than one of the alternative actions that can be taken, you MUST say that the proposed action should have an expected value no higher than 5. Otherwise, if the proposed action is better than or equal to the correctness of the alternative actions that can be taken, then you should say that the proposed action should have an expected value higher than 5.

7) Evaluation - According to the success criteria, current state analysis, alternatives analysis, and simulation results, reason what would be an appropriate expected value score and why. An expected value score of 0 = the lowest expected value, negative progress like taking an irreversible unwanted action that will GUARANTEE TASK FAILURE, and that any other action is better than the proposed action. An expected value score of 10 = the highest reward, positive progress like taking a desired action that will guarantee perfect task completion, and that no other action can possibly be better than the proposed action (no regrets). Actions that do not fully make sense MUST have scores below 5. Only actions that FULLY make sense can have scores above 5. It is possible that the current step does not directly contribute to the task completion, but fixes a previously made mistake. In that case, the score should also be above 5. 

8) Expected Value - Provide a final answer for the expected value score from 0 to 10.

User task: USER_TASK

Proposed next assistant action: PROPOSED_NEXT_ASSISTANT_ACTION

Assistant system message: ASSISTANT_SYSTEM_MESSAGE

Respond STRICTLY in the following format (no fancy formatting, just vanilla text like the following):
Latest Screenshot Analysis: <first describe the zoomed in images (if any) and what the red circles are centered on in the last given screenshot and zoomed in images. if there are red circles, you **MUST** say "Updated proposed next assistant action: ..." and fill in the redacted element descriptions based on exactly what the red circles are centered on even if the element descriptions of where the red circles are seem wrong. if it's not directly centered on anything, you MUST update the element description to "Not centered directly on any element". Then, describe the latest screenshot in great depth to build extremely strong contextual understanding of the latest screenshot and what the current state is.>

Success and rejection criteria: <decompose the user task into different parts that need to be completed and validated to consider the task as completed (success criteria), and what factors would mean that the task is not completed successfully (rejection critera). ensure your success and rejection criteria are very strict to maximize user satisfaction of task completion.>

Progress analysis: <go through EACH screenshot to figure out exactly what steps the assistant have taken and analyze which of the success criteria are completed and what parts of the success criteria still need to be completed.>

Proposed action: <a) restate your understanding of the proposed next assistant action based on the latest screenshot analysis and current state analysis and the proposed next assistant action AND b) if the proposed next assistant action makes sense or not and why based on the progress analysis and success and rejection criteria AND c) if the proposed next assistant action is only partially correct and does not fully make sense, say that the expected value should be no higher than 5, otherwise if the action makes full sense and is fully correct, say that the expected value should be above 5. if localize_and_unnormalize is in the action, you MUST reference the red circles and zoomed in images from the latest screenshot analysis as that is ground truth as elements that WILL be interacted with.>

Simulation: <rollout of the most likely a) best case and potential gain and b) worst case and riskiest risk possibilities of future states and actions and their probabilities of occuring in terms of successful task completion and user satisfaction. specifically, if the assistant action executes the proposed action as intended, what's the best thing that could happen and what's the worst thing that could happen in terms of successful task completion and user satisfaction.>

Alternatives analysis: <a) analysis on what the assistant's best alternative actions currently are, b) checking if the alternative actions' elements (if any) are currently in the current screenshot, c) rolling them out for comparison of what the true most promising next action is, d) marking each alternative as better or worse than the proposed action based on the current state and screenshot in terms of successful task completion and user satisfaction, and e) saying if the proposed action is strictly worse than any of the alternative actions or not AND saying that "the expected value score should be less than 5" if the proposed action is strictly worse than one of the alternative actions or "the expected value score should be more than 5" if the proposed action is better than or equal to the correctness of all the alternative actions>

Evaluation: <according to the success and rejection criteria, progress analysis, proposed action, simulation results, and alternatives analysis, reason what would be an appropriate expected value of leading to successful task completion of the user task AND being the most promising next action out of all possible next actions and why. actions that do not fully make sense MUST have negative scores.>

Expected value: <based on the evaluation result, provide an expected value of type int from 0 to 10, in the format of `<int>` in a single line to reflect the expected value>
"""

GPT_STEP_JUDGE_REVISED = """

You are a critic helping evaluate the next action of a computer-use agent. Your goal is to judge the expected value of the proposed next action based on:

1. Whether it meaningfully contributes to successful completion of the user’s task.
2. Whether it is the most promising possible next action from the assistant's available action space — i.e., a "no-regret" choice.

You will be given:
- A USER_TASK: what the user wants the assistant to do.
- A sequence of prior screenshots (including any zoomed-in crops), each corresponding to one earlier assistant action.
- A single PROPOSED_NEXT_ASSISTANT_ACTION.
- The latest full-screen screenshot and zoomed-in image (if any), annotated with red/green visual guides for where the proposed action is targeting.

------------------------
Assistant action space includes:
- `click(x, y)`: click at coordinates (x, y)
- `scroll(x, y, scroll_x, scroll_y)`: scroll at (x, y) by the pixel amounts (scroll_x, scroll_y)
- `keypress(keys)`: press keys like "Enter", "Ctrl+A", etc.
- `type(text)`: type a string (must click on an input first)
- `wait`: wait for page to change or update
- `screenshot`: take a new screenshot
- `final_answer(answer)`: output the final answer to the user (no screenshot will be given with this)

------------------------
SCREENSHOT ANNOTATION CONVENTIONS:
- The top-left green label (e.g. “click”) is the **type of action**, not where it occurs.
- The **red circle** is the exact target position for a click, scroll, or drag — the assistant’s mouse cursor will land there. It must be on the correct element.
- For **scroll actions**, a red arrow shows scroll direction, and red circle marks scroll origin.
- For **drag actions**, red circle marks the start point, red arrow marks direction.
- For sliders, the specific knob dragged and direction both matter. Always examine drag annotations carefully.

IMPORTANT: The assistant has **not yet executed** the proposed action. You must judge its value **before it runs**, based on what is visible on screen.

------------------------
Your task is to follow the 8 steps below, output your analysis for each of the steps, then return an integer score in the format `Expected value: <int>`, where:

- 0 = guaranteed task failure or irreversible error
- 10 = guaranteed task success and no better alternative action exists
- 5 = a borderline step that is either only partially correct or may be outperformed by a better next action
------------------------

1. **Latest Screenshot Analysis**  
   - Then analyze the **latest full screenshot**: describe relevant UI elements visible, current screen state, and the annotation overlays (red circles/arrows, green labels).  
   - Describe any **zoomed-in** image(s). For each, examine where the red circle is at: if it's not directly on an interactive element, say so explicitly (e.g. “not centered on any element”). If a web element (such as a search button) is small, it could be partially obscured by the red circle, pay close attention to such details.
   - If red annotations suggest a different intent than the textual action description, update the interpretation accordingly.  

2. **Success and Rejection Criteria**  
   - Break down the USER_TASK into **specific, verifiable success conditions**.  
   - Define what would count as incorrect or incomplete (rejection criteria).  

3. **Progress Analysis**  
   - Go through EACH screenshot and earlier action.  
   - For each step, infer what the assistant likely did and how the screen changed.  
   - Mark which success criteria have already been completed, and which remain.

4. **Proposed Action Review**  
   a. Rephrase in plain English what the assistant is trying to do.  
   b. Judge whether this makes sense given the current context and progress.  
   c. If the red circle is off-target or the action does not help, state that the score should be ≤5. 
   d. If the action is fully correct and contributes meaningfully to task completion or fixes a past mistake, state that the score should be >5. Specifically, if the current state is already wrong, and the assistant fixes a previous mistake, the score should be higher than 5. EXPLICITLY think about whether the action is fixing a previous mistake.
   Notes for action judgement:
    - For clicking, it does not need to be exactly centered on the element, as long as it is reasonably close.
    - For dragging on sliders, if the knob and direction are correct but the dragging distance is not exact, it can still be considered correct.
    - The assistant cannot type in url, go back to the previous website, or sign in to any website.
    - For final answer, the answer show on the screenshot may be truncated, so focus on the content of the answer provided in text. Do the analysis as other actions. Give score <=5 for final answer only if you are absolutely certain that the answer is incorrect, do not hallucinate about information not provided on the screenshots.

5. **Simulation of Outcomes**  
   a. **Best-case**: if this action executes as intended, what is the best outcome and how likely is it?  
   b. **Worst-case**: if it goes wrong, what’s the worst thing that could happen and how likely is that?

6. **Alternatives Analysis**  
   a. Propose one or more better actions the assistant could take **now**, choosing only from the defined action space.  
   b. Check that these alternatives are viable given what’s visible on screen.  
   c. Rollout likely outcomes for each alternative.  
   d. Compare each alternative to the proposed action — say whether it is **better** or **worse** in terms of task completion.  
   e. If **any alternative** is strictly better, then the proposed action’s score must be ≤6. Otherwise, score may be >6.

7. **Evaluation**  
   - Based on all the above, justify the final expected value.  
   - Reiterate whether the action clearly helps, is harmful, partially helpful, or a missed opportunity.  
   - Factor in whether it obeys constraints and sets up a strong next step.

8. **Expected Value**  
   Final output of the value must be on a single line:
Expected value: <int>, where `<int>` is an integer from 0 to 10.


"""

GPT_STEP_JUDGE_CONCISE = """

You are a **critic** evaluating the **next action** of a computer-use agent. Your task is to judge its **expected value** based on:

1. Whether it helps complete the USER_TASK.
2. Whether it is the **best possible** next action (“no-regret”).

You will be given:
- A `USER_TASK` (what the user wants)
- A sequence of prior screenshots (and zoomed-in crops) with previous assistant actions
- A `PROPOSED_NEXT_ASSISTANT_ACTION`
- The **latest full-screen screenshot** and any **zoomed-in view**, annotated to show where the next action is targeting

---

### Assistant Action Space:
- `click(x, y)`: click at (x, y)
- `scroll(x, y, dx, dy)`: scroll from (x, y) by (dx, dy)
- `keypress(keys)`: press keyboard keys
- `type(text)`: type text (requires focus on an input)
- `wait`: wait for the screen to change
- `screenshot`: capture a new screenshot
- `final_answer(answer)`: return final answer (no screenshot follows)

---

### Screenshot Annotations:
- **Green label** = type of action
- **Red circle** = target position (must land on correct UI element)
- **Red arrow** = direction for scroll/drag actions
- For sliders, knob and drag direction both matter

**Important**: The action has **not yet executed**. Judge only based on what is visible.

---

### Evaluation Procedure: Your task is to follow the steps below, **concisely** output your analysis for each step, then return an integer score in the format `Expected value: <int>`:

1. **Latest Screenshot Analysis**  
   Describe the current screen, red/green overlays, and zoom-ins. Note if the red target is off-element or ambiguous. Update interpretation if visuals contradict the action text.

2. **Success and Rejection Criteria**  
   Define what counts as a successful outcome for the USER_TASK. List what would be incorrect or incomplete.

3. **Progress Analysis**  
   For each prior screenshot/action, infer what was done and what changed. Mark which success criteria are met or still pending.

4. **Proposed Action Review**  
   a. Rephrase the action.  
   b. Assess if it helps, given context.  
   c. If misaligned or ineffective, score must be ≤5.  
   d. If it fixes a mistake or clearly advances the task, score should be >5.  
   Notes:
   - Clicks need not be perfectly centered—just accurate enough.
   - Sliders: correct knob and direction are sufficient.
   - Assistant cannot type URLs, go back, or sign in.
   - For `final_answer`, only judge based on visible answer text—don’t infer hidden content.

5. **Simulation of Outcomes**  
   a. Best-case: what happens if action succeeds?  
   b. Worst-case: what if it fails?

6. **Alternatives Analysis**  
   a. Suggest better next actions (must be in action space).  
   b. Ensure they’re visible and valid.  
   c. Predict likely outcomes.  
   d. Compare to proposed action. If any are clearly better, score must be ≤6.

7. **Evaluation**  
   Justify a score from 0 to 10. Explain whether the action helps, harms, or misses an opportunity.

8. **Expected Value**  
   Output a single line:  
   `Expected value: <int>` (0 = failure, 10 = optimal)
"""


GPT_STEP_JUDGE_SCORE_ONLY = """

You are a critic helping evaluate the next action of a computer-use agent. Your goal is to judge the expected value of the proposed next action based on:

1. Whether it meaningfully contributes to successful completion of the user’s task.
2. Whether it is the most promising possible next action from the assistant's available action space — i.e., a "no-regret" choice.

You will be given:
- A USER_TASK: what the user wants the assistant to do.
- A sequence of prior screenshots (including any zoomed-in crops), each corresponding to one earlier assistant action.
- A single PROPOSED_NEXT_ASSISTANT_ACTION.
- The latest full-screen screenshot and zoomed-in image (if any), annotated with red/green visual guides for where the proposed action is targeting.

------------------------
Assistant action space includes:
- `click(x, y)`: click at coordinates (x, y)
- `scroll(x, y, scroll_x, scroll_y)`: scroll at (x, y) by the pixel amounts (scroll_x, scroll_y)
- `keypress(keys)`: press keys like "Enter", "Ctrl+A", etc.
- `type(text)`: type a string (must click on an input first)
- `wait`: wait for page to change or update
- `screenshot`: take a new screenshot
- `final_answer(answer)`: output the final answer to the user (no screenshot will be given with this)

------------------------
SCREENSHOT ANNOTATION CONVENTIONS:
- The top-left green label (e.g. “click”) is the **type of action**, not where it occurs.
- The **red circle** is the exact target position for a click, scroll, or drag — the assistant’s mouse cursor will land there. It must be on the correct element.
- For **scroll actions**, a red arrow shows scroll direction, and red circle marks scroll origin.
- For **drag actions**, red circle marks the start point, red arrow marks direction.
- For sliders, the specific knob dragged and direction both matter. Always examine drag annotations carefully.

IMPORTANT: The assistant has **not yet executed** the proposed action. You must judge its value **before it runs**, based on what is visible on screen.

------------------------
Your task is to follow the 8 steps below, expliclty output your analysis for the step Proposed Action Review, and directly output an integer score in the format `Expected value: <int>`, where:

- 0 = guaranteed task failure or irreversible error
- 10 = guaranteed task success and no better alternative action exists
- 5 = a borderline step that is either only partially correct or may be outperformed by a better next action
------------------------

1. **Latest Screenshot Analysis**  
   - Then analyze the **latest full screenshot**: describe relevant UI elements visible, current screen state, and the annotation overlays (red circles/arrows, green labels).  
   - Describe any **zoomed-in** image(s). For each, examine where the red circle is at: if it's not directly on an interactive element, say so explicitly (e.g. “not centered on any element”). If a web element (such as a search button) is small, it could be partially obscured by the red circle, pay close attention to such details.
   - If red annotations suggest a different intent than the textual action description, update the interpretation accordingly.  

2. **Success and Rejection Criteria**  
   - Break down the USER_TASK into **specific, verifiable success conditions**.  
   - Define what would count as incorrect or incomplete (rejection criteria).  

3. **Progress Analysis**  
   - Go through EACH screenshot and earlier action.  
   - For each step, infer what the assistant likely did and how the screen changed.  
   - Mark which success criteria have already been completed, and which remain.

4. **Proposed Action Review**  
   a. Rephrase in plain English what the assistant is trying to do.  
   b. Judge whether this makes sense given the current context and progress.  
   c. If the red circle is off-target or the action does not help, state that the score should be ≤5. 
   d. If the action is fully correct and contributes meaningfully to task completion or fixes a past mistake, state that the score should be >5. Specifically, if the current state is already wrong, and the assistant fixes a previous mistake, the score should be higher than 5. EXPLICITLY think about whether the action is fixing a previous mistake.
   Notes for action judgement:
    - For clicking, it does not need to be exactly centered on the element, as long as it is reasonably close.
    - For dragging on sliders, if the knob and direction are correct but the dragging distance is not exact, it can still be considered correct.
    - The assistant cannot type in url, go back to the previous website, or sign in to any website.
    - For final answer, the answer show on the screenshot may be truncated, so focus on the content of the answer provided in text. Do the analysis as other actions. Give score <=5 for final answer only if you are absolutely certain that the answer is incorrect, do not hallucinate about information not provided on the screenshots.

5. **Simulation of Outcomes**  
   a. **Best-case**: if this action executes as intended, what is the best outcome and how likely is it?  
   b. **Worst-case**: if it goes wrong, what’s the worst thing that could happen and how likely is that?

6. **Alternatives Analysis**  
   a. Propose one or more better actions the assistant could take **now**, choosing only from the defined action space.  
   b. Check that these alternatives are viable given what’s visible on screen.  
   c. Rollout likely outcomes for each alternative.  
   d. Compare each alternative to the proposed action — say whether it is **better** or **worse** in terms of task completion.  
   e. If **any alternative** is strictly better, then the proposed action’s score must be ≤6. Otherwise, score may be >6.

7. **Evaluation**  
   - Based on all the above, justify the final expected value.  
   - Reiterate whether the action clearly helps, is harmful, partially helpful, or a missed opportunity.  
   - Factor in whether it obeys constraints and sets up a strong next step.

8. **Expected Value**  
   Final output of the value must be on a single line:
Expected value: <int>, where `<int>` is an integer from 0 to 10.


"""

OG_GPT_STEP_JUDGE = """
You are a critic helping an assistant, and you are evaluating the expected value of an assistant proposed next action in leading to successful task completion of a given user task AND being the most promising next action out of all possible next assistant actions (no regrets).

The user will give you a user task and assistant system message, the latest (up to MAX_IMAGES) screenshots from the assistant trying to complete the user task, and the proposed next action from the assistant along with zoomed in sections of the latest screenshot indicating which elements the assistant proposing to localize and interact with (if any). 

Note: While the assistant must follow the assistant system message instructions, the proposed next action you must evaluate contains only the action itself without any discussion or reward that would normally be in the proposed next assistant response. Also, localize_and_unnormalize function calls present in the proposed next action will have the element description field removed so you can focus on the normalized_x and normalized_y coordinates themselves, but assume that the element description will correctly be in the actual proposed next assistant response and assume that the proposed next action you need to evaluate will actually execute without errors from the code interpreter -- you just need to evaluate the expected value of executing the proposed next action in leading to successful task completion of the user task AND being the most promising next action.

Your goal is to analyze the latest screenshot, decompose and define the task completion success criteria, analyze the current assistant progress, re-state your understanding of the proposed next assistant action, simulate rollouts of likely future states and actions, analyze the assistant's best next alternative actions, evaluate the expected value of the proposed response in completing the user task and being the most promising next action, and conclude with a final expected value for the proposed response.

Specifically, your task is to:
1) Latest Screenshot Analysis - First, thoroughly describe the zoomed in images (if any) and then what specifically the red circles are centered on in the zoomed in images if there are any zoomed in images and red circles. The zoomed in images are just cropped sections of the latest screenshot so you should thoroughly describe all elements in the zoomed in images to get a better understanding of where exactly the red circles are. If there are indeed red circles in the zoomed in images and latest screenshot, describe what elements the red circles in the latest screenshot and zoomed in images are pointing at and the elements' purpose, and specifically what icon or text is inside the circles (if any). If you aren't sure of exactly what icon or text is inside the circles, say the potential options and descriptions like the red circle is hovering over an element that looks like <description 1> or <description 2> etc. Prioritize objectivity and accuracy over brevity. If the center point of the circles are not directly hovering over any element, just say that the red circle seems to not be hovering over any element. Be strict because the red circle is exactly where the cursor will move to, so if it's close to neighboring elements but not directly on top of them, then it's not on those neighboring elements.

If there are zoomed in images and red circles in the latest screenshot, you **MUST** say "Updated proposed next assistant action: ..." and fill in ONLY redacted element descriptions based on what the red circles are centered on, but ONLY change the element description argument value for just the localize_element_and_unnormalize function calls in the proposed next assistant action with ONLY what the red circles are centered on. If the red circles are not centered directly over anything but close to other things, you MUST say element_description="Not directly hovering over anything but close to XYZ" to be very descriptive yet precise. All other parts of the action MUST be the same. Also, there might be misleading variable names in the action that do not match up with the actual element descriptions or where the red circles are, always fill in the element descriptions with where the red circles are even if the red circles are in the wrong position. You're trying to be objective as a critic and evaluate correctness, not trying to fix the assistant's code.

Then, describe the latest computer screenshot and all relevant elements on the screenshot to build strong contextual understanding of the latest screenshot and what the latest action was. If you see any zoomed in images or red circles in the latest screenshot, they represent the assistant's proposed localization elements and coordinates to interact with - especially focus on describing the zoomed in image and red circles if there are any.

2) Success and rejection criteria - Decompose the user task into different parts that need to be completed and validated to consider the task as completed (success criteria), and what factors would mean that the task is not completed successfully (rejection critera). Ensure your success and rejection criteria are very strict to maximize user satisfaction of task completion. You **MUST** follow the assistant system message rules though such as no taking irreversible actions without user approval, etc. as the assistant must still abide by these and the expected values are based on user satisfaction of task completion.

3) Progress Analysis - Go through EACH screenshot to figure out exactly what steps the assistant was taking and analyze if any of the success criteria were completed and what's still left to be completed. Note: you must cover every screenshot of what action likely took place so you don't mistakenly think part of the success criteria was not completed when it was actually completed.

4) Proposed Next Assistant Action - a) re-state your understanding of the proposed next assistant action based on the current state analysis and the proposed next assistant action AND b) if the proposed next assistant action makes sense or not and why based on the progress analysis and success and rejection criteria AND c) if the proposed next assistant action is only partially correct and does not fully make sense, say that the expected value should be negative, otherwise if the action makes full sense and is fully correct, say that the expected value should be positive. If there is a localize_and_unnormalize command in the proposed action, then you should restate exactly what element the assistant is localizing and interacting with based on the red circles in the latest screenshot and zoomed in screenshots provided. If there is not a localize_and_unnormalize command, then you should restate the proposed action in plain language.

5) Simulation - In a few paragraphs, rollout the most likely a) best case potential gain and b) worst case riskiest risk of potential future state(s) and action(s) and their likelihoods based on the current state after the assistant executes the proposed response as its next action. 

6) Alternatives Analysis - a) Generate the assistant's best next alternative actions based on the success and rejection criteria and the progress analysis and current screenshot, b) checking if the alternative actions' elements (if any) are currently in the current screenshot, c) do rollouts for each of those actions. Then d) do a quick comparison analysis based on the current state and screenshot between each alternative and the proposed action to determine if the alternative action is better or worse than the proposed action in terms of successful task completion and user satisfaction. This is to determine if the proposed action is the current most promising next action out out the possible next assistant actions. Make sure you double check the latest screenshot to ground your analysis and alternatives evaluation. e) If the proposed action is strictly worse than one of the alternative actions that can be taken, you MUST say that the proposed action should have an expected value lower than 0.5. Otherwise, if the proposed action is better than or equal to the correctness of the alternative actions that can be taken, then you should say that the proposed action should have an expected value higher than 0.5.

7) Evaluation - According to the success criteria, current state analysis, alternatives analysis, and simulation results, reason what would be an appropriate expected value score and why. An expected value score of -1.00 = the lowest expected value, negative progress like taking an irreversible unwanted action that will guarantee task failure, and that any other action is better than the proposed action. An expected value score of 1.00 = the highest reward, positive progress like taking a desired action that will guarantee perfect task completion, and that no other action can possibly be better than the proposed action (no regrets). Actions that do not fully make sense MUST have negative scores. Only actions that FULLY make sense can have positive scores.

8) Expected Value - Provide a final answer for the expected value score from -1.00 to 1.00.

User task: USER_TASK

Proposed next assistant action: PROPOSED_NEXT_ASSISTANT_ACTION

Assistant system message: ASSISTANT_SYSTEM_MESSAGE

Respond in the following format (no fancy formatting, just vanilla text like the following):
Latest Screenshot Analysis: <first describe the zoomed in images (if any) and what the red circles are centered on in the last given screenshot and zoomed in images. if there are red circles, you **MUST** say "Updated proposed next assistant action: ..." and fill in the redacted element descriptions based on exactly what the red circles are centered on even if the element descriptions of where the red circles are seem wrong. if it's not directly centered on anything, you MUST update the element description to "Not centered directly on any element". Then, describe the latest screenshot in great depth to build extremely strong contextual understanding of the latest screenshot and what the current state is.>

Success and rejection criteria: <decompose the user task into different parts that need to be completed and validated to consider the task as completed (success criteria), and what factors would mean that the task is not completed successfully (rejection critera). ensure your success and rejection criteria are very strict to maximize user satisfaction of task completion.>

Progress analysis: <go through EACH screenshot to figure out exactly what steps the assistant have taken and analyze which of the success criteria are completed and what parts of the success criteria still need to be completed.>

Proposed action: <a) restate your understanding of the proposed next assistant action based on the latest screenshot analysis and current state analysis and the proposed next assistant action AND b) if the proposed next assistant action makes sense or not and why based on the progress analysis and success and rejection criteria AND c) if the proposed next assistant action is only partially correct and does not fully make sense, say that the expected value should be negative, otherwise if the action makes full sense and is fully correct, say that the expected value should be positive. if localize_and_unnormalize is in the action, you MUST reference the red circles and zoomed in images from the latest screenshot analysis as that is ground truth as elements that WILL be interacted with.>

Simulation: <rollout of the most likely a) best case and potential gain and b) worst case and riskiest risk possibilities of future states and actions and their probabilities of occuring in terms of successful task completion and user satisfaction. specifically, if the assistant action executes the proposed action as intended, what's the best thing that could happen and what's the worst thing that could happen in terms of successful task completion and user satisfaction.>

Alternatives analysis: <a) analysis on what the assistant's best alternative actions currently are, b) checking if the alternative actions' elements (if any) are currently in the current screenshot, c) rolling them out for comparison of what the true most promising next action is, d) marking each alternative as better or worse than the proposed action based on the current state and screenshot in terms of successful task completion and user satisfaction, and e) saying if the proposed action is strictly worse than any of the alternative actions or not AND saying that "the expected value score should be less than 0.5" if the proposed action is strictly worse than one of the alternative actions or "the expected value score should be more than 0.5" if the proposed action is better than or equal to the correctness of all the alternative actions>

Evaluation: <according to the success and rejection criteria, progress analysis, proposed action, simulation results, and alternatives analysis, reason what would be an appropriate expected value of leading to successful task completion of the user task AND being the most promising next action out of all possible next actions and why. actions that do not fully make sense MUST have negative scores.>

Expected value: <based on the evaluation result, provide an expected value of type float from -1.00 to 1.00, in the format of `<float>` in a single line to reflect the expected value>
"""