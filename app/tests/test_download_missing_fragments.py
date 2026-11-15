"""A real local HLS transfer must fail instead of publishing missing video."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
import yt_dlp

from src.core.audio.download_runtime import DownloadFailure
from src.core.audio.extractor import _download_via_ytdlp


def test_missing_media_fragment_never_becomes_a_completed_download(tmp_path):
    visited = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            visited.append(self.path)
            if self.path == '/video.m3u8':
                body = b'#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1,\nfirst.ts\n#EXTINF:1,\nmissing.ts\n#EXT-X-ENDLIST\n'
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
            elif self.path == '/first.ts':
                body = b'\x47'+b'\0'*187
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp2t')
            else:
                self.send_error(404)
                return
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}/video.m3u8'
        with pytest.raises(DownloadFailure):
            _download_via_ytdlp(url, tmp_path, lambda *_:None, link_media_mode='video')
        assert '/missing.ts' in visited
        assert not list(tmp_path.glob('*.mp4'))
        assert not list(tmp_path.glob('*.ts'))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
