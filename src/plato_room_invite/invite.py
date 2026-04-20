"""Room invitation management."""
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

class InviteStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"

@dataclass
class InviteCode:
    code: str
    room: str
    invited_by: str
    invited_agent: str = ""
    role: str = "member"
    status: InviteStatus = InviteStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    max_uses: int = 1
    uses: int = 0

class RoomInvite:
    def __init__(self, code_length: int = 8, default_ttl: float = 86400):
        self.code_length = code_length
        self.default_ttl = default_ttl
        self._codes: dict[str, InviteCode] = {}

    def create(self, room: str, invited_by: str, invited_agent: str = "",
               role: str = "member", ttl: float = 0, max_uses: int = 1) -> InviteCode:
        code = secrets.token_urlsafe(self.code_length)[:self.code_length]
        now = time.time()
        invite = InviteCode(code=code, room=room, invited_by=invited_by,
                          invited_agent=invited_agent, role=role,
                          expires_at=now + ttl if ttl > 0 else now + self.default_ttl,
                          max_uses=max_uses)
        self._codes[code] = invite
        return invite

    def accept(self, code: str, agent: str = "") -> tuple[bool, str]:
        invite = self._codes.get(code)
        if not invite:
            return False, "Invalid code"
        if invite.status == InviteStatus.REVOKED:
            return False, "Invite revoked"
        if invite.status == InviteStatus.EXPIRED:
            return False, "Invite expired"
        if invite.expires_at > 0 and time.time() > invite.expires_at:
            invite.status = InviteStatus.EXPIRED
            return False, "Invite expired"
        if invite.uses >= invite.max_uses:
            return False, "Invite already used"
        invite.status = InviteStatus.ACCEPTED
        invite.uses += 1
        invite.invited_agent = agent or invite.invited_agent
        return True, f"Accepted to {invite.room} as {invite.role}"

    def revoke(self, code: str) -> bool:
        invite = self._codes.get(code)
        if invite and invite.status == InviteStatus.PENDING:
            invite.status = InviteStatus.REVOKED
            return True
        return False

    def validate(self, code: str) -> tuple[bool, str]:
        invite = self._codes.get(code)
        if not invite:
            return False, "Invalid"
        if invite.status == InviteStatus.REVOKED:
            return False, "Revoked"
        if invite.status == InviteStatus.EXPIRED:
            return False, "Expired"
        if invite.status == InviteStatus.ACCEPTED and invite.uses >= invite.max_uses:
            return False, "Fully used"
        if invite.expires_at > 0 and time.time() > invite.expires_at:
            invite.status = InviteStatus.EXPIRED
            return False, "Expired"
        return True, f"Valid for {invite.room}"

    def purge_expired(self) -> int:
        now = time.time()
        expired = [c for c, inv in self._codes.items()
                  if inv.expires_at > 0 and now > inv.expires_at and inv.status != InviteStatus.ACCEPTED]
        for c in expired:
            self._codes[c].status = InviteStatus.EXPIRED
        return len(expired)

    def for_room(self, room: str) -> list[InviteCode]:
        return [inv for inv in self._codes.values() if inv.room == room]

    @property
    def stats(self) -> dict:
        statuses = {}
        for inv in self._codes.values():
            statuses[inv.status.value] = statuses.get(inv.status.value, 0) + 1
        return {"total": len(self._codes), "statuses": statuses}
