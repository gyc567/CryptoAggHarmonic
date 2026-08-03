# Description: This module contains the functions for handling OpenAI API requests.
import json
import logging
import os

from app.infra.llm_client import get_llm_client

# Re-export for backwards compatibility with existing imports.
_get_client = get_llm_client

logging.basicConfig(level=logging.INFO)

# Read model config lazily on first use.
_openai_api_model: str | None = None


def _get_model() -> str:
    global _openai_api_model
    if _openai_api_model is None:
        _openai_api_model = os.getenv("OPENAI_API_MODEL", "gpt-3.5-turbo")
    return _openai_api_model


def parse_args(string):
    """
    Parses the given string into Python variables.

    Args:
        string: The openai response string to be parsed and converted into Python variables.
    Returns:
        A tuple containing the parsed function name, args and kwargs.
    """
    try:
        data = json.loads(string)
        logging.info(f"Data: {data}")
        function_name = data.get("function_name", "")
        args = data.get("args", [])
        kwargs = data.get("kwargs", {})
        logging.info(f"preparing to call {function_name}({args}, {kwargs})")
        return function_name, args, kwargs
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON string: {string}")
    except Exception as e:
        print(f"Error: {e}")
    return None, None, None


def query_openai(prompt, developer_content, model=None):
    """
    Determines the intent of the given prompt.

    Args:
        prompt: The user prompt to be analyzed.
        developer_content: The developer content to be sent to OpenAI.
        model: The model to be used for the OpenAI API call. Defaults to the environment variable model if not provided.
    Returns:
        A string containing the response from OpenAI or an error message.
    """
    logging.debug(f"Prompt: {prompt}")
    logging.debug(f"Developer content: {developer_content}")
    logging.debug(f"Model: {model}")
    try:
        response = get_llm_client().chat.completions.create(
            model=model or _get_model(),
            messages=[{"role": "developer", "content": developer_content}, {"role": "user", "content": prompt}],
            max_tokens=100,
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Error: {e}")
        return f"Error: {e}"
