"""Room invite — token-based invites with expiration, usage limits, and claim tracking."""
import time
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from collections import defaultdict

class InviteRole(Enum):
    GUEST = "guest"
    MEMBER = "member"
    MODERATOR = "moderator"

class InviteStatus(Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    REVOKED = "revoked"
    MAX_USES = "max_uses"

@dataclass
class InviteToken:
    code: str
    room: str
    creator: str
    role: InviteRole = InviteRole.MEMBER
    max_uses: int = 1
    uses: int = 0
    claimed_by: list[str] = field(default_factory=list)
    status: InviteStatus = InviteStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    note: str = ""

class RoomInvite:
    def __init__(self):
        self._tokens: dict[str, InviteToken] = {}
        self._room_invites: dict[str, list[str]] = defaultdict(list)  # room -> [token_codes]
        self._claim_log: list[dict] = []

    def create(self, room: str, creator: str, role: str = "member",
               max_uses: int = 1, duration: float = 86400 * 7,
               note: str = "") -> InviteToken:
        code = secrets.token_urlsafe(8).lower()
        token = InviteToken(code=code, room=room, creator=creator,
                          role=InviteRole(role), max_uses=max_uses,
                          expires_at=time.time() + duration if duration > 0 else 0.0,
                          note=note)
        self._tokens[code] = token
        self._room_invites[room].append(code)
        return token

    def create_bulk(self, room: str, creator: str, count: int = 5, **kwargs) -> list[InviteToken]:
        return [self.create(room, creator, **kwargs) for _ in range(count)]

    def claim(self, code: str, claimant: str) -> dict:
        token = self._tokens.get(code)
        if not token:
            return {"error": "Invalid invite code"}
        if token.status == InviteStatus.REVOKED:
            return {"error": "Invite revoked"}
        if token.status == InviteStatus.EXPIRED:
            return {"error": "Invite expired"}
        if token.status == InviteStatus.MAX_USES:
            return {"error": "Invite max uses reached"}
        if token.expires_at > 0 and time.time() > token.expires_at:
            token.status = InviteStatus.EXPIRED
            return {"error": "Invite expired"}
        if claimant in token.claimed_by:
            return {"error": "Already claimed"}
        if token.uses >= token.max_uses:
            token.status = InviteStatus.MAX_USES
            return {"error": "Invite max uses reached"}

        token.uses += 1
        token.claimed_by.append(claimant)
        if token.uses >= token.max_uses:
            token.status = InviteStatus.CLAIMED

        entry = {"code": code, "room": token.room, "claimant": claimant,
                "role": token.role.value, "timestamp": time.time()}
        self._claim_log.append(entry)
        if len(self._claim_log) > 2000:
            self._claim_log = self._claim_log[-2000:]

        return {"success": True, "room": token.room, "role": token.role.value,
                "code": code, "remaining_uses": token.max_uses - token.uses}

    def revoke(self, code: str) -> bool:
        token = self._tokens.get(code)
        if token and token.status == InviteStatus.PENDING:
            token.status = InviteStatus.REVOKED
            return True
        return False

    def get(self, code: str) -> Optional[InviteToken]:
        return self._tokens.get(code)

    def room_invites(self, room: str, active_only: bool = True) -> list[InviteToken]:
        codes = self._room_invites.get(room, [])
        tokens = [self._tokens[c] for c in codes if c in self._tokens]
        if active_only:
            tokens = [t for t in tokens if t.status == InviteStatus.PENDING]
        return sorted(tokens, key=lambda t: t.created_at, reverse=True)

    def expire_old(self) -> int:
        now = time.time()
        expired = 0
        for token in self._tokens.values():
            if token.status == InviteStatus.PENDING and token.expires_at > 0 and now > token.expires_at:
                token.status = InviteStatus.EXPIRED
                expired += 1
        return expired

    def claim_history(self, room: str = "", limit: int = 50) -> list[dict]:
        entries = self._claim_log
        if room:
            entries = [e for e in entries if e.get("room") == room]
        return list(reversed(entries))[:limit]

    def creator_invites(self, creator: str) -> list[InviteToken]:
        return [t for t in self._tokens.values() if t.creator == creator]

    def room_members(self, room: str) -> list[str]:
        codes = self._room_invites.get(room, [])
        members = set()
        for code in codes:
            token = self._tokens.get(code)
            if token:
                members.update(token.claimed_by)
        return list(members)

    @property
    def stats(self) -> dict:
        statuses = {}
        for t in self._tokens.values():
            statuses[t.status.value] = statuses.get(t.status.value, 0) + 1
        return {"total_tokens": len(self._tokens), "rooms": len(self._room_invites),
                "total_claims": len(self._claim_log), "by_status": statuses}
