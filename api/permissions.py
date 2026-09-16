from rest_framework.permissions import BasePermission

class IsStaff(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and (u.is_superuser or u.role in ('admin', 'manager', 'front', 'expert')))

class IsAdministrator(IsStaff):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and (request.user.is_superuser or request.user.role == 'admin')

class IsFrontDesk(IsStaff):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and (request.user.is_superuser or request.user.role in ('admin', 'manager', 'front'))

class IsInspector(IsStaff):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and (request.user.is_superuser or request.user.role in ('admin', 'expert'))
