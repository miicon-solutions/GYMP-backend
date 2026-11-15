from ipaddress import ip_address

from django.conf import settings


def client_ip(request):
    remote = request.META.get("REMOTE_ADDR", "unknown")
    trusted = set(settings.TRUSTED_PROXY_IPS)
    if remote not in trusted:
        return remote
    chain = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") + [remote]
    try:
        normalized = [str(ip_address(part.strip())) for part in chain if part.strip()]
    except ValueError:
        return remote
    return next((part for part in reversed(normalized) if part not in trusted), remote)
