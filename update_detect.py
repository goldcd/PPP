import os
import re

file_path = 'app/detect_adverts.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# We want to replace the sys_msg definition block.
# We'll use a regex to capture everything from `sys_msg = (` up to the `user_msg = f"Transcript Segment` line.

new_prompt_code = '''
    sys_msg = (
        "You are a podcast content segmenter.\\n"
        "Your purpose is to carefully analyze this provided segment of the show and partition it chronologically into distinct topics.\\n"
        "A simple way to consider this task, is that you're being asked to create the chapter markings for a podcast.\\n"
        "Your first step, before doing anything else, is to read the entire provided segment of the show from start to finish.\\n\\n"
    )
    
    if previous_context:
        sys_msg += f"CRITICAL CONTEXT FROM PREVIOUS CHUNK:\\n{previous_context}\\n\\n"
        
    sys_msg += (
        "CRITICAL INSTRUCTION: Break the transcript into the distinct topics.\\n"
        "For each topic, identify:\\n"
        "1. Short title\\n"
        "2. Start block index and end block index (inclusive)\\n"
        "3. Category: Choose exactly one of: 'show_content', 'sponsor_read', 'podcast_promotion', 'self_promotion', 'intro_outro'.\\n\\n"
        "Category Definitions:\\n"
        "- 'show_content': Primary show conversation, stories, news, interviews, or banter.\\n"
        "- 'intro_outro': Standard show intro theme, greeting, outro wrap-up, or ending credits.\\n"
        "- 'self_promotion': Promotion of the podcast itself or its hosts.\\n"
        "- 'sponsor_read': Commercial pitches/advertisements for EXTERNAL companies/products/services.\\n"
        "- 'podcast_promotion': Promos/trailers/credits for OTHER podcasts.\\n\\n"
        "CRITICAL OUTPUT INSTRUCTIONS:\\n"
        f"- Every single provided block from {min_idx} to {max_idx} MUST be included in a topic.\\n"
        "- The topics must be strictly contiguous with no gaps (e.g. 101-110, 111-115, 116-150).\\n"
        "- Do not skip or orphan any blocks.\\n"
        "- You MUST return ONLY a valid JSON object matching this structure:\\n"
        "{\\n"
        "  \\"analysis\\": \\"I will walk through the text chronologically. Block X to Y is banter... Block Z to W is an ad...\\",\\n"
        "  \\"topics\\": [\\n"
        "    {\\n"
        "      \\"title\\": \\"Segment name\\",\\n"
        "      \\"start_idx\\": 101,\\n"
        "      \\"end_idx\\": 119,\\n"
        "      \\"category\\": \\"sponsor_read\\",\\n"
        "      \\"confidence\\": \\"certain\\"\\n"
        "    }\\n"
        "  ]\\n"
        "}\\n\\n"
        "ADDITIONAL CLASSIFICATION RULES:\\n"
        "1. Teaser / Cross-Promotions: Hosts often promote OTHER podcasts by playing an audio snippet or discussing its topics (like an interview). The ENTIRE teaser is a `podcast_promotion`.\\n"
        "2. Post-Ad Banter: If hosts banter about the sponsor's product immediately after the pitch, this is STILL part of the `sponsor_read`.\\n"
        "3. Break Transitions: Phrases like \\"We'll be back\\" or \\"Let's take a quick break\\" are `show_content`.\\n"
        "4. Legal Disclaimers: \\"Terms and conditions apply\\" MUST be included at the end of the `sponsor_read`.\\n"
    )

'''

# Find the start of sys_msg
start_idx = content.find('    sys_msg = (')
# Find the start of user_msg
end_idx = content.find('    # Format the user message to include the actual transcript subset')

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + new_prompt_code + content[end_idx:]

# Also update num_ctx
content = content.replace('"num_ctx": 6144', '"num_ctx": 8192')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated successfully")
