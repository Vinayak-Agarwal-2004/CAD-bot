"""
Instagram Reels via the Instagram Graph API (professional account required).

Setup: create a Meta app with the Instagram API, connect a Business/Creator
account, grant instagram_content_publish + instagram_manage_comments +
instagram_manage_insights, then set INSTAGRAM_USER_ID and a long-lived
INSTAGRAM_ACCESS_TOKEN. With "Instagram Login" tokens set
GRAPH_API_HOST=graph.instagram.com.

The video is uploaded directly (resumable upload). If PUBLIC_MEDIA_BASE_URL
is set, Instagram fetches the file from that URL instead.
"""
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from publishing.base import Metrics, PublishError, PublishResult, Publisher, check_response

logger = logging.getLogger(__name__)

INSIGHT_METRICS = ['views', 'reach', 'likes', 'comments', 'shares', 'saved']


class InstagramPublisher(Publisher):
    name = 'instagram'

    def __init__(self, user_id: str, access_token: str, api_version: str = 'v21.0',
                 host: str = 'graph.facebook.com', public_base_url: str = '',
                 poll_interval: float = 10.0, poll_timeout: float = 900.0):
        self.user_id = user_id
        self.token = access_token
        self.base = f'https://{host}/{api_version}'
        self.public_base_url = public_base_url.rstrip('/')
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.http = requests.Session()

    def configured(self) -> Tuple[bool, str]:
        if not (self.user_id and self.token):
            return False, 'set INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN'
        return True, ''

    def _post(self, path: str, what: str, **data) -> Dict:
        data['access_token'] = self.token
        return check_response(self.http.post(f'{self.base}/{path}', data=data, timeout=60), what)

    def _get(self, path: str, what: str, **params) -> Dict:
        params['access_token'] = self.token
        return check_response(self.http.get(f'{self.base}/{path}', params=params, timeout=60), what)

    def publish(self, video_path: Path, cover_path: Optional[Path], metadata: Dict,
                cover_time_ms: int = 0) -> PublishResult:
        caption = metadata['instagram']['caption']
        common = {'media_type': 'REELS', 'caption': caption, 'share_to_feed': 'true',
                  'thumb_offset': str(cover_time_ms)}
        if self.public_base_url:
            container = self._post(f'{self.user_id}/media', 'create reel container',
                                   video_url=f'{self.public_base_url}/{video_path.name}', **common)
        else:
            container = self._post(f'{self.user_id}/media', 'create reel container',
                                   upload_type='resumable', **common)
            upload_uri = container.get('uri')
            if not upload_uri:
                raise PublishError(f'Instagram did not return an upload URI: {container}')
            size = video_path.stat().st_size
            with open(video_path, 'rb') as fh:
                check_response(self.http.post(upload_uri, data=fh, timeout=600, headers={
                    'Authorization': f'OAuth {self.token}', 'offset': '0', 'file_size': str(size)}),
                    'upload reel video')

        container_id = container['id']
        self._wait_until_ready(container_id)
        published = self._post(f'{self.user_id}/media_publish', 'publish reel', creation_id=container_id)
        media_id = published['id']
        permalink = None
        try:
            permalink = self._get(media_id, 'get permalink', fields='permalink').get('permalink')
        except PublishError as exc:
            logger.warning('%s', exc)
        return PublishResult('posted', media_id, permalink)

    def _wait_until_ready(self, container_id: str):
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            status = self._get(container_id, 'check container', fields='status_code,status')
            code = status.get('status_code')
            if code == 'FINISHED':
                return
            if code in ('ERROR', 'EXPIRED'):
                raise PublishError(f'Instagram processing failed: {status}')
            time.sleep(self.poll_interval)
        raise PublishError('Instagram processing timed out')

    def post_comment(self, remote_id: str, text: str) -> None:
        self._post(f'{remote_id}/comments', 'post comment', message=text)

    def fetch_metrics(self, remote_ids: List[str]) -> Dict[str, Metrics]:
        results = {}
        for media_id in remote_ids:
            try:
                data = self._get(f'{media_id}/insights', 'fetch insights',
                                 metric=','.join(INSIGHT_METRICS)).get('data', [])
            except PublishError as exc:
                logger.warning('%s', exc)
                continue
            values = {}
            for entry in data:
                if 'total_value' in entry:
                    values[entry['name']] = entry['total_value'].get('value')
                elif entry.get('values'):
                    values[entry['name']] = entry['values'][0].get('value')
            results[media_id] = Metrics(
                views=values.get('views'), likes=values.get('likes'), comments=values.get('comments'),
                shares=values.get('shares'), saves=values.get('saved'), raw=values)
        return results
