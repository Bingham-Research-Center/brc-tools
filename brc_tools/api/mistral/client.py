"""Mistral chat-completions wrapper around the official `mistralai` SDK."""

from brc_tools.api._auth import load_api_key


class MistralClient:
    """Mistral client. Auth via `MISTRAL_API_KEY`."""

    def __init__(self, *, model: str = "mistral-small-latest"):
        from mistralai import Mistral

        self.model = model
        self._client = Mistral(api_key=load_api_key("MISTRAL_API_KEY"))

    def chat(self, messages: list[dict], *, model: str | None = None, **kwargs) -> str:
        """Multi-turn chat; returns the assistant's text response.

        `messages` is a list of {"role": "user"|"assistant"|"system",
        "content": str} dicts.
        """
        resp = self._client.chat.complete(
            model=model or self.model,
            messages=messages,
            **kwargs,
        )
        return resp.choices[0].message.content
