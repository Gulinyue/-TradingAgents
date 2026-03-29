from abc import ABC, abstractmethod
from typing import Any, Optional


def normalize_content(response):
    """Normalize LLM response content to a plain string.

    Multiple providers return content as a list of typed blocks:
    - dict: {'type': 'text', 'text': '...'}
    - Pydantic TextBlock: TextBlock(type='text', text='...')
    - Pydantic ThinkingBlock: ThinkingBlock(type='thinking', thinking='...')
    Downstream agents expect response.content to be a plain string.
    This extracts and joins text blocks, discarding thinking/reasoning blocks.
    """
    content = response.content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
            elif hasattr(item, "type"):
                if item.type == "text" and hasattr(item, "text"):
                    texts.append(item.text)
                # ThinkingBlock.type == "thinking": skip
            elif isinstance(item, str):
                texts.append(item)
        response.content = "\n".join(t for t in texts if t)
    return response


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs

    @abstractmethod
    def get_llm(self) -> Any:
        """Return the configured LLM instance."""
        pass

    @abstractmethod
    def validate_model(self) -> bool:
        """Validate that the model is supported by this client."""
        pass
