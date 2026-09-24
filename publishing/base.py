"""
Common interface for platform publishers.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class PublishError(RuntimeError):
    pass


@dataclass
class PublishResult:
    status: str                 # 'posted' or 'draft' (sent to the app to finish there)
    remote_id: str
    url: Optional[str] = None
    extra: Dict = field(default_factory=dict)


@dataclass
class Metrics:
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None
    raw: Dict = field(default_factory=dict)


class Publisher:
    name = 'base'

    def configured(self) -> Tuple[bool, str]:
        """(ready, reason-if-not)."""
        raise NotImplementedError

    def publish(self, video_path: Path, cover_path: Optional[Path], metadata: Dict,
                cover_time_ms: int = 0) -> PublishResult:
        raise NotImplementedError

    def post_comment(self, remote_id: str, text: str) -> None:
        """Optional: comment on our own post to start the conversation."""

    def fetch_metrics(self, remote_ids: List[str]) -> Dict[str, Metrics]:
        return {}


def check_response(response, what: str) -> Dict:
    """Raise PublishError with the API's own message on HTTP errors."""
    try:
        body = response.json()
    except ValueError:
        body = {'text': response.text[:500]}
    if response.status_code >= 400:
        raise PublishError(f'{what} failed ({response.status_code}): {body}')
    return body
