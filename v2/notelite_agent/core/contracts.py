from dataclasses import dataclass


@dataclass(frozen=True)
class AccessContext:
    user_id: str
    role: str = "user"
    tenant_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def apply_scope(self, base_filter=None):
        scope = dict(base_filter or {})
        if self.tenant_id:
            scope["tenant_id"] = self.tenant_id

        if self.is_admin:
            return scope

        if not self.user_id:
            raise ValueError("AccessContext.user_id is required for non-admin requests.")
        if not self.tenant_id:
            raise ValueError("AccessContext.tenant_id is required for non-admin requests.")

        if "user_id" in scope and scope["user_id"] != self.user_id:
            raise PermissionError("Users can only access their own data.")
        if "tenant_id" in scope and scope["tenant_id"] != self.tenant_id:
            raise PermissionError("Users can only access their own tenant data.")

        scope["user_id"] = self.user_id
        return scope
