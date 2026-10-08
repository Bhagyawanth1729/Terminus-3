"""Recovery lease fencing."""

from __future__ import annotations

from datetime import datetime, timedelta

from .model import ContractError, FencingError, LeaseToken, to_iso, utcnow


class FencingMixin:
    def acquire_recovery_lease(
        self,
        *,
        region: str,
        owner_id: str,
        ttl_seconds: int,
        at: datetime | None = None,
    ) -> LeaseToken:
        now = at or utcnow()
        if ttl_seconds <= 0:
            raise ContractError("ttl_seconds must be positive")
        current = self.store.current_lease(region)
        if current is None:
            epoch = 1
            acquired_at = now
        elif current.owner_id == owner_id and not current.expired(now):
            epoch = current.fence_epoch
            acquired_at = current.acquired_at
        elif current.expired(now):
            epoch = current.fence_epoch + 1
            acquired_at = now
        else:
            raise FencingError(
                f"recovery lease for {region} is owned by {current.owner_id} until {to_iso(current.expires_at)}"
            )
        return self.store.write_lease(
            region=region,
            owner_id=owner_id,
            fence_epoch=epoch,
            acquired_at=acquired_at,
            renewed_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

    def assert_recovery_fence(
        self,
        *,
        region: str,
        owner_id: str,
        fence_epoch: int,
        at: datetime | None = None,
    ) -> LeaseToken:
        current = self.store.current_lease(region)
        if current is None:
            raise FencingError(f"region {region} has no recovery lease")
        current.assert_current(
            owner_id=owner_id,
            fence_epoch=fence_epoch,
            at=at or utcnow(),
        )
        return current
