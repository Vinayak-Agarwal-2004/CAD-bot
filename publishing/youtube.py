"""
YouTube Shorts via the YouTube Data API v3.

Setup (once):
  1. Google Cloud console -> enable "YouTube Data API v3".
  2. Create an OAuth client of type "Desktop app", download the JSON to
     secrets/youtube_client_secret.json.
  3. `python main.py auth youtube` and approve in the browser.

A vertical video under 3 minutes is classified as a Short automatically.
Each upload costs ~1600 of the default 10,000 daily quota units.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from publishing.base import Metrics, PublishError, PublishResult, Publisher

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.force-ssl',   # comments, playlists, stats
]


class YouTubePublisher(Publisher):
    name = 'youtube'

    def __init__(self, client_secrets: Path, token_file: Path, privacy: str = 'public',
                 category_id: str = '28', playlist_id: str = ''):
        self.client_secrets = Path(client_secrets)
        self.token_file = Path(token_file)
        self.privacy = privacy
        self.category_id = category_id
        self.playlist_id = playlist_id
        self._service = None

    def configured(self) -> Tuple[bool, str]:
        try:
            import googleapiclient  # noqa: F401
        except ImportError:
            return False, 'pip install google-api-python-client google-auth-oauthlib'
        if not self.token_file.exists():
            if not self.client_secrets.exists():
                return False, f'missing {self.client_secrets} (OAuth desktop client JSON)'
            return False, 'run `python main.py auth youtube` first'
        return True, ''

    # ------------------------------------------------------------ auth
    def authorize(self, interactive: bool = False):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.token_file.write_text(creds.to_json())
        if not creds or not creds.valid:
            if not interactive:
                raise PublishError('YouTube token missing or revoked: run `python main.py auth youtube`')
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets), SCOPES)
            # Prints a URL to open; on a headless server, forward the port (ssh -L).
            creds = flow.run_local_server(port=8765, open_browser=False)
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(creds.to_json())
        return creds

    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build
            self._service = build('youtube', 'v3', credentials=self.authorize(), cache_discovery=False)
        return self._service

    # ------------------------------------------------------------ actions
    def publish(self, video_path: Path, cover_path: Optional[Path], metadata: Dict,
                cover_time_ms: int = 0) -> PublishResult:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        meta = metadata['youtube']
        body = {
            'snippet': {
                'title': meta['title'],
                'description': meta['description'],
                'tags': meta['tags'],
                'categoryId': self.category_id,
                'defaultLanguage': 'en',
                'defaultAudioLanguage': 'zxx',  # no spoken language
            },
            'status': {
                'privacyStatus': self.privacy,
                'selfDeclaredMadeForKids': False,
                'embeddable': True,
            },
        }
        media = MediaFileUpload(str(video_path), mimetype='video/mp4', chunksize=8 * 1024 * 1024,
                                resumable=True)
        try:
            request = self.service().videos().insert(part='snippet,status', body=body, media_body=media)
            response = None
            while response is None:
                _, response = request.next_chunk(num_retries=3)
        except HttpError as exc:
            raise PublishError(f'YouTube upload failed: {exc}') from exc

        video_id = response['id']
        if self.playlist_id:
            try:
                self.service().playlistItems().insert(part='snippet', body={'snippet': {
                    'playlistId': self.playlist_id,
                    'resourceId': {'kind': 'youtube#video', 'videoId': video_id}}}).execute()
            except HttpError as exc:
                logger.warning('Could not add to playlist: %s', exc)
        return PublishResult('posted', video_id, f'https://youtube.com/shorts/{video_id}')

    def post_comment(self, remote_id: str, text: str) -> None:
        self.service().commentThreads().insert(part='snippet', body={'snippet': {
            'videoId': remote_id,
            'topLevelComment': {'snippet': {'textOriginal': text}}}}).execute()

    def fetch_metrics(self, remote_ids: List[str]) -> Dict[str, Metrics]:
        results = {}
        for start in range(0, len(remote_ids), 50):
            batch = remote_ids[start:start + 50]
            response = self.service().videos().list(part='statistics', id=','.join(batch)).execute()
            for item in response.get('items', []):
                s = item.get('statistics', {})
                results[item['id']] = Metrics(
                    views=int(s.get('viewCount', 0)), likes=int(s.get('likeCount', 0)),
                    comments=int(s.get('commentCount', 0)), raw=s)
        return results
