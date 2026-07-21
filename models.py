from dataclasses import dataclass
import uuid 
from uuid_extensions import uuid7str
from datetime import timezone
from datetime import datetime

@dataclass(frozen=True, slots=True)
class NetworkMetric:
    id: uuid.UUID
    download: float
    upload: float
    ping: float
    timestamp: datetime
    share: str
    client: str
    server: str
    bytes_sent: int
    bytes_received: int

    @classmethod
    def create(
        cls,
        download: float,
        upload: float,
        ping: float,
        share: str,
        client: str,
        server: str,
        bytes_sent: int,
        bytes_received: int
    ) -> "NetworkMetric":
        if download < 0:
            raise ValueError("download must be non-negative")
        if upload < 0:
            raise ValueError("upload must be non-negative")
        if ping < 0:
            raise ValueError("ping must be non-negative")
        if bytes_sent  < 0:
            raise ValueError("bytes_sent must be non-negative")
        if bytes_received < 0:
            raise ValueError("bytes_received must be non-negative")
        if not client or not client.strip():
            raise ValueError("client cannot be empty")
        if not server or not server.strip():
            raise ValueError("server cannot be empty")

        return cls(
            id=uuid.UUID(uuid7str()), 
            download=download,
            upload=upload,
            ping=ping,
            timestamp=datetime.now(timezone.utc),          
            share=share,
            client=client,
            server=server,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received
        )


@dataclass(frozen=True, slots=True)
class NetworkDevice:
    id: uuid.UUID
    ip: str
    latency_ms: float 
    timestamp: datetime 

    @classmethod
    def create(
        cls,
        ip: str,
        latency_ms: float,
    ) -> "NetworkDevice":
        if not ip or not ip.strip():
            raise ValueError("IP cannot be empty")
        if latency_ms < 0:
            raise ValueError("Latency must be non-negative")
    
        return cls(
            id=uuid.UUID(uuid7str()),
            ip=ip,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc)
        )


@dataclass(frozen=True, slots=True)
class SpeedTest:
    id: uuid.UUID
    metric_id: uuid.UUID
    device_scan_id: uuid.UUID

    @classmethod
    def create(cls, metric_id: uuid.UUID, device_scan_id: uuid.UUID) -> "SpeedTest":
        return cls(
            id=uuid.UUID(uuid7str()),
            metric_id=metric_id,
            device_scan_id=device_scan_id
        )
