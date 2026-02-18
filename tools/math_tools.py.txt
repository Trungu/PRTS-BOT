"""
This module provides tools for mathematical operations, including rendering LaTeX code into images using the CodeCogs API. 

The function, `display_latex`, takes a LaTeX string, cleans it, and returns a Discord file object containing the rendered image if successful.
"""

import requests
import io
import discord

async def display_latex(latex_code: str) -> str:
    """
    Cleans LaTeX code and fetches a rendered image from CodeCogs.
    Returns a tuple of (cleaned_code, discord_file_or_None).
    """
    # clean the code. 
    cleaned_code = latex_code.replace("\\\\", "\\").replace("\n", " ")
    
    encoded_latex = cleaned_code.replace(" ", "&space;")
    url = f"https://latex.codecogs.com/png.latex?\\dpi{{300}}\\color{{white}}{encoded_latex}"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            # Create the Discord file object
            file_produced = discord.File(
                io.BytesIO(response.content), 
                filename="rendered_latex.png"
            )
            return cleaned_code, file_produced
    except Exception as e:
        print(f"[ERROR] LaTeX Render failed: {e}")

    return cleaned_code, None