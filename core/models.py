from __future__ import annotations
from dataclasses import dataclass, field

@dataclass(slots=True)
class FileEntry:
    index: int
    path: str
    size: int
    progress: float = 0.0
    priority: int = 4

@dataclass(slots=True)
class TrackerEntry:
    url: str
    tier: int = 0
    status: str = ""

@dataclass(slots=True)
class PeerEntry:
    ip: str
    client: str = ""
    progress: float = 0.0
    download_rate: int = 0
    upload_rate: int = 0

@dataclass(slots=True)
class TorrentStatusInfo:
    info_hash: str
    name: str
    state: str
    progress: float
    download_rate: int
    upload_rate: int
    total_download: int
    total_upload: int
    num_seeds: int
    num_peers: int
    eta_seconds: int | None
    save_path: str
    paused: bool = False
    error: str = ""
    files: list[FileEntry] = field(default_factory=list)
    trackers: list[TrackerEntry] = field(default_factory=list)
    peers: list[PeerEntry] = field(default_factory=list)
