# EXTERNAL LIBRARIES
import discord
import matplotlib.pyplot as plt
import os
import io
import requests

# INTERNAL MODULES
from utils.prompts import SYSTEM_PROMPT
from tools.math_tools import display_latex

from flask import json
from openai import AsyncOpenAI
from groq import Groq
from dotenv import load_dotenv
from collections import deque

from sympy import content, limit

load_dotenv()
_DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

AI_CLIENT = AsyncOpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

tools = [
    {
        "type" : "function",
        "function" : {
            "name" : "get_context",
            "description" : "MANDATORY if the user's message is a follow-up. Fetches the recent chat history to provide context for the current problem.",
            "parameters" : {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer", 
                        "description": "number of messages to look back"
                    }
                },
                "required": ["limit"]
            }
        }
    },
    {
        "type" : "function",
        "function" : {
            # used together with get_context, the model can decide to call get_context to fetch the last N messages from the chat
            # then it can decide if based on the user request, if it needs to fetch an image from the chat history. 
            # if the user request is something like "fetch the image I sent earlier", then the model can decide to call fetch_image 
            # with the appropriate parameters to fetch the image from the chat history.
            "name" : "fetch_image",
            "description" : "fetch an image from the chat history based on a query.",
            "parameters" : {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string", 
                        "description": "the query to search for in the chat history to find the image."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "display_latex",
            "description": (
                "MANDATORY: Use this tool to display any mathematical formulas, integrals, or complex equations. Provide the raw LaTeX string. Example: \int x^2 dx. Do not use markdown code blocks inside the tool call."
                "IMPORTANT: Use SINGLE backslashes for commands (e.g., \int, \pi). "
                "Do NOT double-escape backslashes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "latex_code": {
                        "type": "string",
                        "description": "the LaTeX code to render"
                    }
                },
                "required": ["latex_code"]
            }
        }
    },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "display_tutorial",
    #         "description": "Use this tool to create an interactive tutorial with step-by-step instructions and explanations. This is ideal for guiding users through complex problems or concepts in a structured manner.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "steps": {
    #                     "type": "array",
    #                     "items": {
    #                         "type": "string",
    #                         "description": "A single step in the tutorial, which can include instructions, explanations, or any relevant information for that step."
    #                     },
    #                     "description": "An array of steps that make up the tutorial. Each step should be concise and focused on a specific part of the problem or concept being explained."
    #                 }
    #             },
    #             "required": ["steps"]
    #         }
    #     }
    # }
]

