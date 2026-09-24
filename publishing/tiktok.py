"""
TikTok via the Content Posting API.

Setup: create an app at developers.tiktok.com with the Content Posting API
(scopes video.upload for drafts, video.publish for direct posts, video.list
for stats), authorise your account and set TIKTOK_ACCESS_TOKEN.

Modes (TIKTOK_MODE):
- 'draft'  -> the video lands in your TikTok inbox; open the app, add a
              trending sound and post. Trending sounds can't be attached
              through the API, and they're one of the biggest reach levers.
- 'direct' -> posts straight away. Apps that haven't passed TikTok's audit
              can only post privately (SELF_ONLY).
"""
import logging
import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from publishing.base import Metrics, PublishError, PublishResult, Publisher, check_response

logger = logging.getLogger(__name__)

API = 'https://open.tiktokapis.com/v2'
MAX_SINGLE_CHUNK = 64 * 1024 * 1024
CHUNK_SIZE = 10 * 1024 * 1024


def chunk_plan(size: int) -> Tuple[int, int]:
    """(chunk_size, total_chunk_count) following TikTok's rules: files up to 64 MB go in one
    chunk; otherwise 10 MB chunks with the remainder folded into the last one."""
    if size <= MAX_SINGLE_CHUNK:
        return size, 1
    return CHUNK_SIZE, max(1, math.floor(size / CHUNK_SIZE))


class TikTokPublisher(Publisher):
    name = 'tiktok'

    def __init__(self, access_token: str, mode: str = 'draft', privacy: str = 'PUBLIC_TO_EVERYONE',
                 poll_interval: float = 5.0, poll_timeout: float = 600.0):
        self.token = access_token
        self.mode = mode
        self.privacy = privacy
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.http = requests.Session()

    def configured(self) -> Tuple[bool, str]:
        if not self.token:
            return False, 'set TIKTOK_ACCESS_TOKEN'
        if self.mode not in ('draft', 'direct'):
            return False, "TIKTOK_MODE must be 'draft' or 'direct'"
        return True, ''

    def _call(self, path: str, what: str, payload: Dict) -> Dict:
        response = self.http.post(f'{API}/{path}', json=payload, timeout=60, headers={
            'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json; charset=UTF-8'})
        body = check_response(response, what)
        error = body.get('error', {})
        if error.get('code') not in (None, 'ok'):
            raise PublishError(f"{what} failed: {error.get('code')}: {error.get('message')}")
        return body.get('data', {})

    def publish(self, video_path: Path, cover_path: Optional[Path], metadata: Dict,
                cover_time_ms: int = 0) -> PublishResult:
        size = video_path.stat().st_size
        chunk_size, chunks = chunk_plan(size)
        source = {'source': 'FILE_UPLOAD', 'video_size': size,
                  'chunk_size': chunk_size, 'total_chunk_count': chunks}

        if self.mode == 'direct':
            creator = self._call('post/publish/creator_info/query/', 'query creator info', {})
            options = creator.get('privacy_level_options', [])
            privacy = self.privacy if self.privacy in options else (options[0] if options else 'SELF_ONLY')
            if privacy != self.privacy:
                logger.warning('TikTok privacy %s not allowed for this app/account; using %s',
                               self.privacy, privacy)
            data = self._call('post/publish/video/init/', 'init post', {
                'post_info': {
                    'title': metadata['tiktok']['caption'],
                    'privacy_level': privacy,
                    'disable_comment': False, 'disable_duet': False, 'disable_stitch': False,
                    'video_cover_timestamp_ms': cover_time_ms,
                },
                'source_info': source,
            })
        else:
            data = self._call('post/publish/inbox/video/init/', 'init draft', {'source_info': source})

        self._upload(video_path, data['upload_url'], size, chunk_size, chunks)
        final = self._wait(data['publish_id'])
        post_ids = final.get('publicaly_available_post_id') or []
        remote_id = str(post_ids[0]) if post_ids else data['publish_id']
        status = 'draft' if self.mode == 'draft' else 'posted'
        return PublishResult(status, remote_id, extra={'publish_id': data['publish_id']})

    def _upload(self, video_path: Path, url: str, size: int, chunk_size: int, chunks: int):
        with open(video_path, 'rb') as fh:
            for index in range(chunks):
                start = index * chunk_size
                end = size - 1 if index == chunks - 1 else start + chunk_size - 1
                fh.seek(start)
                blob = fh.read(end - start + 1)
                response = self.http.put(url, data=blob, timeout=600, headers={
                    'Content-Type': 'video/mp4', 'Content-Length': str(len(blob)),
                    'Content-Range': f'bytes {start}-{end}/{size}'})
                if response.status_code >= 400:
                    raise PublishError(f'TikTok upload chunk {index + 1}/{chunks} failed '
                                       f'({response.status_code}): {response.text[:300]}')

    def _wait(self, publish_id: str) -> Dict:
        deadline = time.monotonic() + self.poll_timeout
        done = {'PUBLISH_COMPLETE', 'SEND_TO_USER_INBOX'}
        while time.monotonic() < deadline:
            data = self._call('post/publish/status/fetch/', 'fetch status', {'publish_id': publish_id})
            if data.get('status') in done:
                return data
            if data.get('status') == 'FAILED':
                raise PublishError(f"TikTok rejected the post: {data.get('fail_reason')}")
            time.sleep(self.poll_interval)
        raise PublishError('TikTok processing timed out')

    def fetch_metrics(self, remote_ids: List[str]) -> Dict[str, Metrics]:
        results = {}
        ids = [r for r in remote_ids if r.isdigit()]   # drafts only have a publish_id
        for start in range(0, len(ids), 20):
            data = self._call('video/query/?fields=id,view_count,like_count,comment_count,share_count',
                              'query videos', {'filters': {'video_ids': ids[start:start + 20]}})
            for video in data.get('videos', []):
                results[str(video['id'])] = Metrics(
                    views=video.get('view_count'), likes=video.get('like_count'),
                    comments=video.get('comment_count'), shares=video.get('share_count'), raw=video)
        return results
