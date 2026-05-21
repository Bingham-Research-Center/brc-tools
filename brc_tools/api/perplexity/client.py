"""Perplexity wrapper using the OpenAI-compatible Sonar endpoint."""

from brc_tools.api._auth import load_api_key


class PerplexityClient:
    """Perplexity Sonar client. Auth via `PERPLEXITY_API_KEY`."""

    BASE_URL = "https://api.perplexity.ai"

    def __init__(self, *, model: str = "sonar"):
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(
            api_key=load_api_key("PERPLEXITY_API_KEY"),
            base_url=self.BASE_URL,
        )

    def ask(self, prompt: str, *, model: str | None = None, **kwargs) -> str:
        """Single-turn query; returns the assistant's text response."""
        resp = self._client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        return resp.choices[0].message.content
