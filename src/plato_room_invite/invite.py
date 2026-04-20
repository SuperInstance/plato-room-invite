"""Room invites — token generation with expiry, usage limits, roles, batch creation, revocation."""
import time
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict
from enum import Enum

class InviteStatus(Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    REVOKED = "revoked"

@dataclass
class RoomInvite:
    token: str
    room: str
    created_by: str = ""
    role: str = "member"
    max_uses: int = 1
    uses: int = 0
    expires_at: float = 0.0
    status: InviteStatus = InviteStatus.PENDING
    created_at: float = field(default_factory=time.time)
    claimed_by: list[str] = field(default_factory=list)
    note: str = ""
    metadata: dict = field(default_factory=dict)

class RoomInviteSystem:
    def __init__(self, token_length: int = 16, max_invites_per_room: int = 100):
        self.token_length = token_length
        self.max_invites_per_room = max_invites_per_room
        self._invites: dict[str, RoomInvite] = {}  # token → invite
        self._by_room: dict[str, list[str]] = defaultdict(list)  # room → [tokens]
        self._by_agent: dict[str, list[str]] = defaultdict(list)  # agent → [tokens created]
        self._claim_log: list[dict] = []

    def create(self, room: str, created_by: str = "", role: str = "member",
              max_uses: int = 1, expires_hours: float = 24.0, note: str = "") -> RoomInvite:
        if len(self._by_room[room]) >= self.max_invites_per_room:
            self._revoke_oldest(room)
        token = secrets.token_urlsafe(self.token_length)
        expires_at = time.time() + (expires_hours * 3600) if expires_hours > 0 else 0.0
        invite = RoomInvite(token=token, room=room, created_by=created_by, role=role,
                           max_uses=max_uses, expires_at=expires_at, note=note)
        self._invites[token] = invite
        self._by_room[room].append(token)
        self._by_agent[created_by].append(token)
        return invite

    def create_batch(self, room: str, count: int, created_by: str = "",
                    role: str = "member", expires_hours: float = 24.0) -> list[RoomInvite]:
        return [self.create(room, created_by, role, 1, expires_hours,
                           f"Batch invite #{i+1}") for i in range(count)]

    def claim(self, token: str, agent_id: str) -> Optional[RoomInvite]:
        invite = self._invites.get(token)
        if not invite:
            return None
        if invite.status == InviteStatus.REVOKED:
            return None
        if invite.status == InviteStatus.EXPIRED:
            return None
        if invite.expires_at > 0 and invite.expires_at < time.time():
            invite.status = InviteStatus.EXPIRED
            return None
        if invite.uses >= invite.max_uses:
            return None
        invite.uses += 1
        invite.claimed_by.append(agent_id)
        if invite.uses >= invite.max_uses:
            invite.status = InviteStatus.CLAIMED
        self._claim_log.append({"token": token, "agent": agent_id, "room": invite.room,
                               "role": invite.role, "timestamp": time.time()})
        return invite

    def revoke(self, token: str) -> bool:
        invite = self._invites.get(token)
        if invite and invite.status == InviteStatus.PENDING:
            invite.status = InviteStatus.REVOKED
            return True
        return False

    def revoke_all(self, room: str, created_by: str = "") -> int:
        count = 0
        for token in self._by_room.get(room, []):
            invite = self._invites.get(token)
            if invite and invite.status == InviteStatus.PENDING:
                if not created_by or invite.created_by == created_by:
                    invite.status = InviteStatus.REVOKED
                    count += 1
        return count

    def _revoke_oldest(self, room: str):
        tokens = self._by_room.get(room, [])
        if not tokens:
            return
        oldest = min(tokens, key=lambda t: self._invites[t].created_at)
        self.revoke(oldest)

    def get(self, token: str) -> Optional[RoomInvite]:
        return self._invites.get(token)

    def room_invites(self, room: str) -> list[RoomInvite]:
        tokens = self._by_room.get(room, [])
        return [self._invites[t] for t in tokens if t in self._invites]

    def agent_invites(self, agent_id: str) -> list[RoomInvite]:
        tokens = self._by_agent.get(agent_id, [])
        return [self._invites[t] for t in tokens if t in self._invites]

    def purge_expired(self) -> int:
        now = time.time()
        purged = 0
        for invite in self._invites.values():
            if invite.expires_at > 0 and invite.expires_at < now and invite.status == InviteStatus.PENDING:
                invite.status = InviteStatus.EXPIRED
                purged += 1
        return purged

    def claim_history(self, room: str = "", limit: int = 50) -> list[dict]:
        log = self._claim_log
        if room:
            log = [e for e in log if e["room"] == room]
        return log[-limit:]

    @property
    def stats(self) -> dict:
        total = len(self._invites)
        pending = sum(1 for i in self._invites.values() if i.status == InviteStatus.PENDING)
        claimed = sum(1 for i in self._invites.values() if i.status == InviteStatus.CLAIMED)
        return {"total": total, "pending": pending, "claimed": claimed,
                "rooms": len(self._by_room), "claims": len(self._claim_log)}