# defining some UI functionality
class TutorialView(discord.ui.View):
    """
    [INCOMPLETE - WORK IN PROGRESS]
    This is a template for a tutorial view that can be used to guide users through a concept or problem step by step.

    It has a "Next Step" button that the user can click to move through the steps of the tutorial. The steps are defined in a list and the view keeps track of the current step. 
    When the user clicks the button, it sends a message with the next step in the tutorial. Once the user reaches the end of the steps, it sends a completion message.

    TODO:
    - Implement a tool call that allows the model to generate steps and descriptions for the problem (ex: math problem, coding)
    - Use the display_latex tool to render any equations or math snippets in the tutorial steps for better readability and understanding.
    - Coding should be rendered using code blocks for better readability.
    """
    def __init__(self, steps, timeout = 180):
        super().__init__(timeout=timeout) # this is the timeout for how long the buttons will be active

        # this is for keeping track of the current step in the tutorial
        self.steps = steps
        self.current_step = 0

    @discord.ui.button(label="Next Step", style=discord.ButtonStyle.primary)
    async def next_step(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_step < len(self.steps) - 1:
            self.current_step += 1
            await interaction.response.send_message(f"Step {self.current_step + 1}: {self.steps[self.current_step]}", ephemeral=True)
        else:
            await interaction.response.send_message("Tutorial complete!", ephemeral=True)



class MyClient(discord.Client):
    def __init__(self, *, intents, **options):
        super().__init__(intents=intents, **options)
        self._PROGRAM_INITIALIZED = False
        self.channel_histories = {}  # Dictionary to store message history for each channel


    async def on_ready(self):
        activity = discord.Game(name="traversing the assimilated universe")
        await self.change_presence(status=discord.Status.online, activity=activity)
        print(f'Logged on as {self.user}!')


    def update_channel_history(self, channel_id, role, content, author_name="User"):
        # ensure there's a history deque for the channel, if not, create one
        if channel_id not in self.channel_histories:
            self.channel_histories[channel_id] = deque(maxlen=50)  # Keep the last 50 messages

        self.channel_histories[channel_id].append({
            "role": role, 
            "content": content, 
            "author": author_name
        })

    

    async def process_message(self, message, content=None):
        # TODO NOTES FOR LATER:
        # we need to fix the issue where
        # if we ask the model to solve a math problem
        # then ask what "that" is, it forgets that it just solved the problem and doesn't know what "that" is.

        # function for processing messages and determining the right tool to use.
        tokens_used = 0
        channel_id = message.channel.id
        last_latex_rendered = ""

        system_instruction = {
            "role": "system", 
            "content": SYSTEM_PROMPT
        }

        message_block = [system_instruction] + [{"role": "user", "content": content}]
        file_produced = None # Update the tool description to encourage self-deciding
     
        # response loop for tool calls
        for _ in range(3):  # allow up to 3 tool calls
            response = await AI_CLIENT.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=message_block,
                tools=tools,
                tool_choice="auto",
                max_tokens=500,
            )

            tokens_used += response.usage.total_tokens
            response_message = response.choices[0].message

            # if the model decides to call a tool
            if response_message.tool_calls:
                # tool_call = response_message.tool_calls[0]

                # log the AI's intent to call a tool 
                message_block.append(response_message)

                for tool_call in response_message.tool_calls:
                    # make sure the json arguments from the model are properly parsed and we can access the parameters for each tool call. this is important for the model to be able to use the tools effectively and for us to be able to execute the correct actions based on the model's intent.
                    try:
                        args_dict = json.loads(tool_call.function.arguments)

                    except json.JSONDecodeError:
                        message_block.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": f"Error: Invalid JSON arguments for tool call '{tool_call.function.name}'. Skipping this tool call."
                        })

                        continue  # skip this tool call if arguments are not valid JSON

                    if tool_call.function.name == "get_context":
                        args_dict = json.loads(tool_call.function.arguments)
                        limit = args_dict.get("limit", 10)

                        # Pull directly from your local deque memory
                        local_history = list(self.channel_histories.get(channel_id, []))
                        
                        # Get the most recent N messages
                        context_messages = local_history[-limit:]

                        # include author name so if we ask "who was speaking 3 messages ago?" the model can refer to the author in the context
                        formatted_context = "\n".join([
                            f"{msg.get('author_name')} (ID: {msg.get('author_id')}): {msg['content']}" 
                            for msg in context_messages
                        ])

                        # --- DEBUG PRINT START ---
                        print(f"\n[DEBUG] Context Sent to AI for Channel {channel_id}:")
                        print("-" * 30)
                        print(formatted_context)
                        print("-" * 30 + "\n")
                        # --- DEBUG PRINT END ---

                        # Send the context back to the model
                        message_block.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": "get_context",
                            "content": f"Local Context (limit {limit}):\n" + formatted_context
                        })


                    # image tool call
                    # does not work currently
                    elif tool_call.function.name == "fetch_image":
                        args_dict = json.loads(tool_call.function.arguments)
                        query = args_dict.get("query", "").lower() # Case-insensitive

                        image_url = None
                        
                        # We look back 100 messages to find the actual file
                        async for msg in message.channel.history(limit=100):
                            # 1. Check if the text matches OR if the filename matches
                            text_match = query in msg.content.lower()
                            file_match = msg.attachments and query in msg.attachments[0].filename.lower()
                            
                            # 2. Logic fix: If we found a match and it has an image, grab it
                            if (text_match or file_match) and msg.attachments:
                                image_url = msg.attachments[0].url
                                break
                        
                        message_block.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": "fetch_image",
                            "content": f"Found image URL: {image_url}" if image_url else f"No image found for '{query}'."
                        })


                    # latex tool call
                    elif tool_call.function.name == "display_latex":
                        args_dict = json.loads(tool_call.function.arguments)
                        latex_input = args_dict.get("latex_code", "")

                        clean_latex, file_produced = await display_latex(latex_input)

                        last_latex_rendered = clean_latex  # Store the last rendered LaTeX for context in future responses
                        
                        if file_produced:
                            message_block.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": "display_latex",
                                "content": f"Successfully rendered LaTeX: {file_produced.filename}"
                            })
                        else:
                            message_block.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": "display_latex",
                                "content": f"Failed to render LaTeX image."
                            })
                    
                    # continue if a tool was called, otherwise break the loop and return the response
                continue
            else:
                break
            

        text_response = response_message.content or "Rendering complete."

        history_entry = text_response
        if last_latex_rendered:
            history_entry += f"\n[System Note: Assistant rendered this LaTeX: {last_latex_rendered}]"

        self.update_channel_history(channel_id, "user", content, author_name=message.author.display_name)  # we use display name over username for better readability in the context, so if the model calls get_context to fetch the last few messages, it can refer to the author by their display name which is more natural.
        self.update_channel_history(channel_id, "assistant", history_entry, author_name="PRTS")  # Update history with assistant response
        
        return {"content": text_response, "file": file_produced, "tokens": tokens_used}
    
  
    async def on_message(self, message):
        # print(f'Message from {message.author}: {message.content}')
        if message.author == client.user:
            return
        
        # ignore messages from other bots to prevent infinite loops
        if message.author.bot:
            return
        
        # check if message is a reply to the bot. we want the bot to respond to replies too
        is_reply = False
        if message.reference and message.reference.resolved and message.reference.resolved.author == client.user:
            is_reply = True
        
        if message.content.startswith('PRTS') or is_reply:
            msg = message.content.removeprefix('PRTS').lstrip(' ,:;').strip()

            # user_memory = self.retrieve_memory(message.author.id)
            # user_memory.append({"role": "user", "content": msg})

            # if message.author.id != AUTHORIZED_USER_ID:
         
            
            # message is the message object, which we need to pass to the tool function in order to fetch the message history.
            # content is the content of the message, which we need to pass to the model in order for it to determine which tool to call and what to do with the tool response.
            result = await self.process_message(message, content=msg)

            token_count = result.pop("tokens", 0) 
            print(f"Tokens used: {token_count}")
        
            content = result.get("content", "")
            file_to_send = result.get("file") 

            if len(content) > 2000:
                chunks = [content[i:i+2000] for i in range(0, len(content), 2000)]
                
                for i, chunk in enumerate(chunks):
                    # Attach the file and reference only to the first message chunk
                    if i == 0:
                        await message.channel.send(content=chunk, file=file_to_send, reference=message)
                    else:
                        await message.channel.send(content=chunk)
            else:
                # Use the extracted 'file_to_send' variable
                await message.channel.send(content=content, file=file_to_send, reference=message)

        
        

            
intents = discord.Intents.default()
intents.message_content = True

client = MyClient(intents=intents)
client.run(_DISCORD_TOKEN)
